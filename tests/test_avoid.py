"""
[avoid] in config.toml: sites / companies where the agent never applies (the offer is still judged and saved).

  1) matching rules (sub-domains, www, ports, company names without accents)
  2) scan: the offer's company or its company-site link is on the list -> judged, saved "avoided", no application
  3) during the application: a click leads to an avoided site -> stopped at once, nothing typed there
"""
import json
from common import CALLS, CONFIG, HELLOWORK, ROOT, fresh
from playwright.sync_api import sync_playwright
from core import avoid
from core.browser import Session
import graphs.scan as scan_mod

# 1) matching -------------------------------------------------------------------------------------
CONFIG["avoid"] = {"sites": ["www.3ds.com", "127.0.0.1:8771"], "companies": ["Dassault Systèmes"]}
assert avoid.site("https://www.3ds.com/careers/x") and avoid.site("https://careers.3ds.com/a") and avoid.site("3ds.com")
assert not avoid.site("https://my3ds.com/") and not avoid.site("https://www.3ds.co/")
assert avoid.site("http://127.0.0.1:8771/form.html") and not avoid.site("http://127.0.0.1:8774/x")   # port given
assert avoid.company("DASSAULT SYSTEMES SE") and not avoid.company("Dassault Aviation")
assert avoid.reason("https://www.indeed.com/x", company_name="Dassault Systèmes").startswith("avoided company")
assert avoid.reason("https://www.indeed.com/x", company_name="ACME") is None


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = scan_mod.run_scan(s)
        s.close()
    return st


def rows(con):
    return {r["listing_title"].split(" H/F")[0]: r for r in con.execute("SELECT * FROM applications")}


SEARCH = [HELLOWORK + "/search.html"]
APPLY = {"enabled": True, "approve_legal": True, "min_score": 80}

# 2) before applying: ACME by company name, Delta by its "Postuler sur le site du recruteur" link (:8771) -------
con = fresh("avoid2", search={"sources": ["hellowork"], "extra_search_urls": SEARCH}, auto_apply=APPLY,
            avoid={"sites": ["127.0.0.1:8771"], "companies": ["Acme"]})
CALLS.update(judge=0, apply=0)
st = scan()
r = rows(con)
print({k: (v["status"], v["agent_summary"]) for k, v in r.items()}, st["stats"])
assert r["AI Engineer"]["verdict"] == "high" and r["AI Engineer"]["status"] == "avoided"          # judged, not applied
assert "avoided company Acme" in r["AI Engineer"]["agent_summary"]
assert r["GenAI Engineer"]["status"] == "avoided" and "127.0.0.1:8771" in r["GenAI Engineer"]["agent_summary"]
assert st["stats"].get("avoided") == 2 and not st["stats"].get("auto_applied_attempts"), st["stats"]

# 3) during the application: the scan does not know the link (pre-check off), the click leads there -> stop ----
class _NoPrecheck:
    @staticmethod
    def reason(*a, **k):
        return None


scan_mod.avoid = _NoPrecheck
con = fresh("avoid3", search={"sources": ["hellowork"], "extra_search_urls": SEARCH}, auto_apply=APPLY,
            avoid={"sites": ["127.0.0.1:8771"], "companies": []})
st = scan()
r = rows(con)
print({k: (v["status"], v["agent_summary"]) for k, v in r.items()}, st["stats"])
assert r["GenAI Engineer"]["status"] == "avoided", r["GenAI Engineer"]["agent_summary"]
log = [json.loads(l) for l in (ROOT / r["GenAI Engineer"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
i = next(n for n, l in enumerate(log) if l.get("kind") == "avoided")
assert not any(l.get("kind") in ("type", "upload_cv", "select") for l in log[i:]), log          # nothing done there
assert r["AI Engineer"]["status"] == "ready_for_review"                                         # the others: normal

# 4) the same job already applied through another link (Indeed -> Free-Work): never applied twice -----------
from core import db
from nodes.dedupe import applied_elsewhere
con = fresh("avoid4")
a = db.upsert_offer(con, "https://www.free-work.com/fr/tech-it/job-mission/ia/ingenieur-ia-agentique",
                    {"title": "Ingénieur IA / Développeur Agentique (IA4IT)", "company": "Hexagone Digitale"}, "")
db.update(con, a, status="applied", platform="freework")
b = db.upsert_offer(con, "https://fr.indeed.com/viewjob?jk=abc123",
                    {"title": "Ingénieur IA / Développeur Agentique (IA4IT) H/F", "company": "HEXAGONE DIGITALE SAS"}, "")
c2 = db.upsert_offer(con, "https://fr.indeed.com/viewjob?jk=abc124",
                     {"title": "Data Engineer H/F", "company": "Hexagone Digitale"}, "")
assert applied_elsewhere(con, b)["id"] == a
assert applied_elsewhere(con, c2) is None                    # same company, another job: applied normally
print("\nALL AVOID CHECKS PASSED")
