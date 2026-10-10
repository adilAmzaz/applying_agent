"""
Offline email-source tests: real alert formats (fixtures/), then scans where the "mailbox" is a fixture
whose links point to the fake sites. No network, no password.
"""
from pathlib import Path
from common import BOARD, CALLS, CONFIG, LINKEDIN, ROOT, fresh
from playwright.sync_api import sync_playwright
from core.browser import Session
from graphs.scan import run_scan
from nodes.sources import indeed_email, linkedin_email, mail

FIX = ROOT / "tests" / "fixtures"

# 1) parsing the real formats --------------------------------------------------------------------
cards = indeed_email.parse((FIX / "indeed_alert.txt").read_text(encoding="utf-8"))
assert [c["jk"] for c in cards] == ["7d29825d944e4901", "1398ecc7190d8b5b", "dfc52bb78a8ead09", "a1f9c5bd094985bd"]
assert cards[1] == {**cards[1], "title": "Cofondateur CTO IA F/H", "company": "Gam'in Tech", "location": "Paris (75)",
                    "easy_apply": True}
assert cards[0]["company"] == "Dassault Systèmes" and not cards[0]["easy_apply"]
assert indeed_email.offer_url(cards[0]) == "https://fr.indeed.com/viewjob?jk=7d29825d944e4901"
cards = linkedin_email.parse((FIX / "linkedin_alert.txt").read_text(encoding="utf-8"))
assert [c["jk"] for c in cards] == ["2453474129", "2452384232", "2452357557"]
assert (cards[0]["title"], cards[0]["company"], cards[0]["easy_apply"]) == ("System Reliability Engineer (Python)", "Quarkslab", True)
assert (cards[2]["company"], cards[2]["location"]) == ("Selescope", "Paris, Île-de-France, France")   # "Company · Location"
assert linkedin_email.offer_url(cards[0]) == "https://www.linkedin.com/jobs/view/2453474129/"
html = '<p><a href="https://www.linkedin.com/comm/jobs/view/4011111111/?x=1">AI Engineer</a></p><p>ACME</p><p>Paris</p>'
c = linkedin_email.parse(mail.html_to_text(html))
assert c and c[0]["jk"] == "4011111111" and c[0]["title"] == "AI Engineer", c                    # HTML-only email
# 2026 format: the email header and "other alerts" headers are glued to the next offer
cards = linkedin_email.parse((FIX / "linkedin_alert_2026.txt").read_text(encoding="utf-8"))
assert [(c["jk"], c["title"], c["company"], c["location"]) for c in cards] == [
    ("4475955775", "Ingénieur GenAI", "L'olivier Assurance | Admiral Group Plc", "Paris"),
    ("4475996365", "AI Engineer (Always Open)", "Chipiron", "Paris"),
    ("4475709439", "Ingénieur IA – Large Language Models (LLM)", "Accenture France", "Paris"),
    ("4450300152", "AI Engineer", "Mirakl", "Paris")], cards
assert cards[0]["href"] == "https://www.linkedin.com/jobs/view/4475955775/"          # no tracking tokens

# alerts forwarded by hand as .eml attachments: each attached alert is read, other senders ignored
from email.message import EmailMessage
def _eml(sender, mid, body):
    m = EmailMessage(); m["From"], m["Subject"], m["Message-ID"] = sender, "alerte", mid; m.set_content(body); return m
fwd = EmailMessage(); fwd["From"], fwd["Subject"], fwd["Message-ID"] = "me@gmail.com", "Fwd: alertes", "<fwd@me>"
fwd.set_content("voir les pieces jointes")
fwd.add_attachment(_eml("Alertes LinkedIn Jobs <jobalerts-noreply@linkedin.com>", "<a1@li>",
                        (FIX / "linkedin_alert_2026.txt").read_text(encoding="utf-8")))
fwd.add_attachment(_eml("Alertes LinkedIn Jobs <jobalerts-noreply@linkedin.com>", "<a2@li>", "x"))
fwd.add_attachment(_eml("Indeed <alert@indeed.com>", "<i1@in>", "y"))
got = mail.messages_in(fwd.as_bytes(), linkedin_email.SENDERS)
assert [m["message_id"] for m in got] == ["<a1@li>", "<a2@li>"], got
assert len(linkedin_email.parse(got[0]["text"])) == 4
assert mail.messages_in(_eml("x@y.com", "<z>", "hello").as_bytes(), linkedin_email.SENDERS) == []
direct = mail.messages_in(_eml("jobalerts-noreply@linkedin.com", "<d>", "x").as_bytes(), linkedin_email.SENDERS)
assert [m["message_id"] for m in direct] == ["<d>"]

# 2) scan from the mailbox (fixture) -----------------------------------------------------------
INDEED_MAIL = f"""Indeed Job Alert

AI Engineer H/F
ACME - Paris (75)
Candidature simplifiée
il y a 1 jour
{BOARD}/job.html?jk=A1&from=ja

LLM Engineer
Gamma - Lyon (69)
il y a 2 jours
{BOARD}/job3.html?jk=C3&from=ja
"""
LINKEDIN_MAIL = f"""LinkedIn | Votre alerte Emploi AI engineer (France)
---------------------------------------------------------
AI Engineer
ACME
Paris
| Easy Apply

Voir l’offre d’emploi : {LINKEDIN}/jobs/view/3900000001/?trk=x
---------------------------------------------------------
"""
BOX = [{"message_id": "<i1@indeed>", "sender": "donotreply@jobalert.indeed.com", "subject": "", "text": INDEED_MAIL},
       {"message_id": "<l1@linkedin>", "sender": "jobalerts-noreply@linkedin.com", "subject": "", "text": LINKEDIN_MAIL}]
mail.fetch_messages = lambda senders: [m for m in BOX if any(s in m["sender"] for s in senders)]


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = run_scan(s)
        s.close()
    return st


con = fresh("mail1", search={"sources": ["indeed_email", "linkedin_email"], "extra_search_urls": []})
CALLS.update(judge=0)
st = scan()
r = {(row["source"], row["company"]): row for row in con.execute("SELECT * FROM applications")}
print({k: (v["status"], v["verdict"]) for k, v in r.items()}, st["stats"])
assert CALLS["judge"] == 3, CALLS                                   # ACME + Gamma (Indeed), ACME (LinkedIn)
assert r[("indeed_email", "ACME")]["listing_title"] == "AI Engineer H/F"
assert r[("linkedin_email", "ACME")]["apply_kind"] == "easy"
assert con.execute("SELECT count(*) FROM mail_seen").fetchone()[0] == 2

CALLS.update(judge=0)
st = scan()                                                         # same emails: never parsed again
assert CALLS["judge"] == 0, CALLS

# 3) browser + email in one scan: the email offers were already found by the browser search ------
con = fresh("mail3", search={"sources": ["indeed", "indeed_email"]})
CALLS.update(judge=0)
st = scan()
assert CALLS["judge"] == 4, CALLS                                   # the 4 judged offers of the results page
assert st["stats"]["already_seen_this_run"] == 2, st["stats"]       # A1 and C3 from the email: free skip

# 4) no password configured: the email source stops, the scan goes on --------------------------
import importlib
importlib.reload(mail)
CONFIG["email"] = {"address": "", "password_env": "JOBAGENT_TEST_NO_PASSWORD"}
con = fresh("mail4", search={"sources": ["indeed_email", "indeed"]})
CALLS.update(judge=0)
st = scan()
assert st["stats"]["blocked_indeed_email"] == 1 and CALLS["judge"] == 4, (st["stats"], CALLS)
print("\nALL EMAIL CHECKS PASSED")
