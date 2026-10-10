"""
Offline scan tests (unattended: input() would crash the test if called).

Fake results page: job (ACME, easy apply, high 92), job2 (BetaCorp, "Power BI" -> prefiltered, no LLM),
job3 (Gamma, maybe 60), job4 (Delta, company site, high 88),
job5 (same title as job, other link: another ACME entity -> a DIFFERENT offer, judged too).
"""
import json
from pathlib import Path
from common import CALLS, CONFIG, fresh, ROOT
from playwright.sync_api import sync_playwright
from core.browser import Session
from graphs.scan import run_scan

RESULTS = ROOT / "tests" / "fake_site" / "results.html"


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = run_scan(s)
        s.close()
    return st


def rows(con):
    """keyed by page: job, job2 ... job5"""
    return {Path(r["url"].split("?")[0]).stem: r for r in con.execute("SELECT * FROM applications")}


# 1) auto-apply OFF: judge only ------------------------------------------------------------
con = fresh("scan1")
CALLS.update(judge=0, apply=0)
st = scan()
r = rows(con)
print({k: (v["status"], v["verdict"], v["score"], v["apply_kind"]) for k, v in r.items()})
assert CALLS["judge"] == 4 and CALLS["apply"] == 0, CALLS                     # job2 never reached the LLM
assert r["job2"]["status"] == "prefiltered" and "power bi" in r["job2"]["notes"]
assert (r["job"]["verdict"], r["job"]["score"], r["job"]["apply_kind"]) == ("high", 92, "easy")
assert (r["job4"]["verdict"], r["job4"]["apply_kind"]) == ("high", "external")
assert r["job3"]["verdict"] == "maybe" and r["job3"]["status"] == "judged"
assert r["job5"]["status"] == "judged"                         # same title, other link = another offer
assert json.loads(r["job"]["judge_reasons"]) == ["ACME reason"]
assert r["job"]["listing_title"] == "AI Engineer H/F"
from common import REPORTS
reports = sorted(REPORTS.glob("scan-*.md"))
assert reports and "ACME" in reports[-1].read_text(encoding="utf-8")

# 2) second scan: same link + same title -> nothing judged again (tokens) ---------------------
CALLS.update(judge=0)
st = scan()
assert CALLS["judge"] == 0 and st["stats"]["already_known"] == 4, (CALLS, st["stats"])   # job2 re-prefiltered (free)

# 3) same link, title edited on the site -> judged again (only that one) -----------------------
original = RESULTS.read_text(encoding="utf-8")
try:
    edited = original.replace('href="job3.html?jk=C3">LLM Engineer<', 'href="job3.html?jk=C3">Senior LLM Engineer<')
    assert edited != original
    RESULTS.write_text(edited, encoding="utf-8")
    CONFIG["search"]["extra_search_urls"] = [CONFIG["search"]["extra_search_urls"][0] + "?v=2"]   # no browser cache
    CALLS.update(judge=0)
    st = scan()
    assert CALLS["judge"] == 1, CALLS
    assert rows(con)["job3"]["listing_title"] == "Senior LLM Engineer"
finally:
    RESULTS.write_text(original, encoding="utf-8")
    CONFIG["search"]["extra_search_urls"] = [CONFIG["search"]["extra_search_urls"][0].replace("?v=2", "?v=3")]

# 4) dedupe node disabled -> everything re-read and re-judged ---------------------------------
CONFIG["dedupe"]["enabled"] = False
CALLS.update(judge=0)
scan()
assert CALLS["judge"] == 4, CALLS
CONFIG["dedupe"]["enabled"] = True

# 5) auto-apply ON, no submit, legal NOT approved -> needs_human (privacy checkbox) ----------
con = fresh("scan5", auto_apply={"enabled": True})
scan()
r = rows(con)
assert r["job"]["status"] == "needs_human" and r["job4"]["status"] == "needs_human", \
    {k: v["status"] for k, v in r.items()}
assert r["job3"]["status"] == "judged"                                        # maybe: never auto-applied

# 6) auto-apply ON, legal approved, no submit -> filled, stops before sending ----------------
con = fresh("scan6", auto_apply={"enabled": True, "approve_legal": True})
scan()
r = rows(con)
assert r["job"]["status"] == "ready_for_review", r["job"]["agent_summary"]
assert r["job4"]["status"] == "ready_for_review", r["job4"]["agent_summary"]
log = (ROOT / r["job4"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8")
assert '"kind": "new_tab"' in log and "upload_cv" in log                      # followed the company site
assert "account creation is for the human" in log                              # "Créer un compte" blocked
assert "Activer" in (ROOT / r["job"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8")

# 7) auto-apply ON + submit ON -> applied by itself; a later scan never re-applies -----------
con = fresh("scan7", auto_apply={"enabled": True, "approve_legal": True, "submit": True})
scan()
r = rows(con)
assert r["job"]["status"] == "applied" and r["job"]["applied_at"] and r["job"]["auto"] == 1
assert r["job4"]["status"] == "applied", r["job4"]["agent_summary"]
CALLS.update(apply=0, judge=0)
CONFIG["dedupe"]["enabled"] = False                         # even with dedupe off: the apply guard holds
scan()
assert CALLS["apply"] == 0, CALLS
assert rows(con)["job"]["status"] == "applied"
CONFIG["dedupe"]["enabled"] = True

# 8) several queries (Indeed gives different results for "AI engineer" / "ingénieur IA") ----------
from graphs.scan import searches_from_config
assert searches_from_config({"sources": ["indeed"], "queries": ["AI engineer", "ingénieur IA"], "max_pages": 3,
                             "extra_search_urls": ["u"]}, {}) == \
    [{"source": "indeed", "query": "AI engineer", "max_pages": 3}, {"source": "indeed", "query": "ingénieur IA", "max_pages": 3},
     {"source": "indeed", "url": "u", "max_pages": 3}]
assert searches_from_config({"query": "AI engineer", "source": "indeed"}, {}) == \
    [{"source": "indeed", "query": "AI engineer", "max_pages": 3}]                              # old config still works
# two searches returning the SAME offers: each one opened and judged once only
con = fresh("scan8")
url = CONFIG["search"]["extra_search_urls"][0]
CONFIG["search"]["extra_search_urls"] = [url + "?q=ai-engineer", url + "?q=ingenieur-ia"]
CALLS.update(judge=0)
st = scan()
assert CALLS["judge"] == 4, CALLS
assert st["stats"]["already_seen_this_run"] == 5, st["stats"]                 # 2nd search: all 5 already met
assert con.execute("SELECT count(*) FROM applications").fetchone()[0] == 5
CONFIG["search"]["extra_search_urls"] = [url]

# 9) levels: high AND maybe applied ("maybe" = the recruiter sees the CV for other roles) -----------
import scan as scan_cli
names, flags = scan_cli.apply_options(["linkedin", "--apply", "high,maybe", "--supervised", "--max", "7"])
assert names == ["linkedin"] and flags == ["--apply", "high,maybe", "--supervised", "--max", "7"]
assert CONFIG["auto_apply"]["verdicts"] == ["high", "maybe"] and CONFIG["auto_apply"]["submit"] is True
assert CONFIG["auto_apply"]["approve_legal"] is True and CONFIG["auto_apply"]["max_per_run"] == 7
from graphs.scan import min_score
assert min_score({"min_score": {"high": 70, "maybe": 40}}, "maybe") == 40 and min_score({"min_score": 85}, "maybe") == 85
con = fresh("scan9", auto_apply={"enabled": True, "verdicts": ["high", "maybe"], "min_score": {"high": 80, "maybe": 40},
                                 "approve_legal": True, "submit": True, "supervised": False})
CALLS.update(apply=0, maybe_prompt=0)
scan()
r = rows(con)
print({k: (v["verdict"], v["status"]) for k, v in r.items()})
assert r["job3"]["verdict"] == "maybe" and r["job3"]["status"] not in ("judged",), r["job3"]["status"]   # maybe: applied too
assert r["job"]["status"] == "applied" and CALLS["maybe_prompt"] >= 1
print("\nALL SCAN CHECKS PASSED")
