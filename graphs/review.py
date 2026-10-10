"""
REVIEW loop (you are here): go through what the scan judged, decide, apply.

  pending (high first, then maybe) -> show card -> a = apply (interactive) | s = skip | l = later | o = open | q
                                         \-> optional: label it as a judge example (h / m / l)
"""

import json
import webbrowser
from datetime import datetime

from core import db
from core.config import ROOT
from nodes import store
from nodes.apply import apply
from nodes.dedupe import already_applied
from nodes.examples import add_example


def show(row):
    reasons = json.loads(row["judge_reasons"] or "[]")
    flags = json.loads(row["red_flags"] or "[]")
    skills = row["skills"]
    try:
        skills = ", ".join(json.loads(skills)) if skills else "-"
    except (ValueError, TypeError):
        pass
    print("\n" + "-" * 72)
    print(f"#{row['id']}  {(row['verdict'] or '?').upper()} {row['score']}   {row['title']}  |  {row['company']}")
    print(f"     {row['location']} | {row['contract_type']} | {row['remote']} | salary: {row['salary']} | apply: {row['apply_kind']}")
    print(f"     skills: {skills}")
    print(f"     {row['summary']}")
    print(f"     + {' / '.join(reasons)}")
    if flags:
        print(f"     ! {' / '.join(flags)}")
    print(f"     contact: {row['contact_name'] or '-'} | {row['contact_email'] or '-'} | {row['contact_phone'] or '-'}")
    print(f"     {row['url']}")


def _session(session, row):
    """A SessionPool gives the Chrome of the agent logged in to this offer's site."""
    return session.for_platform(row["platform"]) if hasattr(session, "for_platform") else session


def apply_now(session, con, row, ask):
    done = already_applied(con, row["id"])
    if done is not None and ask(f"Already applied (#{done['id']} {done['company']}, {done['status']} "
                                f"{done['applied_at'] or ''}). Apply AGAIN? [y/N] > ").strip().lower() not in ("y", "yes", "o", "oui"):
        print("   not applied again")
        return "already_applied"
    run_dir = ROOT / "runs" / f"review-{datetime.now():%Y%m%d-%H%M%S}-offer-{row['id']}"
    session = _session(session, row)
    page = session.new_tab(row["url"])
    res = apply(page, row["url"], "interactive", ask, run_dir, title=row["title"] or "", company=row["company"] or "")
    status = store.save_application(con, row["id"], res, "interactive", run_dir)
    print(f"\n   -> {status}: {res.get('summary', '')[:300]}")
    if status == "ready_for_review":
        ans = ask('Did you click the final send button? [y = yes, Enter = later] > ').strip().lower()
        if ans in ("y", "yes", "o", "oui"):
            db.mark_applied(con, row["id"])
            status = "applied"
            print("   saved as APPLIED")
    keep = [p for p in session.ctx.pages if status == "ready_for_review" and p in res.get("opened", []) + [page]]
    if status != "ready_for_review":
        session.close_tabs_except(keep)
    return status


def maybe_label(row, decision, ask):
    """If you disagree with the judge, offer to save the offer as an example."""
    disagree = (decision == "apply" and row["verdict"] != "high") or (decision == "skip" and row["verdict"] == "high")
    if not disagree:
        return
    ans = ask(f"You disagree with the judge ({row['verdict']}). Save as example? [h/m/l + why, Enter = no] > ").strip()
    if ans[:1].lower() in ("h", "m", "l"):
        label = {"h": "high", "m": "maybe", "l": "low"}[ans[0].lower()]
        print("   example added ->", add_example(row, label, ans[1:].strip()))


def run_auto(session, ask=input, verdicts=("high", "maybe"), limit: int | None = None):
    """python review.py --apply high,maybe: applies to every pending offer of these levels, one after the
    other, until SENT ([auto_apply] submit/approve_legal/supervised set by review.py). You watch: captchas,
    logins and unknown questions are asked here."""
    con = db.connect()
    rows = db.pending_review(con, verdicts)[:limit]
    print(f"{len(rows)} offers to apply to ({', '.join(verdicts)})")
    stats = {}
    for row in rows:
        show(row)
        if already_applied(con, row["id"]) is not None:
            stats["already_applied"] = stats.get("already_applied", 0) + 1
            continue
        run_dir = ROOT / "runs" / f"review-{datetime.now():%Y%m%d-%H%M%S}-offer-{row['id']}"
        s = _session(session, row)
        page = s.new_tab(row["url"])
        res = apply(page, row["url"], "auto", ask, run_dir, verdict=row["verdict"], title=row["title"] or "",
                    company=row["company"] or "")
        db.update(con, row["id"], decision="apply")
        status = store.save_application(con, row["id"], res, "auto", run_dir)
        print(f"   -> {status}: {res.get('summary', '')[:200]}")
        stats[status] = stats.get(status, 0) + 1
        if status != "ready_for_review":
            s.close_tabs_except([p for p in s.ctx.pages if p not in res.get("opened", []) + [page]])
    print("\nDONE:", stats)
    return stats


def run_review(session, ask=input, verdicts=("high", "maybe")):
    con = db.connect()
    rows = db.pending_review(con, verdicts)
    print(f"{len(rows)} offers to review ({', '.join(verdicts)})")
    stats = {}
    for row in rows:
        show(row)
        ans = ask("[a]pply / [s]kip / [l]ater / [o]pen in browser / [q]uit > ").strip().lower()[:1]
        if ans == "o":
            webbrowser.open(row["url"]) if not session.cdp else _session(session, row).new_tab(row["url"])
            ans = ask("[a]pply / [s]kip / [l]ater / [q]uit > ").strip().lower()[:1]
        if ans == "q":
            break
        if ans == "a":
            db.update(con, row["id"], decision="apply")
            st = apply_now(session, con, row, ask)
            maybe_label(row, "apply", ask)
        elif ans == "s":
            db.update(con, row["id"], decision="skip", status="skipped")
            st = "skipped"
            maybe_label(row, "skip", ask)
        else:
            st = "later"
        stats[st] = stats.get(st, 0) + 1
    print("\nREVIEW DONE:", stats)
    return stats
