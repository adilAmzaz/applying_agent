"""
Offline Free-Work tests on a fake Free-Work (:8775): results drawn after load (the "latest offers" ticker at the top
is ignored), CDI + freelance offers, application form drawn IN the offer page (Free-Work account).
  ACME   AI Engineer H/F   CDI        -> high
  Delta  GenAI Engineer    Freelance  -> high
  Gamma  LLM Engineer H/F  CDI        -> maybe
"""
import json
from common import CALLS, CONFIG, FREEWORK, ROOT, fresh
from core.db import job_identity
from graphs.scan import run_scan
from playwright.sync_api import sync_playwright
from core.browser import Session
from nodes.sources import freework, freework_email, get_source

# 1) identity / urls ----------------------------------------------------------------------------
u = "https://www.free-work.com/fr/tech-it/job-mission/ingenieur-de-production/ingenieur-ia-mlops-production-h-f?utm=x"
assert job_identity(u) == ("freework", "ingenieur-ia-mlops-production-h-f"), job_identity(u)
assert freework.canonical(u) == "https://www.free-work.com/fr/tech-it/job-mission/ingenieur-de-production/ingenieur-ia-mlops-production-h-f"
assert freework.results_url({"query": "ingénieur IA"}, 0) == "https://www.free-work.com/fr/tech-it/jobs?query=ing%C3%A9nieur%20IA&sort=date"
assert freework.results_url({"query": "x"}, 2).endswith("&sort=date&page=3")              # newest first
CONFIG["freework"] = {"sort": "relevance"}
assert "sort=" not in freework.results_url({"query": "x"}, 0)
CONFIG["freework"] = {"contracts": ["permanent", "contractor"]}
assert "contracts=permanent&contracts=contractor" in freework.results_url({"query": "x"}, 0)
CONFIG["freework"] = {}
assert get_source("freework_email").SENDERS == ["free-work"] and freework_email.PLATFORM == "freework"


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = run_scan(s)
        s.close()
    return st


def rows(con):
    return {r["listing_title"].split(" H/F")[0]: r for r in con.execute("SELECT * FROM applications")}


SEARCH = [FREEWORK + "/search.html"]

# 2) browser scan: 3 results, the ticker offer ignored -------------------------------------------
con = fresh("fw1", search={"sources": ["freework"], "extra_search_urls": SEARCH})
CALLS.update(judge=0)
st = scan()
r = rows(con)
print({k: (v["status"], v["verdict"], v["company"], v["location"]) for k, v in r.items()}, st["stats"])
assert set(r) == {"AI Engineer", "GenAI Engineer", "LLM Engineer"}, set(r)            # not "SAP CONSULTANT"
assert r["AI Engineer"]["verdict"] == "high" and r["GenAI Engineer"]["verdict"] == "high"
assert r["LLM Engineer"]["status"] == "closed"                                          # "n'est plus disponible"

# 3) auto-apply, submit on: Free-Work's own form in the page, CV attached, sent ----------------------
con = fresh("fw3", search={"sources": ["freework"], "extra_search_urls": SEARCH},
            auto_apply={"enabled": True, "approve_legal": True, "submit": True})
scan()
r = rows(con)
assert r["AI Engineer"]["status"] == "applied", r["AI Engineer"]["agent_summary"]
log = [json.loads(l) for l in (ROOT / r["AI Engineer"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
assert any(l.get("kind") == "upload_cv" for l in log)
# one-click "Je postule": sent at once, the site shows the COMPANY page + a toast "candidature envoyée avec succès"
# (+ "Candidature spontanée déjà envoyée"): counted as sent, saved, next offer -- no human called
assert r["GenAI Engineer"]["status"] == "applied", (r["GenAI Engineer"]["status"], r["GenAI Engineer"]["agent_summary"])
log = [json.loads(l) for l in (ROOT / r["GenAI Engineer"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
assert not any(l.get("kind") == "wait_for_human" for l in log), log
print("\nALL FREEWORK CHECKS PASSED")
