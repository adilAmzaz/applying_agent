"""
Offline review test: scan (judge only), then YOU review in the terminal (scripted answers).

  ACME  high 92 -> a (apply)  -> privacy box asked -> y -> review page -> "did you send?" y -> applied
  Delta high 88 -> s (skip)   -> you disagree with the judge -> "l not my sector" -> example saved as LOW
  ACME (other entity, same title, other link) high 92 -> l (later)
  Gamma maybe   -> l (later)  -> stays judged
"""
from common import CONFIG, Human, ROOT, fresh
from playwright.sync_api import sync_playwright
from core.browser import Session
from graphs.review import run_review
from graphs.scan import run_scan

con = fresh("review")
human = Human(["a", "y", "y",              # job  (ACME, 92): apply, approve privacy box, yes I sent it
               "l",                        # job5 (other ACME entity, same title, other link, 92): later
               "s", "l not my sector",     # Delta (88): skip + label as low example
               "l"])                       # Gamma (maybe): later
with sync_playwright() as p:
    s = Session(p)
    run_scan(s)
    stats = run_review(s, ask=human)
    s.close()

r = {row["company"]: row for row in con.execute("SELECT * FROM applications ORDER BY id DESC")}   # job (id 1) wins for ACME
assert r["ACME"]["status"] == "applied" and r["ACME"]["decision"] == "apply" and r["ACME"]["auto"] == 0
assert r["Delta"]["status"] == "skipped" and r["Delta"]["decision"] == "skip"
assert r["Gamma"]["status"] == "judged"
assert any("legal notice" in q for q, a in human.asked), human.asked
examples = (ROOT / CONFIG["judge"]["examples_file"]).read_text(encoding="utf-8")
assert "-> LOW" in examples and "not my sector" in examples and "Delta" in examples
assert [q[:8] for q, a in human.asked].count("[a]pply ") == 4                     # high first, then maybe
# never twice: applying again to the applied offer is refused (answer: Enter = no)
from graphs.review import apply_now
with sync_playwright() as p:
    s = Session(p)
    again = Human([""])
    assert apply_now(s, con, r["ACME"], again) == "already_applied"
    s.close()
assert con.execute("SELECT count(*) FROM applications WHERE status='applied'").fetchone()[0] == 1
print(stats)

# review.py --apply high,maybe: every pending high + maybe offer applied, one after the other, until sent
from graphs.review import run_auto
import review as review_cli
con = fresh("review_auto")
with sync_playwright() as p:
    s = Session(p)
    run_scan(s)
    review_cli.full_apply(["high", "maybe"])
    st = run_auto(s, ask=Human([]), verdicts=("high", "maybe"))
    s.close()
r = {row["listing_title"] + row["url"][-2:]: row["status"] for row in con.execute("SELECT * FROM applications")}
print(st, r)
assert st.get("applied", 0) >= 3, st                                          # ACME x2 + Delta (high), Gamma (maybe)
assert con.execute("SELECT count(*) FROM applications WHERE status='judged'").fetchone()[0] == 0
print("\nALL REVIEW CHECKS PASSED")
