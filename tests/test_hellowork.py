"""
Offline HelloWork tests on a fake HelloWork (:8774): list drawn after load, application form drawn IN the
offer page (no dialog), "Postuler sur le site du recruteur", expired offer, alert email (direct + tracking link).

  ACME     AI Engineer H/F     HelloWork form (in the page)  -> high 92
  Delta    GenAI Engineer H/F  company site                  -> high 88
  Gamma    LLM Engineer H/F    expired                       -> closed
  Epsilon  ML Engineer H/F     only in the email             -> low
"""
import json
from common import CALLS, CONFIG, HELLOWORK, ROOT, fresh
from playwright.sync_api import sync_playwright
from core import policy
from core.browser import Session
from core.db import job_identity
from graphs.scan import run_scan
from nodes.sources import hellowork, hellowork_email, mail

# 1) identity, guardrails, email parsing ---------------------------------------------------------
u = "https://www.hellowork.com/fr-fr/emplois/61234567.html?utm_source=alert"
assert job_identity(u) == ("hellowork", "61234567") and hellowork.canonical(u).endswith("/emplois/61234567.html")
ctx = {"board_host": "www.hellowork.com", "external": True, "filled_inputs": 1}
offer = "https://www.hellowork.com/fr-fr/emplois/61234567.html"
chk = lambda name, **el: policy.check("click", {"name": name, **el}, offer, ctx)[0]
assert chk("Postuler") == policy.ALLOW and chk("Postuler sur le site du recruteur") == policy.ALLOW
assert chk("Sauvegarder") == policy.FORBIDDEN and chk("Créer une alerte") == policy.FORBIDDEN
assert chk("Continuer ma candidature") == policy.ALLOW                       # step 1 of the form (#postuler)
assert chk("Rechercher") == policy.FORBIDDEN                                   # search form: not an apply form
assert chk("Continuer", in_apply_form=True) == policy.ALLOW                    # form drawn in the page
assert chk("Envoyer ma candidature", in_apply_form=True) == policy.FORBIDDEN   # no submit configured
assert chk("Sauvegarder", in_apply_form=True) == policy.FORBIDDEN

MAIL = f"""HelloWork - Votre alerte emploi "AI engineer"
2 nouvelles offres

AI Engineer H/F
ACME
Paris - 75
{HELLOWORK}/track.html?u={HELLOWORK}/fr-fr/emplois/61000001.html&c=1

ML Engineer H/F
Epsilon
Paris - 75
Voir l'offre : {HELLOWORK}/fr-fr/emplois/61000004.html?utm_source=alert

Modifier mon alerte {HELLOWORK}/track.html?u=x&settings=1
Se désabonner {HELLOWORK}/track.html?u=y
"""
cards = hellowork_email.parse(MAIL)
print(cards)
assert [(c["title"], c["company"], c["resolve"]) for c in cards] == [("AI Engineer H/F", "ACME", True),
                                                                    ("ML Engineer H/F", "Epsilon", False)]


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = run_scan(s)
        s.close()
    return st


def rows(con):
    return {r["listing_title"].split(" H/F")[0]: r for r in con.execute("SELECT * FROM applications")}


SEARCH = [HELLOWORK + "/search.html"]

# 2) browser scan --------------------------------------------------------------------------------
con = fresh("hw1", search={"sources": ["hellowork"], "extra_search_urls": SEARCH})
CALLS.update(judge=0)
st = scan()
r = rows(con)
print({k: (v["status"], v["verdict"], v["apply_kind"]) for k, v in r.items()}, st["stats"])
assert CALLS["judge"] == 2, CALLS
assert (r["AI Engineer"]["verdict"], r["AI Engineer"]["apply_kind"]) == ("high", "easy")
assert r["GenAI Engineer"]["apply_kind"] == "external" and r["LLM Engineer"]["status"] == "closed"

# 3) alert email: tracking link resolved to a known offer -> skipped, the new one judged ----------
mail.fetch_messages = lambda senders: [{"message_id": "<h1@hw>", "sender": "alerte@hellowork.com", "subject": "", "text": MAIL}]
CONFIG["search"].update(sources=["hellowork_email"], extra_search_urls=[])
CALLS.update(judge=0)
st = scan()
assert CALLS["judge"] == 1 and st["stats"]["already_known"] == 1, (CALLS, st["stats"])
assert rows(con)["ML Engineer"]["verdict"] == "low"

# 4) auto-apply on the form drawn in the page: filled, alerts unticked, stops before sending --------
con = fresh("hw4", search={"sources": ["hellowork"], "extra_search_urls": SEARCH},
            auto_apply={"enabled": True, "approve_legal": True})
scan()
r = rows(con)
assert r["AI Engineer"]["status"] == "ready_for_review", r["AI Engineer"]["agent_summary"]
assert r["GenAI Engineer"]["status"] == "ready_for_review", r["GenAI Engineer"]["agent_summary"]
log = [json.loads(l) for l in (ROOT / r["AI Engineer"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
assert any(l.get("kind") == "set_checked" and "alertes" in l["el"] and l["after"] is False for l in log)
assert any(l.get("kind") == "policy" and l["el"] == "Envoyer ma candidature" and l["verdict"] == "forbidden" for l in log)

# 5) submit on: sent from the in-page form ---------------------------------------------------------
con = fresh("hw5", search={"sources": ["hellowork"], "extra_search_urls": SEARCH},
            auto_apply={"enabled": True, "approve_legal": True, "submit": True})
scan()
assert rows(con)["AI Engineer"]["status"] == "applied"
print("\nALL HELLOWORK CHECKS PASSED")
