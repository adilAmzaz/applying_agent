"""
Offline Welcome to the Jungle tests on a fake WTTJ (:8773): list drawn after load, apply form in a modal,
company-site offer, closed offer, alert email with a direct link and a tracking (redirect) link.

  ACME     AI Engineer     WTTJ form (modal)   -> high 92
  Delta    GenAI Engineer  company site        -> high 88
  Gamma    LLM Engineer    "Cette offre n'est plus disponible" -> closed
  Epsilon  ML Engineer     only in the email   -> low
"""
import json
from common import CALLS, ROOT, WTTJ, fresh
from playwright.sync_api import sync_playwright
from core import policy
from core.browser import Session
from graphs.scan import run_scan
from nodes.sources import mail, wttj, wttj_email

# 1) identity, guardrails, email parsing ---------------------------------------------------------
from core.db import job_identity
u = "https://www.welcometothejungle.com/en/companies/mistral-ai/jobs/ai-engineer_paris?q=x&o=12"
assert job_identity(u) == ("wttj", "mistral-ai/ai-engineer_paris")
assert wttj.canonical(u) == "https://www.welcometothejungle.com/fr/companies/mistral-ai/jobs/ai-engineer_paris"
assert job_identity(wttj.canonical(u)) == job_identity(u)                     # /en/ and /fr/: same offer
# WTTJ has no public search any more: your MATCHES (logged in), read once per scan, clear message when logged out
assert wttj.results_url({"query": "AI engineer"}, 0) == "https://www.welcometothejungle.com/fr/jobs-matches?published_since=last_7d"
assert wttj.results_url({"query": "AI engineer"}, 2).endswith("?published_since=last_7d&page=3")
assert wttj.blocked("https://www.welcometothejungle.com/fr/jobs?query=AI", [], "Jobs | Welcome to the Jungle") == wttj.LOGIN_NEEDED
assert wttj.blocked("https://www.welcometothejungle.com/fr/authenticate/signin", [], "") == wttj.LOGIN_NEEDED
assert wttj.blocked("https://www.welcometothejungle.com/fr/jobs-matches", [{"jk": 1}], "") is None
from graphs.scan import searches_from_config
_s = searches_from_config({"sources": ["wttj", "indeed"], "queries": ["a", "b", "c"]}, {})
assert sum(x["source"] == "wttj" for x in _s) == 1 and sum(x["source"] == "indeed" for x in _s) == 3, _s
ctx = {"board_host": "www.welcometothejungle.com", "external": True, "filled_inputs": 1}
offer = "https://www.welcometothejungle.com/fr/companies/acme/jobs/ai-engineer_paris"
chk = lambda name, typ=None, dialog=False: policy.check("click", {"name": name, "type": typ, "in_dialog": dialog}, offer, ctx)[0]
assert chk("Postuler") == policy.ALLOW
assert chk("Sauvegarder") == policy.FORBIDDEN and chk("Suivre") == policy.FORBIDDEN
assert chk("Se connecter", dialog=True) == policy.FORBIDDEN                    # login: the human
assert chk("Envoyer ma candidature", dialog=True) == policy.FORBIDDEN          # no submit configured
assert policy.check("click", {"name": "Continuer"}, offer + "/apply", ctx)[0] == policy.ALLOW   # WTTJ form URL

MAIL = f"""Welcome to the Jungle
3 nouvelles offres pour votre alerte "AI engineer"

AI Engineer
ACME
Paris
Voir l'offre {WTTJ}/track.html?u={WTTJ}/fr/companies/acme/jobs/ai-engineer_paris&click=1

ML Engineer
Epsilon
Paris
{WTTJ}/fr/companies/epsilon/jobs/ml-engineer_paris?utm_source=alert

Voir toutes les offres {WTTJ}/fr/jobs?query=AI+engineer
Gérer mes alertes {WTTJ}/fr/me/alerts
Se désabonner {WTTJ}/unsubscribe?t=1
"""
cards = wttj_email.parse(MAIL)
print(cards)
assert [(c["title"], c["company"], c["resolve"]) for c in cards] == [("AI Engineer", "ACME", True), ("ML Engineer", "Epsilon", False)]
assert cards[1]["jk"] == "epsilon/ml-engineer_paris"


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = run_scan(s)
        s.close()
    return st


def rows(con):
    return {r["listing_title"]: r for r in con.execute("SELECT * FROM applications")}


SEARCH = [WTTJ + "/search.html"]

# 2) browser scan -------------------------------------------------------------------------------
con = fresh("wttj1", search={"sources": ["wttj"], "extra_search_urls": SEARCH})
CALLS.update(judge=0)
st = scan()
r = rows(con)
print({k: (v["status"], v["verdict"], v["apply_kind"], v["platform"]) for k, v in r.items()}, st["stats"])
assert CALLS["judge"] == 2, CALLS
assert (r["AI Engineer"]["verdict"], r["AI Engineer"]["apply_kind"]) == ("high", "easy")
assert r["GenAI Engineer"]["apply_kind"] == "external"
assert r["LLM Engineer"]["status"] == "closed"
assert "?q=" not in r["AI Engineer"]["url"]                                    # clean link stored
# WTTJ cannot sort by date: every page read first, then newest first (Delta today, Gamma 5/10, ACME 1/10)
order = [x[0] for x in con.execute("SELECT listing_title FROM applications ORDER BY id")]
assert order == ["GenAI Engineer", "LLM Engineer", "AI Engineer"], order

# 3) alert email: tracking link resolved to an offer already judged -> skipped; the new one judged
mail.fetch_messages = lambda senders: [{"message_id": "<w1@wttj>", "sender": "alerts@welcometothejungle.com",
                                        "subject": "", "text": MAIL}]
CALLS.update(judge=0)
from core.config import CONFIG
CONFIG["search"].update(sources=["wttj_email"], extra_search_urls=[])
st = scan()
print(st["stats"])
assert CALLS["judge"] == 1 and st["stats"]["already_known"] == 1, (CALLS, st["stats"])   # ACME known, Epsilon new
assert rows(con)["ML Engineer"]["verdict"] == "low"

# 4) auto-apply on the WTTJ form: filled, newsletter unticked, stops before sending -------------
con = fresh("wttj4", search={"sources": ["wttj"], "extra_search_urls": SEARCH},
            auto_apply={"enabled": True, "approve_legal": True})
scan()
r = rows(con)
assert r["AI Engineer"]["status"] == "ready_for_review", r["AI Engineer"]["agent_summary"]
assert r["GenAI Engineer"]["status"] == "ready_for_review", r["GenAI Engineer"]["agent_summary"]
log = [json.loads(l) for l in (ROOT / r["AI Engineer"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
assert any(l.get("kind") == "set_checked" and "alertes" in l["el"] and l["after"] is False for l in log)
assert any(l.get("kind") == "upload_cv" for l in log)
assert any(l.get("kind") == "policy" and l["el"] == "Envoyer ma candidature" and l["verdict"] == "forbidden" for l in log)
print("\nALL WTTJ CHECKS PASSED")
