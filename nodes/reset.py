"""
RESET: make offers "never seen" again, so the next scan reads and judges them again.
Used by `python jobs.py reset ...`. Always backs the database up first (backups/).

Targets:
  <id>              one offer
  <status>          every offer with that status (skipped, prefiltered, judged, needs_human, stuck,
                    ready_for_review, applied, ...)
  last-scan         every offer processed by the most recent scan
  scan <name>       every offer processed by that scan (python jobs.py scans lists them)
  all               everything

What is cleared: status -> new, verdict, score, reasons, judged date, your decision, judge attempts.
Applied offers also lose their application date: they can be applied to AGAIN (asked twice).
Kept: the offer text and fields, contacts, relances (follow-ups), notes.
"""

import sqlite3
from datetime import datetime

from core import db

CLEAR = {"status": "new", "verdict": None, "score": None, "judge_reasons": None, "red_flags": None,
         "judged_at": None, "decision": None, "judge_attempts": 0}
CLEAR_APPLIED = {"applied_at": None, "auto": 0}


def select(con, target: list[str]):
    """-> (rows, description). target = command line words after 'reset'."""
    if not target:
        raise ValueError("reset what? <id> | <status> | last-scan | scan <name> | blocked-pages | all")
    t = target[0]
    if t.isdigit():
        return con.execute("SELECT * FROM applications WHERE id=?", (int(t),)).fetchall(), f"offer #{t}"
    if t in ("blocked-pages", "captcha"):           # judged on a verification page instead of the offer
        rows = [r for r in con.execute("SELECT * FROM applications WHERE status NOT IN (%s)"
                                       % ",".join("?" * len(db.APPLIED_STATUSES)), db.APPLIED_STATUSES)
                if _challenge_row(r)]
        return rows, "offers judged on a verification / captcha page"
    if t == "all":
        return con.execute("SELECT * FROM applications").fetchall(), "ALL offers"
    if t in ("last-scan", "scan"):
        name = target[1] if t == "scan" and len(target) > 1 else last_scan(con)
        if not name:
            raise ValueError("no scan recorded yet")
        return con.execute("SELECT * FROM applications WHERE last_scan=?", (name,)).fetchall(), f"scan {name}"
    return con.execute("SELECT * FROM applications WHERE status=?", (t,)).fetchall(), f"status '{t}'"


def _challenge_row(r) -> bool:
    from nodes.read import CHALLENGE_TEXT, CHALLENGE_TITLE
    text = (r["description"] or "")[:3000]
    return bool(CHALLENGE_TITLE.match((r["title"] or "").strip()) or CHALLENGE_TITLE.match((r["listing_title"] or "").strip())
                or (CHALLENGE_TEXT.search(text) and len(text) < 2500))


def last_scan(con) -> str | None:
    row = con.execute("SELECT last_scan FROM applications WHERE last_scan IS NOT NULL "
                      "ORDER BY last_scan DESC LIMIT 1").fetchone()
    return row[0] if row else None


def scans(con):
    """[(scan name, number of offers, {status: count})], newest first."""
    out = []
    for (name,) in con.execute("SELECT DISTINCT last_scan FROM applications WHERE last_scan IS NOT NULL "
                               "ORDER BY last_scan DESC").fetchall():
        counts = dict(con.execute("SELECT status, count(*) FROM applications WHERE last_scan=? GROUP BY status",
                                  (name,)).fetchall())
        out.append((name, sum(counts.values()), counts))
    return out


def backup(con) -> str:
    folder = db.DB_PATH.parent / "backups"          # next to jobs.db
    folder.mkdir(exist_ok=True)
    path = folder / f"jobs-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    dest = sqlite3.connect(path)
    con.backup(dest)                     # consistent copy, even while open
    dest.close()
    return str(path)


def reset(con, rows) -> int:
    for r in rows:
        fields = dict(CLEAR)
        if r["status"] in db.APPLIED_STATUSES:
            fields.update(CLEAR_APPLIED)
        db.update(con, r["id"], **fields)
    return len(rows)
