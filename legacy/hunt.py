"""
Job hunt: two separated parts connected by a LangGraph graph.

  SEARCH part (no LLM for navigation, no clicks: everything by URL)
    criteria -> results page -> next offer -> read offer (new tab) -> keyword filter -> YOU decide
  APPLY part (agent.apply_offer: the LLM tool-calling loop, unchanged)

              +----------+
              | criteria |  ask query, location, mandatory/excluded keywords (saved in criteria.json)
              +----+-----+
                   v
              +----------+   no new offer on this page -> next page (up to max_pages) -> end
        +---->| results  |   results tab: always kept open, never clicked
        |     +----+-----+
        |          v
        |     +----------+   queue empty -> back to results (next page)
        +-----|   pick   |<----------------------------------+
              +----+-----+                                   |
                   v                                         |
              +----------+   offer opened in a NEW TAB       |
              |   read   |   mandatory keywords missing ---->+ (saved as 'filtered')
              +----+-----+                                   |
                   v                                         |
              +----------+   s = skip ---------------------->+ (saved as 'skipped')
              |  decide  |   q = quit -> end                 |
              +----+-----+                                   |
                   v  a = apply                              |
              +----------+                                   |
              |  apply   |  agent.apply_offer ---------------+
              +----------+

Usage (start_chrome.bat first):
  python hunt.py                 # asks the criteria
  python hunt.py --last          # reuse criteria.json without asking
  python hunt.py --recheck       # also show again the offers you skipped before

Offers already APPLIED are never shown again. Offers 'filtered' by keywords are re-checked
with the current keywords at every hunt (changing keywords never hides offers forever).
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, END
from playwright.sync_api import sync_playwright

import agent
import db
import search
from explore import Session


# Statuses never shown again / shown again only with --recheck. Everything else (new, filtered,
# stuck, ready_for_review) is RE-EVALUATED with the current criteria at each hunt.
DONE_STATUSES = {"applied", "interview", "rejected", "offer", "no_answer"}
RECHECK_STATUSES = {"skipped", "external_apply"}
DEAD_PAGE = re.compile(r"page introuvable|page not found|offre (n'est plus|expir)|no longer available", re.I)


class HuntState(TypedDict, total=False):
    criteria: dict
    page_no: int
    queue: list            # cards of the current results page not processed yet
    current: dict          # the offer being looked at
    seen: list             # job keys already handled in this session
    stats: dict
    stop: bool


class Browser:
    """Browser objects live outside the graph state (not serializable)."""
    def __init__(self, session: Session):
        self.s = session
        self.results = session.ctx.new_page()       # the results tab, kept for the whole hunt
        self.offer = None                           # the current offer tab


def build_graph(br: Browser, con, run_dir: Path, ask=input, recheck: bool = False):

    # ---------------------------------------------------------------- nodes
    def node_results(st: HuntState) -> HuntState:
        url = search.results_url(st["criteria"], st["page_no"])
        print(f"\n=== results page {st['page_no'] + 1}: {url[:110]}")
        br.results.goto(url)
        br.results.wait_for_load_state("domcontentloaded")
        time.sleep(1.5)
        cards = br.results.evaluate(search.RESULTS_JS)
        fresh = []
        for c in cards:
            c["url"] = search.offer_url(c, br.results.url)
            if c["jk"] in st["seen"]:
                continue
            row = db.find(con, c["url"])
            if row and (row["status"] in DONE_STATUSES or (row["status"] in RECHECK_STATUSES and not recheck)):
                key = f"known_{row['status']}"           # already applied / you said no before
                st["stats"][key] = st["stats"].get(key, 0) + 1
                continue
            fresh.append(c)
        print(f"    {len(cards)} offers on the page, {len(fresh)} new")
        return {"queue": fresh, "stats": st["stats"]}

    def node_pick(st: HuntState) -> HuntState:
        queue = list(st["queue"])
        cur = queue.pop(0)
        return {"queue": queue, "current": cur, "seen": st["seen"] + [cur["jk"]]}

    def node_read(st: HuntState) -> HuntState:
        cur = dict(st["current"])
        br.offer = br.s.ctx.new_page()                    # NEW TAB: results stay where they are
        br.offer.goto(cur["url"])
        br.offer.wait_for_load_state("domcontentloaded")
        time.sleep(1)
        title, text = agent.read_offer_text(br.offer)
        title = re.sub(r"\s+-\s+Indeed\.com$", "", title).strip()
        if DEAD_PAGE.search(title) or len(text) < 60:      # expired / removed offer: nothing to save
            print(f"  - {cur['title'][:60]} -> offer page unavailable, skipped")
            cur.update(keywords_ok=False)
            _close_offer_tabs(br)
            return {"current": cur}
        ok, reason, matched = search.keyword_check(text, st["criteria"])
        cur.update(keywords_ok=ok, reason=reason, matched=matched)
        if not ok:
            print(f"  - {cur['title'][:60]} | {cur['company'][:30]}  -> filtered ({reason})")
            app_id = db.upsert_offer(con, cur["url"], {"title": title, "company": cur["company"],
                                                       "location": cur["location"]}, text)
            db.update(con, app_id, status="filtered", notes=reason)
            st["stats"]["filtered"] += 1
            _close_offer_tabs(br)
            return {"current": cur, "stats": st["stats"]}
        offer, description, usage = agent.extract_offer(br.offer)     # LLM: structured fields
        cur["app_id"] = db.upsert_offer(con, cur["url"], offer, description)
        cur["offer"], cur["usage"] = offer, usage
        return {"current": cur}

    def node_decide(st: HuntState) -> HuntState:
        cur, o = st["current"], st["current"]["offer"]
        print("\n" + "-" * 70)
        print(f"#{cur['app_id']}  {o.get('title')}  |  {o.get('company')}")
        print(f"     {o.get('location')} | {o.get('contract_type')} | {o.get('remote')} | salary: {o.get('salary')}")
        print(f"     experience: {o.get('experience_required')}")
        skills = o.get("skills") or []
        print(f"     skills: {', '.join(skills) if isinstance(skills, list) else skills}")
        print(f"     {o.get('summary')}")
        print(f"     contact: {o.get('contact_name') or '-'} | {o.get('contact_email') or '-'} | "
              f"{o.get('contact_phone') or '-'}")
        if cur.get("matched"):
            print(f"     keywords found: {', '.join(cur['matched'])}")
        print(f"     {cur['url']}")
        ans = ask("Apply? [a = apply / s = skip / q = quit] > ").strip().lower()
        decision = {"a": "apply", "s": "skip", "q": "quit"}.get(ans[:1], "skip")
        if decision != "apply":
            db.update(con, cur["app_id"], status="skipped")
            st["stats"]["skipped"] += 1
            _close_offer_tabs(br)
        return {"current": {**cur, "decision": decision}, "stop": decision == "quit", "stats": st["stats"]}

    def node_apply(st: HuntState) -> HuntState:
        cur = st["current"]
        offer_dir = run_dir / f"offer-{cur['app_id']}"
        offer_dir.mkdir(parents=True, exist_ok=True)
        result = agent.apply_offer(br.s, br.offer, cur["url"], con, cur["app_id"], cur["usage"], offer_dir)
        status = con.execute("SELECT status FROM applications WHERE id=?", (cur["app_id"],)).fetchone()[0]
        st["stats"][status] = st["stats"].get(status, 0) + 1
        if status != "ready_for_review":         # sent, external or stuck: clean the tabs
            _close_offer_tabs(br)
        br.results.bring_to_front()
        return {"stats": st["stats"]}

    # ---------------------------------------------------------------- routing
    def after_results(st):
        if st["queue"]:
            return "pick"
        if st["page_no"] + 1 < st["criteria"]["max_pages"]:
            return "next_page"
        return END

    def next_page(st: HuntState) -> HuntState:
        return {"page_no": st["page_no"] + 1}

    def after_pick_or_done(st):
        return "pick" if st["queue"] else ("next_page" if st["page_no"] + 1 < st["criteria"]["max_pages"] else END)

    g = StateGraph(HuntState)
    g.add_node("results", node_results)
    g.add_node("next_page", next_page)
    g.add_node("pick", node_pick)
    g.add_node("read", node_read)
    g.add_node("decide", node_decide)
    g.add_node("apply", node_apply)

    g.set_entry_point("results")
    g.add_conditional_edges("results", after_results, {"pick": "pick", "next_page": "next_page", END: END})
    g.add_edge("next_page", "results")
    g.add_edge("pick", "read")
    g.add_conditional_edges("read", lambda st: "decide" if st["current"]["keywords_ok"] else "continue",
                            {"decide": "decide", "continue": "continue"})
    g.add_conditional_edges("decide", lambda st: st["current"]["decision"],
                            {"apply": "apply", "skip": "continue", "quit": END})
    g.add_edge("apply", "continue")
    # "continue": a no-op node that routes to the next offer / page / end
    g.add_node("continue", lambda st: {})
    g.add_conditional_edges("continue", after_pick_or_done, {"pick": "pick", "next_page": "next_page", END: END})
    return g.compile()


def _close_offer_tabs(br: Browser):
    """Close every tab except the results tab (offer page, smartapply form...)."""
    for pg in list(br.s.ctx.pages):
        if pg is not br.results and pg.url.startswith("http"):
            try:
                pg.close()
            except Exception:
                pass
    br.offer = None


def hunt(criteria: dict | None = None, ask=input, recheck: bool = False):
    agent.check_llm_server()
    criteria = criteria or search.ask_criteria()
    run_dir = Path("runs") / ("hunt-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True)
    (run_dir / "criteria.json").write_text(json.dumps(criteria, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"model={agent.MODEL}  logs -> {run_dir}")
    con = db.connect()
    with sync_playwright() as p:
        br = Browser(Session(p))
        graph = build_graph(br, con, run_dir, ask, recheck)
        state = graph.invoke(
            {"criteria": criteria, "page_no": 0, "queue": [], "seen": [], "stop": False,
             "stats": {"filtered": 0, "skipped": 0}},
            {"recursion_limit": 500})
        print("\n" + "=" * 70 + "\nHUNT FINISHED:", json.dumps(state["stats"]))
        print("python jobs.py list   -> all offers seen and applications")
        try:
            br.results.close()
        except Exception:
            pass
        br.s.close()
    return state


if __name__ == "__main__":
    recheck = "--recheck" in sys.argv          # also show again offers you skipped / external ones
    if "--last" in sys.argv and search.CRITERIA_FILE.exists():
        hunt(search.load_criteria(), recheck=recheck)
    else:
        hunt(recheck=recheck)
