"""
SCAN graph: runs alone (scheduled), never asks anything.

Searches of one scan (config.toml [search]): every source x every query, then the pasted URLs.
  browser sources (indeed, linkedin): results pages read in the agent Chrome
  email sources (indeed_email, linkedin_email): the offers of the new job-alert emails (one "page")
All of them feed the same chain below. An offer met twice in one scan (2 queries, browser + email) is
handled once; across scans the dedupe node decides.

  results -> pick -> dedupe -> read -> prefilter -> judge -> store -> auto_gate -> [apply_auto] -> pick ...
     ^                  |         |                                                       |
     |               dead page  filtered                                       queue empty: next page / next search
     +---------------------------------------------------------------------------------------+-> notify -> END

Every node is a small function calling one module of nodes/. To change a step, change its module.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, END

from core import avoid, db
from core.config import CONFIG, ROOT
from nodes import store
from nodes.dedupe import already_applied, applied_elsewhere, seen_before
from nodes.apply import apply
from nodes.judge import judge
from nodes.notify import report
from nodes.prefilter import prefilter
from nodes.read import challenge, read_offer
from nodes.sources import get_source, mail
from core import human, telegram



class ScanState(TypedDict, total=False):
    searches: list          # [{"source": "indeed", "query": "AI engineer"}, {"source": "linkedin_email"}, {"source":..., "url": ...}]
    blocked: list           # sources stopped for this scan (login wall, mailbox error)
    mails: list             # [(message_id, source, offers)] marked as read at the end (mail_seen)
    search_i: int
    page_no: int
    queue: list
    current: dict
    seen: list
    found: list
    stats: dict


class Ctx:
    """Things that are not data (browser, db): kept out of the graph state."""
    def __init__(self, session, con, run_dir: Path):
        self.s, self.con, self.run_dir = session, con, run_dir
        self.results = session.new_tab()
        self.offer = None
        self.agent = None

    @staticmethod
    def pause(platform: str) -> float:
        return float(CONFIG.get(platform, {}).get("pause_seconds", 1.5))


def _bump(st, key, n=1):
    st["stats"][key] = st["stats"].get(key, 0) + n
    return st["stats"]


def build(c: Ctx):
    search_cfg, auto = CONFIG["search"], CONFIG["auto_apply"]

    def cleared(page, source: str) -> bool:
        """An anti-bot / captcha page (Indeed: "Vérification supplémentaire requise")? You are watching
        ([auto_apply] supervised / --supervised): you solve it in the agent Chrome (terminal or Telegram).
        Nobody there: the source stops for this scan (the offers are NOT judged, they come back next scan)."""
        why = challenge(page)
        if not why:
            return True
        print(f"    ! {source}: verification page instead of the page (\"{why}\")")
        if auto.get("supervised"):
            for attempt in range(3):
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                ans = human.ask(f"\a\n>>> HUMAN NEEDED in the {source} Chrome window: verification / captcha page "
                                f"(\"{why}\").\n    Solve it, then press Enter.  'skip' = stop {source} for this scan > ")
                if ans.strip().lower() in ("skip", "s"):
                    break
                page.wait_for_timeout(1500)
                if challenge(page) and attempt == 0:
                    try:
                        page.reload(wait_until="domcontentloaded")
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass
                if not challenge(page):
                    print("    verification solved: going on")
                    return True
        print(f"    ! {source} stopped for this scan (verification page): its offers will be read next scan")
        telegram.send(f"🛑 {source}: verification / captcha page -- {source} stopped for this scan. "
                      "Open its agent Chrome and solve it before the next scan.", "errors")
        return False

    def results(st):
        search = st["searches"][st["search_i"]]
        src = get_source(search["source"])
        stop = {"queue": [], "stats": st["stats"], "page_no": search["max_pages"] - 1}      # -> next search
        if search["source"] in st["blocked"]:
            return stop
        label = search.get("query") or ("new alert emails" if src.KIND == "email" else "pasted URL")
        all_read = False                                  # True: every page read at once (SORT_BY_DATE)
        if src.KIND == "email":
            print(f"\n=== search {st['search_i'] + 1}/{len(st['searches'])} {search['source']} [{label}]")
            try:
                msgs = mail.new_messages(c.con, search["source"], src.SENDERS)
            except mail.MailError as e:
                print(f"    ! {e}")
                return {**stop, "blocked": st["blocked"] + [search["source"]], "stats": _bump(st, f"blocked_{search['source']}")}
            cards, mails = [], list(st["mails"])
            for m in msgs:
                found = src.parse(m["text"])
                cards += found
                mails.append((m["message_id"], search["source"], len(found)))
            print(f"    {len(msgs)} new emails, {len(cards)} offers")
            for card in cards:
                card["url"] = src.offer_url(card)
        else:
            def one_page(n):
                url = src.results_url({**search_cfg, "query": search.get("query", "")}, n, search.get("url"))
                print(f"\n=== search {st['search_i'] + 1}/{len(st['searches'])} {search['source']} [{label}], "
                      f"page {n + 1}/{search['max_pages']}: {url[:100]}")
                c.results.goto(url)
                c.results.wait_for_load_state("domcontentloaded")
                time.sleep(c.pause(src.PLATFORM))
                found = c.results.evaluate(src.RESULTS_JS)
                if not found and challenge(c.results):          # the results page itself is a captcha
                    if not cleared(c.results, search["source"]):
                        return found, "verification page (captcha): solve it in the agent Chrome"
                    found = c.results.evaluate(src.RESULTS_JS)
                return found, getattr(src, "blocked", lambda u, cs, t="": None)(c.results.url, found, c.results.title())

            if getattr(src, "SORT_BY_DATE", False):
                # the site cannot sort by date: read every page first, then newest first
                cards, ids, pages = [], set(), 0
                for n in range(st["page_no"], search["max_pages"]):
                    found, why = one_page(n)
                    if why and not cards:
                        print(f"    ! {why}")
                        return {**stop, "blocked": st["blocked"] + [search["source"]],
                                "stats": _bump(st, f"blocked_{search['source']}")}
                    new = [x for x in found if x["jk"] not in ids]
                    if why or not new:
                        break                     # empty page, or the same offers again: no more pages
                    ids |= {x["jk"] for x in new}
                    cards, pages = cards + new, pages + 1
                cards.sort(key=lambda x: x.get("published") or "", reverse=True)   # undated ones last
                print(f"    {len(cards)} offers on {pages} page(s), newest first"
                      + (f" ({cards[0].get('published')} .. {cards[-1].get('published')})" if cards else ""))
                all_read = True
            else:
                cards, why = one_page(st["page_no"])
                if why:
                    print(f"    ! {why}")
                    return {**stop, "blocked": st["blocked"] + [search["source"]], "stats": _bump(st, f"blocked_{search['source']}")}
            for card in cards:
                card["url"] = src.offer_url(card, c.results.url)
            mails = st["mails"]
        queue, again, done_there = [], 0, 0
        for card in cards:
            card["source"], card["platform"] = search["source"], src.PLATFORM
            card["key"] = f"{src.PLATFORM}:{card['jk']}"
            if card["key"] in st["seen"] or card["key"] in {q["key"] for q in queue}:
                again += 1                        # already met in this scan (other page, query or source): free skip
                continue
            if card.get("applied_on_board"):      # the site says you applied (by hand): nothing to do
                done_there += 1
                continue
            queue.append(card)
        if again:
            _bump(st, "already_seen_this_run", again)
        if done_there:
            _bump(st, "applied_on_the_site", done_there)
        print(f"    {len(queue)} offers to process" + (f" ({again} already found by an earlier search)" if again else ""))
        out = {"queue": queue, "stats": st["stats"], "mails": mails}
        if not cards and src.KIND == "browser":
            out["page_no"] = search["max_pages"] - 1          # empty page: no next page
        elif cards and again == len(cards) and src.KIND == "browser":
            out["page_no"] = search["max_pages"] - 1          # the same offers again (page number ignored): stop
            print("    same offers as before: last page for this search")
        elif cards and getattr(src, "STOP_WHEN_KNOWN", False) and \
                all(db.find(c.con, card["url"]) is not None for card in queue + [x for x in cards if x.get("url")]):
            out["page_no"] = search["max_pages"] - 1          # WTTJ matches: a page of offers already known = the
            print("    every offer of this page is already known: stop (older matches below)")   # rest is older
        if src.KIND == "email" or all_read:
            out["page_no"] = search["max_pages"] - 1          # everything read at once: next search
        return out

    def pick(st):
        q = list(st["queue"])
        cur = q.pop(0)
        return {"queue": q, "current": cur, "seen": st["seen"] + [cur["key"]]}

    def dedupe_node(st):
        cur = st["current"]
        skip, why = seen_before(c.con, cur["url"], cur["title"])
        if skip:
            return {"current": {**cur, "next": "skip"}, "stats": _bump(st, "already_known")}
        if why:
            print(f"  ~ {cur['title'][:60]}: {why}")
        return {"current": {**cur, "next": "read"}}

    def read(st):
        cur = dict(st["current"])
        if cur["source"] in st["blocked"]:         # verification page not solved: this source waits for next scan
            return {"current": {**cur, "next": "skip"}, "stats": _bump(st, "not_read_source_blocked")}
        c.offer = c.s.new_tab(cur["url"])
        time.sleep(c.pause(cur["platform"]))
        if not cleared(c.offer, cur["source"]):    # captcha instead of the offer: never judged, nothing saved
            c.s.close_tabs_except([c.results])
            return {"current": {**cur, "next": "skip"}, "blocked": st["blocked"] + [cur["source"]],
                    "stats": _bump(st, f"blocked_{cur['source']}")}
        offer = read_offer(c.offer, cur["platform"])
        if not offer:
            print(f"  - {cur['title'][:60]}: offer page unavailable / closed")
            app_id = store.save_offer(c.con, cur["url"], {"title": cur["title"], "listing_title": cur["title"],
                                                          "company": cur.get("company"), "text": ""}, cur["source"])
            if not store._sent(c.con, app_id):
                db.update(c.con, app_id, status="closed", last_scan=c.run_dir.name)   # not reopened next scan
            c.s.close_tabs_except([c.results])
            return {"current": {**cur, "next": "skip"}, "stats": _bump(st, "dead")}
        seen_extra = []
        if cur.get("resolve"):                     # tracking link (email): the real offer address is known now
            src = get_source(cur["source"])
            real = src.offer_url({"href": c.offer.url, "jk": cur["jk"]})
            if real != cur["url"]:
                key = f"{cur['platform']}:{getattr(src, 'key_of', lambda u: db.job_identity(u)[1])(real)}"
                skip, why = (True, "already met in this scan") if key in st["seen"] else \
                    seen_before(c.con, real, cur["title"])
                if skip:
                    print(f"  = {cur['title'][:60]}: {why}")
                    c.s.close_tabs_except([c.results])
                    return {"current": {**cur, "next": "skip"}, "seen": st["seen"] + [key],
                            "stats": _bump(st, "already_known")}
                cur["url"], seen_extra = real, [key]
        offer["listing_title"] = cur["title"]                    # what dedupe compares next time
        offer.setdefault("company", cur.get("company"))           # from the results card (before the judge)
        offer.setdefault("location", cur.get("location"))
        cur["offer"] = offer
        cur["app_id"] = store.save_offer(c.con, cur["url"], offer, cur["source"])
        db.update(c.con, cur["app_id"], last_scan=c.run_dir.name)       # "python jobs.py reset last-scan"
        return {"current": {**cur, "next": "prefilter"}, "seen": st["seen"] + seen_extra}

    def prefilter_node(st):
        cur = st["current"]
        ok, reason = prefilter(cur["offer"]["text"], CONFIG.get("prefilter", {}))
        if not ok:
            store.save_prefiltered(c.con, cur["app_id"], reason)
            print(f"  - {cur['offer']['title'][:60]}: prefiltered ({reason})")
            c.s.close_tabs_except([c.results])
            return {"current": {**cur, "next": "skip"}, "stats": _bump(st, "prefiltered")}
        return {"current": {**cur, "next": "judge"}}

    def judge_node(st):
        cur = st["current"]
        j = judge(cur["offer"]["text"])
        store.save_judgment(c.con, cur["app_id"], j)
        if not j.get("verdict"):
            print(f"  ! judge failed on #{cur['app_id']}: {j.get('error')}")
            c.s.close_tabs_except([c.results])
            return {"current": {**cur, "next": "skip"}, "stats": _bump(st, "judge_errors")}
        store.save_offer(c.con, cur["url"], {**cur["offer"], **{k: v for k, v in j.items() if v}},
                         cur["source"])                    # judge fields (company, salary...) into the row
        print(f"  * #{cur['app_id']} {j['verdict'].upper():5} {j['score']:3}  {j.get('title') or cur['title']}"
              f" | {j.get('company') or cur['company']}")
        found = st["found"] + [{"id": cur["app_id"], "verdict": j["verdict"], "score": j["score"], "source": cur["source"],
                                "title": j.get("title") or cur["title"], "company": j.get("company") or cur["company"],
                                "url": cur["url"], "reasons": j.get("reasons")}]
        _bump(st, f"judged_{j['verdict']}")
        _bump(st, "tokens_judge", j["usage"]["in"] + j["usage"]["out"])
        eligible = (auto.get("enabled") and j["verdict"] in auto.get("verdicts", ["high"])
                    and j["score"] >= min_score(auto, j["verdict"])
                    and st["stats"].get("auto_applied_attempts", 0) < auto.get("max_per_run", 3)
                    and cur["offer"]["apply_kind"] in ("easy", "external"))
        why = eligible and avoid.reason(cur["url"], cur["offer"].get("external_url") or "",
                                        company_name=j.get("company") or cur.get("company") or "")
        if why:                                    # [avoid] in config.toml: judged and saved, never applied
            print(f"    - {why}: not applying")
            if not store._sent(c.con, cur["app_id"]):
                db.update(c.con, cur["app_id"], status="avoided", agent_summary=why)
            _bump(st, "avoided")
            eligible = False
        if not eligible:
            c.s.close_tabs_except([c.results])
        return {"current": {**cur, "next": "apply" if eligible else "skip", "judgment": j},
                "found": found, "stats": st["stats"]}

    def apply_auto(st):
        cur = st["current"]
        if already_applied(c.con, cur["app_id"]) is not None:         # belt and braces: never twice
            c.s.close_tabs_except([c.results])
            return {"stats": _bump(st, "auto_skipped_already_applied")}
        if (other := applied_elsewhere(c.con, cur["app_id"])) is not None:   # same job, other link / board
            print(f"  = already applied to this job via {other['platform']} (#{other['id']}): next offer")
            db.update(c.con, cur["app_id"], status="applied", applied_at=other["applied_at"],
                      agent_summary=f"same job already applied via {other['platform']} #{other['id']}")
            c.s.close_tabs_except([c.results])
            return {"stats": _bump(st, "auto_skipped_already_applied")}
        _bump(st, "auto_applied_attempts")
        print(f"  > auto-apply #{cur['app_id']}")
        run_dir = c.run_dir / f"offer-{cur['app_id']}"
        try:
            res = apply(c.offer, cur["url"], "auto", human.ask if auto.get("supervised") else None, run_dir,
                        verdict=cur["judgment"]["verdict"], title=cur["judgment"].get("title") or cur.get("title", ""),
                        company=cur["judgment"].get("company") or cur.get("company", ""))
        except Exception as e:                         # one broken application never stops the whole scan
            import traceback
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            print(f"    ! application crashed ({type(e).__name__}): marked stuck, the scan goes on")
            res = {"status": "stuck", "summary": f"crash: {type(e).__name__}: {str(e)[:200]}", "usage": {"in": 0, "out": 0}}
            telegram.send(f"💥 #{cur['app_id']} {cur.get('title', '')[:60]}: crash ({type(e).__name__}). "
                          f"Details: {run_dir.name}/error.txt", "errors")
        status = store.save_application(c.con, cur["app_id"], res, "auto", c.run_dir / f"offer-{cur['app_id']}")
        print(f"    -> {status}")
        if status in ("needs_human", "stuck"):
            j = cur.get("judgment") or {}
            telegram.send(f"⚠️ #{cur['app_id']} {status}: {j.get('title') or cur.get('title', '')} | "
                          f"{j.get('company') or cur.get('company', '')}\n{(res.get('summary') or '')[:500]}\n{cur['url']}",
                          "needs_human")
        found = [dict(f, apply_status=status) if f["id"] == cur["app_id"] else f for f in st["found"]]
        c.s.close_tabs_except([c.results])
        return {"found": found, "stats": _bump(st, f"auto_{status}")}

    def next_page(st):
        if st["page_no"] + 1 < st["searches"][st["search_i"]]["max_pages"]:
            time.sleep(c.pause(get_source(st["searches"][st["search_i"]]["source"]).PLATFORM))
            return {"page_no": st["page_no"] + 1}
        return {"page_no": 0, "search_i": st["search_i"] + 1}

    def notify(st):
        mail.mark_seen(c.con, st["mails"])                     # emails done: never parsed again
        if st["blocked"]:
            st["stats"]["blocked_sources"] = ", ".join(st["blocked"])
        report(st["found"], st["stats"], c.agent)
        return {}

    def route_more(st):
        if st["queue"]:
            return "pick"
        last_page = st["page_no"] + 1 >= st["searches"][st["search_i"]]["max_pages"]
        last_search = st["search_i"] + 1 >= len(st["searches"])
        return "notify" if (last_page and last_search) else "next_page"

    g = StateGraph(ScanState)
    for name, fn in [("results", results), ("pick", pick), ("read", read), ("prefilter", prefilter_node), ("dedupe", dedupe_node),
                     ("judge", judge_node), ("apply_auto", apply_auto), ("next_page", next_page),
                     ("notify", notify), ("more", lambda st: {})]:
        g.add_node(name, fn)
    g.set_entry_point("results")
    g.add_conditional_edges("results", route_more, {"pick": "pick", "next_page": "next_page", "notify": "notify"})
    g.add_edge("next_page", "results")
    g.add_edge("pick", "dedupe")
    route = lambda st: st["current"]["next"]
    g.add_conditional_edges("read", route, {"prefilter": "prefilter", "skip": "more"})
    g.add_conditional_edges("dedupe", route, {"read": "read", "skip": "more"})
    g.add_conditional_edges("prefilter", route, {"judge": "judge", "skip": "more"})
    g.add_conditional_edges("judge", route, {"apply": "apply_auto", "skip": "more"})
    g.add_edge("apply_auto", "more")
    g.add_conditional_edges("more", route_more, {"pick": "pick", "next_page": "next_page", "notify": "notify"})
    g.add_edge("notify", END)
    return g.compile()


def min_score(auto: dict, verdict: str) -> int:
    """[auto_apply] min_score: one number for every level, or per level {high = 70, maybe = 40}."""
    ms = auto.get("min_score", 0)
    return int(ms.get(verdict, 0)) if isinstance(ms, dict) else int(ms)


def searches_from_config(search_cfg: dict, cfg: dict | None = None, only: list | None = None) -> list:
    """Every browser source x every query, the email sources once each, then the pasted results URLs.
    Old config (single 'query', single 'source') still works."""
    cfg = cfg if cfg is not None else CONFIG
    sources = list(search_cfg.get("sources") or [search_cfg.get("source", "indeed")])
    if only is not None:                           # one agent: its own sources only
        sources = [s for s in sources if s in only] if search_cfg.get("sources") else list(only)
    queries = list(search_cfg.get("queries") or [])
    if search_cfg.get("query") and search_cfg["query"] not in queries:
        queries.insert(0, search_cfg["query"])
    pages = lambda name: int(cfg.get(name, {}).get("max_pages", search_cfg.get("max_pages", 3)))
    out = []
    for name in sources:
        if get_source(name).KIND == "email":
            out.append({"source": name, "max_pages": 1})
        elif getattr(get_source(name), "QUERYLESS", False):          # WTTJ matches: same list whatever the query
            out.append({"source": name, "query": "", "max_pages": pages(name)})
        else:
            out += [{"source": name, "query": q, "max_pages": pages(name)} for q in queries if q.strip()]
    for u in search_cfg.get("extra_search_urls", []):
        name = "linkedin" if "linkedin." in u else "indeed" if "indeed." in u else \
            "wttj" if "welcometothejungle." in u else "hellowork" if "hellowork." in u else \
            "freework" if "free-work." in u else \
            next((s for s in sources if get_source(s).KIND == "browser"), "indeed")
        if name in sources:
            out.append({"source": name, "url": u, "max_pages": pages(name)})
    if not out and only is None:
        raise SystemExit("config.toml [search]: set sources, queries = [...] or extra_search_urls = [...]")
    return out


def run_scan(session, agent: str | None = None) -> dict:
    """agent: name in [agents] -> only its sources, in its Chrome (session). None: every source (old setup)."""
    base = ROOT / "runs" / ("scan-" + datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{agent}" if agent else ""))
    run_dir, n = base, 1
    while True:                                    # two scans in the same second (fast scans, parallel agents)
        try:
            run_dir.mkdir(parents=True)
            break
        except FileExistsError:
            n += 1
            run_dir = base.with_name(f"{base.name}-{n}")
    con = db.connect()
    if agent:
        human.AGENT = agent                        # Telegram questions are labelled "[linkedin]": answers addressed
    c = Ctx(session, con, run_dir)
    if agent:
        from core.agents import agents
        a = agents()[agent]
        search_cfg = {**CONFIG["search"], **({"extra_search_urls": a["extra_search_urls"]} if "extra_search_urls" in a else {})}
        searches = searches_from_config(search_cfg, only=a.get("sources", []))
    else:
        searches = searches_from_config(CONFIG["search"])
    c.agent = agent
    if not searches:
        print(f"agent {agent}: nothing to search (its sources are off in [search] sources)")
        return {"stats": {}, "found": []}
    state = build(c).invoke({"searches": searches, "search_i": 0, "page_no": 0, "queue": [], "seen": [],
                             "found": [], "stats": {}, "blocked": [], "mails": []}, {"recursion_limit": 5000})
    try:
        c.results.close()
    except Exception:
        pass
    return state
