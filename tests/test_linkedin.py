"""
Offline LinkedIn (browser) tests on a fake LinkedIn (:8772): results list loaded while scrolling,
Easy Apply in a modal (role=dialog) on the offer page, "Postuler" = company site, closed offer,
offer already applied on the site, login wall.

  ACME     AI Engineer       easy apply (modal)  -> high 92
  Delta    GenAI Engineer    company site        -> high 88
  Gamma    LLM Engineer      "Candidature envoyée" on the card -> skipped, no page opened
  Zeta     Data Scientist IA "N'accepte plus de candidatures" -> dead
  Epsilon  ML Engineer       card rendered only after scrolling -> low
"""
import json
from pathlib import Path
from common import CALLS, CONFIG, LINKEDIN, ROOT, fresh
from playwright.sync_api import sync_playwright
from core import policy
from core.browser import Session
from graphs.scan import run_scan

# 1) guardrails on a LinkedIn offer page ---------------------------------------------------------
ctx = {"board_host": "www.linkedin.com", "external": True, "allow_submit": False, "filled_inputs": 2}
url = "https://www.linkedin.com/jobs/view/4012345678/"
el = lambda name, typ=None, dialog=False: {"name": name, "type": typ, "in_dialog": dialog}
A, F = policy.ALLOW, policy.FORBIDDEN
cases = [
    ("click", el("Candidature simplifiée à AI Engineer chez ACME"), A),   # Easy Apply start
    ("click", el("Postuler"), A),                                         # company site (NOT a send, search box filled)
    ("click", el("Postuler à AI Engineer chez ACME sur le site web de l’entreprise"), A),
    ("click", el("Enregistrer"), F), ("click", el("Suivre"), F), ("click", el("Messagerie"), F),
    ("click", el("Suivant", dialog=True), A), ("click", el("Vérifier", dialog=True), A),
    ("click", el("Envoyer la candidature", dialog=True), F),               # final send: not allowed here
    ("click", el("Enregistrer", dialog=True), F),                           # save the draft = account change
    ("click", el("Suivre ACME pour rester informé", "checkbox", True), F),
    ("check", el("Suivre ACME pour rester informé", "checkbox", True), F),
    ("uncheck", el("Suivre ACME pour rester informé", "checkbox", True), A),
    ("click", el("S’identifier"), F),
]
for action, e, want in cases:
    got = policy.check(action, e, url, ctx)[0]
    assert got == want, (action, e["name"], got, want)
assert policy.check("click", el("Envoyer la candidature", dialog=True), url, {**ctx, "allow_submit": True})[0] == A


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = run_scan(s)
        s.close()
    return st


def rows(con):
    names = {"AI Engineer": "ACME", "GenAI Engineer": "Delta", "ML Engineer": "Epsilon", "Data Scientist IA": "Zeta"}
    return {names[r["listing_title"]]: r for r in con.execute("SELECT * FROM applications")}


SEARCH = [LINKEDIN + "/search.html"]

# 2) judge only --------------------------------------------------------------------------------
con = fresh("li1", search={"sources": ["linkedin"], "extra_search_urls": SEARCH})
CALLS.update(judge=0, apply=0)
st = scan()
r = rows(con)
print({k: (v["status"], v["verdict"], v["apply_kind"], v["listing_title"]) for k, v in r.items()}, st["stats"])
assert CALLS["judge"] == 3 and CALLS["apply"] == 0, CALLS
assert set(r) == {"ACME", "Delta", "Epsilon", "Zeta"}               # Gamma: applied on the site (not stored)
assert r["Zeta"]["status"] == "closed" and r["Zeta"]["verdict"] is None
assert st["stats"]["applied_on_the_site"] == 1 and st["stats"]["dead"] == 1, st["stats"]
assert (r["ACME"]["verdict"], r["ACME"]["apply_kind"], r["ACME"]["listing_title"]) == ("high", "easy", "AI Engineer")
assert r["Delta"]["apply_kind"] == "external" and r["Epsilon"]["verdict"] == "low"
assert r["ACME"]["source"] == "linkedin"
CALLS.update(judge=0)
st = scan()                                                         # second scan: nothing judged again
assert CALLS["judge"] == 0 and st["stats"]["already_known"] == 4 and "dead" not in st["stats"], (CALLS, st["stats"])

# 3) auto-apply, legal approved, no submit: Easy Apply modal filled, "Suivre ACME" unticked, stops before send
con = fresh("li3", search={"sources": ["linkedin"], "extra_search_urls": SEARCH},
            auto_apply={"enabled": True, "approve_legal": True})
scan()
r = rows(con)
assert r["ACME"]["status"] == "ready_for_review", r["ACME"]["agent_summary"]
assert r["Delta"]["status"] == "ready_for_review", r["Delta"]["agent_summary"]   # followed to the company site
log = [json.loads(l) for l in (ROOT / r["ACME"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
blocked = [l["el"] for l in log if l.get("kind") == "policy" and l["verdict"] == "forbidden"]
assert "Enregistrer" in blocked and "Envoyer la candidature" in blocked, blocked
assert any(l.get("kind") == "set_checked" and "Suivre" in l["el"] and l["after"] is False for l in log), log
assert '"kind": "new_tab"' in (ROOT / r["Delta"]["run_dir"] / "actions.jsonl").read_text(encoding="utf-8")

# 4) auto-apply with submit: sent from the modal, never twice ------------------------------------
con = fresh("li4", search={"sources": ["linkedin"], "extra_search_urls": SEARCH},
            auto_apply={"enabled": True, "approve_legal": True, "submit": True})
scan()
assert rows(con)["ACME"]["status"] == "applied"
CALLS.update(apply=0)
scan()
assert CALLS["apply"] == 0

# 5) login wall: LinkedIn stops for this scan, the report says it -----------------------------
con = fresh("li5", search={"sources": ["linkedin"],
                           "extra_search_urls": [LINKEDIN + "/authwall/", LINKEDIN + "/search.html"]})
CALLS.update(judge=0)
st = scan()
assert st["stats"]["blocked_linkedin"] == 1 and CALLS["judge"] == 0, st["stats"]   # 2nd search not even loaded
from common import REPORTS
report = sorted(REPORTS.glob("scan-*.md"))[-1].read_text(encoding="utf-8")
assert "Stopped this time: linkedin" in report

# 6) LinkedIn 2026 logged-in layout: no stable class names, description cut with "... plus" (your screenshot)
from nodes.read import read_offer
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000006/")
    offer = read_offer(page, "linkedin")
    bad = page.evaluate("() => !!window.badClick")
    s.close()
print(offer["text"][:600])
assert "LA FIN DE LA DESCRIPTION COMPLETE" in offer["text"] and "concevoir des agents LLM" in offer["text"]   # "plus" clicked
assert "Premium" not in offer["text"] and "alerte emploi" not in offer["text"]                     # only the description
assert not bad, "clicked 'Afficher plus d'offres d'emploi'"
assert offer["title"] == "INGENIEUR AI H/F" and offer["apply_kind"] == "easy"
print("\nALL LINKEDIN CHECKS PASSED")
