"""
Manage the applications database from the terminal.

  python jobs.py list [status]          all applications (or one status)
  python jobs.py show <id>              every field of one application + its relances
  python jobs.py applied <id> [date]    you clicked "Déposer": mark as applied (date default: today)
  python jobs.py relance <id> [channel] [note...]   log a follow-up (email, phone, linkedin...)
  python jobs.py status <id> <status>   interview | rejected | offer | no_answer | ...
  python jobs.py note <id> <text...>    free note
  python jobs.py reset <id|status>      show it again in hunt.py (e.g. reset skipped)
  python jobs.py due [days]             applications to follow up (default: 7 days without news)
  python jobs.py export [file.csv]      export the overview (opens in Excel)
"""

import csv
import json
import sys

import db

STATUSES = {"new", "filtered", "skipped", "ready_for_review", "applied", "external_apply", "stuck",
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
    cols = ["id", "status", "company", "title", "applied_at", "relance_count", "last_relance_at", "contact_email"]

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

    elif cmd == "reset":                      # make offers visible again to hunt.py
        if args[0].isdigit():
            db.update(con, int(args[0]), status="new")
            print("reset to new")
        else:
            n = con.execute("UPDATE applications SET status='new' WHERE status=?", (args[0],)).rowcount
            con.commit()
            print(f"{n} '{args[0]}' offers reset to new")

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
