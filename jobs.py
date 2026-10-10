"""
Manage the applications database from the terminal.

  python jobs.py list [status]          all applications (or one status)
  python jobs.py show <id>              every field of one application + its relances
  python jobs.py applied <id> [date]    you clicked "Déposer": mark as applied (date default: today)
  python jobs.py relance <id> [channel] [note...]   log a follow-up (email, phone, linkedin...)
  python jobs.py status <id> <status>   interview | rejected | offer | no_answer | ...
  python jobs.py note <id> <text...>    free note
  python jobs.py reset <id|status>      forget it: read + judged again at the next scan (e.g. reset skipped)
  python jobs.py reset last-scan        everything the last scan processed
  python jobs.py reset scan <name>      one scan (names: python jobs.py scans)
  python jobs.py reset all              everything (a backup is always made first, in backups/)
  python jobs.py scans                  list scans and what they found
  python jobs.py example <id> high|maybe|low [why...]   add the offer to judge/examples.md
  python jobs.py due [days]             applications to follow up (default: 7 days without news)
  python jobs.py export [file.csv]      export the overview (opens in Excel)
"""

import csv
import json
import sys

from core import db
from nodes import reset
from nodes.examples import add_example

STATUSES = {"new", "prefiltered", "judged", "skipped", "ready_for_review", "needs_human", "applied", "stuck",
            "interview", "rejected", "offer", "no_answer"}


def table(rows, cols):
    if not rows:
        print("(nothing)")
        return
    widths = {c: min(32, max(len(c), *(len(str(r[c] or "")) for r in rows))) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r[c] or "")[:widths[c]].ljust(widths[c]) for c in cols))


def main(argv):
    if not argv:
        print(__doc__)
        return
    con = db.connect()
    cmd, args = argv[0], argv[1:]
    cols = ["id", "status", "verdict", "score", "company", "title", "applied_at", "relance_count", "contact_email"]

    if cmd == "list":
        q, p = "SELECT * FROM applications_overview", ()
        if args:
            q, p = q + " WHERE status=?", (args[0],)
        table(con.execute(q + " ORDER BY id DESC", p).fetchall(), cols)

    elif cmd == "show":
        a = con.execute("SELECT * FROM applications WHERE id=?", (int(args[0]),)).fetchone()
        if not a:
            sys.exit("unknown id")
        for k in a.keys():
            v = a[k]
            if k == "description" and v:
                v = v[:600] + ("..." if len(v) > 600 else "")
            if k == "skills" and v:
                v = ", ".join(json.loads(v))
            print(f"{k:>20}: {v}")
        print("\nRELANCES:")
        table(con.execute("SELECT * FROM relances WHERE application_id=? ORDER BY done_at", (a["id"],)).fetchall(),
              ["id", "done_at", "channel", "note"])

    elif cmd == "applied":
        db.mark_applied(con, int(args[0]), args[1] if len(args) > 1 else None)
        print("marked as applied")

    elif cmd == "relance":
        rid = db.add_relance(con, int(args[0]), args[1] if len(args) > 1 else "", " ".join(args[2:]))
        print(f"relance #{rid} logged")

    elif cmd == "status":
        if args[1] not in STATUSES:
            sys.exit(f"status must be one of {sorted(STATUSES)}")
        db.update(con, int(args[0]), status=args[1])
        print("status updated")

    elif cmd == "reset":
        yes = "--yes" in args
        target = [a for a in args if a != "--yes"]
        try:
            rows, what = reset.select(con, target)
        except ValueError as e:
            sys.exit(str(e))
        if not rows:
            sys.exit(f"nothing to reset ({what})")
        counts = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"Reset {what}: {len(rows)} offers -> {counts}")
        print("They will be read and judged again at the next scan.")
        applied = [r for r in rows if r["status"] in db.APPLIED_STATUSES]
        if not yes and input("Continue? [y/N] > ").strip().lower() not in ("y", "yes", "o", "oui"):
            sys.exit("cancelled")
        if applied and not yes:
            print(f"\n!! {len(applied)} of them were APPLIED: they could be applied to AGAIN.")
            if input('Type "applied" to reset them too, Enter to keep them as applied > ').strip() != "applied":
                rows = [r for r in rows if r["status"] not in db.APPLIED_STATUSES]
        print("backup ->", reset.backup(con))
        print(f"{reset.reset(con, rows)} offers reset to new")

    elif cmd == "scans":
        for name, n, counts in reset.scans(con):
            print(f"{name}  {n:4} offers  {counts}")

    elif cmd == "example":
        row = con.execute("SELECT * FROM applications WHERE id=?", (int(args[0]),)).fetchone()
        if not row or args[1] not in ("high", "maybe", "low"):
            sys.exit("usage: python jobs.py example <id> high|maybe|low [why]")
        print("added to", add_example(row, args[1], " ".join(args[2:])))

    elif cmd == "note":
        db.update(con, int(args[0]), notes=" ".join(args[1:]))
        print("note saved")

    elif cmd == "due":
        days = int(args[0]) if args else 7
        print(f"Applied {days}+ days ago, no news, no relance in the last {days} days:\n")
        table(db.relances_due(con, days), cols + ["contact_phone"])

    elif cmd == "export":
        path = args[0] if args else "applications.csv"
        rows = con.execute("SELECT * FROM applications_overview ORDER BY id").fetchall()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:      # utf-8-sig: accents OK in Excel
            w = csv.writer(f, delimiter=";")
            w.writerow(rows[0].keys() if rows else [])
            w.writerows([tuple(r) for r in rows])
        print(f"{len(rows)} rows -> {path}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
