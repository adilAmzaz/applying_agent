"""
"Contact me about future job opportunities" (Brevo on LinkedIn, Lever) / talent pool / keep my CV:
always YES (radio Yes/Oui or ticked), while job alerts / newsletters stay OFF.
Plus the clicks / typing that used to time out (LYNRED "Se connecter", Soors message box).
"""
import re
from common import LINKEDIN, ROOT, Human
from playwright.sync_api import sync_playwright
from core import policy
from core.autofill import value_for
from core.browser import Session
from core.tools import BrowserTools, _js_set

PROFILE = {"identity": {"first_name": "Adil"}}
Q = "I am allowing Brevo to contact me about future job opportunities for up to 2 years. Privacy Policy *"

# 1) the rules alone
assert value_for(f"Yes [question: {Q}]", "radio", ["Yes", "No"], PROFILE) == "Yes"
assert value_for("x", "radio", ["Oui", "Non"], PROFILE) is None
assert value_for("J'accepte d'être recontacté pour d'autres offres", "radio", ["Non", "Oui"], PROFILE) == "Oui"
assert value_for(Q, "radio", ["Yes", "No"], {**PROFILE, "consent_future_opportunities": False}) is None
assert value_for(Q, "radio", ["Yes", "No"], {**PROFILE, "form_answers": {Q.rstrip(" *"): "No"}}) == "Yes"
for name in ["J'accepte que mon CV soit conservé dans le vivier de candidats", "Keep my resume on file for future roles",
             "Yes [question: " + Q + "]", "Je souhaite être contacté pour de futures opportunités"]:
    assert policy.TALENT.search(name), name
    assert policy.check("check", {"name": name, "role": "input", "type": "checkbox"}, "https://x.com", {})[0] == policy.ALLOW
for name in ["Recevoir des alertes emploi", "Je souhaite recevoir la newsletter", "Offres similaires par e-mail"]:
    assert not policy.TALENT.search(name) and policy.OPT_IN.search(name), name

# RQTH / handicap: answered "no" ONLY because the profile says so (sensitive_answers), never "prefer not to answer"
RQTH = ["Oui, je suis reconnu(e) travailleur handicapé", "Non, je ne suis pas reconnu(e) comme travailleur handicapé",
        "Je ne souhaite pas répondre à cette question"]
SA = {"sensitive_answers": {"handicap_rqth": "no"}}
assert value_for("x [question: Êtes-vous reconnu(e) travailleur handicapé (RQTH) ?*]", "radio", RQTH, SA) == RQTH[1]
assert value_for("Do you have a disability?", "radio", ["Yes", "No", "I don't wish to answer"], SA) == "No"
assert value_for("Situation de handicap", "select", ["Oui", "Non"], PROFILE) is None          # not stated: ask

# iCIMS login: passkey enrolment page -> never "Continuer" (Windows Hello), only "later"; "Adresse mail" is the email
U = "https://login.icims.eu/u/mfa-webauthn-platform-enrollment?state=x"
assert policy.check("click", {"name": "Continuer", "role": "button"}, U, {})[0] == policy.FORBIDDEN
assert policy.check("click", {"name": "Me rappeler plus tard", "role": "button"}, U, {})[0] == policy.ALLOW
assert policy.check("click", {"name": "Créer une clé d'accès", "role": "button"}, "https://x.com/a", {})[0] == policy.FORBIDDEN
I = {"identity": {"email": "adil@example.com", "address": "Rue de la Paix"}}
assert value_for("Adresse mail", "text", None, I) == "adil@example.com" and value_for("Adresse", "text", None, I) == "Rue de la Paix"

# legal pages: never opened (the agent clicked "CGU" / "Privacy policy" links, a new tab, and got lost)
assert policy.check("click", {"name": "CGU", "role": "a"}, "https://x.com/apply", {})[0] == policy.FORBIDDEN
assert policy.check("click", {"name": "Privacy policy", "role": "a"}, "https://x.com/apply", {})[0] == policy.FORBIDDEN
assert policy.check("click", {"name": "J'accepte les CGU", "role": "input", "type": "checkbox"}, "https://x.com/a", {"approve_legal": True})[0] == policy.ALLOW
import re as _re
from core.tools import SUCCESS_RE
for t in ["Vous avez postulé à cette offre le 10/10/2026", "Félicitations ! Votre candidature a bien été envoyée",
          "Félicitations ! Votre candidature au poste de Senior Ai - Gen ai Engineer H/F va être transmise à Talan."]:
    assert _re.search(SUCCESS_RE, t, _re.I), t

# 2) LinkedIn-like modal: required Yes/No (no answer yet), a talent-pool checkbox, an alert pre-ticked
PAGE = """<div role="dialog" class="artdeco-modal">
<h3>Additional Questions</h3>
<fieldset><legend>""" + Q + """</legend>
  <input type="radio" name="b" id="y" value="Yes" required><label for="y">Yes</label>
  <input type="radio" name="b" id="n" value="No" required><label for="n">No</label></fieldset>
<input type="checkbox" id="pool"><label for="pool">J'accepte que Brevo conserve mon CV pour de futures opportunités</label>
<input type="checkbox" id="jobalert" checked><label for="jobalert">Recevoir des alertes emploi</label>
<button onclick="window.next = (window.next||0) + 1">Suivant</button></div>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(PAGE)
    (ROOT / "runs" / "tests" / "consent").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "consent", Human([]), {"board_host": "x", "approve_legal": True})
    did = t.autopilot(PROFILE)
    print(did)
    state = page.evaluate("() => [y.checked, n.checked, pool.checked, jobalert.checked, window.next]")
    assert state == [True, False, True, False, 1], (state, did)

    # 3) a button under a transparent overlay (LYNRED "Se connecter" timed out): the click still goes through
    page.set_content("""<form onsubmit="return false"><input id="m" placeholder="Email">
      <button id="go" onclick="window.go = 1">Se connecter</button></form>
      <div style="position:fixed;inset:0;background:transparent;z-index:9"></div>""")
    t2 = BrowserTools(page, ROOT / "runs" / "tests" / "consent", Human([]), {"board_host": "x", "accounts": True})
    ref = re.search(r"\[(e\d+)\] button \"Se connecter", t2.read_page()).group(1)
    out = t2.click(ref)
    assert out.startswith("clicked") and page.evaluate("() => window.go") == 1, out[:200]

    # 4) a message box the normal typing cannot reach (Soors): set by script, the site sees the input event
    page.set_content("""<textarea id="msg" style="visibility:hidden" oninput="window.got = this.value"></textarea>""")
    assert _js_set(page.locator("#msg"), "Bonjour") == "Bonjour" and page.evaluate("() => window.got") == "Bonjour"
    s.close()
print("\nALL CONSENT CHECKS PASSED")
