"""Reset commands: by status, last scan, one applied offer; backups; offers judged again afterwards."""
import builtins
from common import CALLS, Human, ROOT, fresh
from playwright.sync_api import sync_playwright
from core import db
from core.browser import Session
from graphs.scan import run_scan
import jobs


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = run_scan(s)
        s.close()
    return st


def status(con):
    return {r["url"].split("/")[-1].split(".")[0]: r["status"] for r in con.execute("SELECT * FROM applications")}


con = fresh("reset")
scan()
db.update(con, 1, status="applied", applied_at="2026-10-01")       # job  : applied
db.update(con, 4, status="skipped", decision="skip")               # job4 : you said no
print(status(con))
BACKUPS = db.DB_PATH.parent / "backups"
backups_before = len(list(BACKUPS.glob("*.db"))) if BACKUPS.exists() else 0

jobs.main(["scans"])
name = con.execute("SELECT last_scan FROM applications WHERE id=1").fetchone()[0]
assert name and name.startswith("scan-")

# 1) reset skipped -> only job4
builtins.input = Human(["y"])
jobs.main(["reset", "skipped"])
assert status(con)["job4"] == "new" and status(con)["job"] == "applied"

# 2) reset last-scan, keep applied (Enter at the second question)
builtins.input = Human(["y", ""])
jobs.main(["reset", "last-scan"])
st = status(con)
assert st["job"] == "applied" and all(v == "new" for k, v in st.items() if k != "job"), st
assert con.execute("SELECT verdict FROM applications WHERE id=3").fetchone()[0] is None

# 3) reset the applied one, confirmed twice
builtins.input = Human(["y", "applied"])
jobs.main(["reset", "1"])
row = con.execute("SELECT * FROM applications WHERE id=1").fetchone()
assert row["status"] == "new" and row["applied_at"] is None

# 4) cancel does nothing
db.update(con, 2, status="skipped")
builtins.input = Human([""])
try:
    jobs.main(["reset", "skipped"])
except SystemExit:
    pass
assert status(con)["job2"] == "skipped"

assert len(list(BACKUPS.glob("*.db"))) == backups_before + 3          # one backup per reset
builtins.input = lambda p="": (_ for _ in ()).throw(AssertionError("unexpected input"))

# 5) the next scan judges the reset offers again (job2 is still skipped: not judged)
CALLS.update(judge=0)
scan()
assert CALLS["judge"] == 4, CALLS
print("\nALL RESET CHECKS PASSED")
