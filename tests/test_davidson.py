"""
Davidson (company site, no dialog): the autopilot clicked a footer "SOUMETTRE UN PROJET" (contact page) instead of
the form's own "POSTULER", and the run was saved as applied. Now: only the form's buttons, required tick-box
questions (Mobilité *) left to the LLM, custom checkboxes ticked, and "sent" only when the site confirms.
"""
from common import CV, LINKEDIN, ROOT, Human
from playwright.sync_api import sync_playwright
from core.browser import Session
from core.tools import BrowserTools

PAGE = """<style>.cb input{opacity:0;position:absolute} .cb span{display:inline-block;width:12px;height:12px;border:1px solid}</style>
<header><a href="#contact" onclick="window.contact=1">SOUMETTRE UN PROJET</a></header>
<form onsubmit="event.preventDefault(); window.applied=(window.applied||0)+1;
   document.getElementById('ok').innerText='Votre candidature a bien été envoyée'">
 <label for="nom">Nom *</label><input id="nom" required>
 <label for="pre">Prénom *</label><input id="pre" required>
 <label for="em">Email *</label><input id="em" type="email" required>
 <label for="cv">CV *</label><input id="cv" type="file" required>
 <fieldset><legend>Mobilité *</legend>
   <label class="cb"><input type="checkbox" id="tls"><span></span> Toulouse</label>
   <label class="cb"><input type="checkbox" id="idf"><span></span> Île-de-France</label></fieldset>
 <label class="cb"><input type="checkbox" id="rgpd"><span></span> En cochant cette case, je reconnais avoir lu la politique de confidentialité</label>
 <button type="submit">POSTULER</button></form>
<div id="ok"></div>
<footer><button onclick="window.contact=1">Soumettre un projet</button></footer>"""
PROFILE = {"identity": {"first_name": "Adil", "last_name": "AMZAZ", "email": "adil@example.com"}}

with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(PAGE)
    (ROOT / "runs" / "tests" / "davidson").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "davidson", Human([]),
                     {"board_host": "x", "approve_legal": True, "allow_submit": True}, str(CV))
    did = t.autopilot(PROFILE)
    print("1:", did)
    v = page.evaluate("() => [nom.value, em.value, rgpd.checked, idf.checked, window.contact, window.applied]")
    assert v == ["AMZAZ", "adil@example.com", True, False, None, None], (v, did)   # stops at "Mobilité *"
    # with your mobility in the profile, the autopilot answers "Mobilité *" itself (Toulouse + Île-de-France)
    from core.autofill import value_for, mobility_boxes
    MOB = {"mobility": ["Paris", "Marseille", "Nice", "Lille", "Lyon", "Toulouse"]}
    assert mobility_boxes("Mobilité *", ["Toulouse", "Île-de-France", "Strasbourg"], MOB) == ["Toulouse", "Île-de-France"]
    assert mobility_boxes("Mobilité *", ["Toulouse", "Partout en France"], MOB) == ["Partout en France"]
    Q = "Quelles sont vos préférences de mobilités géographiques ?"
    assert value_for(Q, "select", ["FR - West France", "FR - Paris", "France entière"], MOB) == "France entière"
    assert value_for(Q, "select", ["FR - West France", "FR - South East"], MOB) == "FR - South East"
    assert value_for("Êtes-vous mobile ?", "radio", ["Oui", "Non"], MOB) == "Oui"
    assert value_for("Téléphone mobile", "text", None, {"identity": {"phone_national": "06"}, **MOB}) == "06"
    # the LLM ticks Île-de-France (an invisible input behind a styled box: the click used to time out)
    import re
    ref = re.search(r"\[(e\d+)\] input:checkbox \"Île-de-France", t.read_page()).group(1)
    out = t.set_checked(ref, True)
    assert page.evaluate("() => idf.checked"), out[:300]
    did = t.autopilot(PROFILE)
    print("2:", did)
    assert page.evaluate("() => [window.contact, window.applied]") == [None, 1], did
    assert t.success and t.submitted, (t.success, t.submitted)

    # MyChatBot: the last button is "Continue" and the site says "Thanks! The form was submitted successfully."
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000008/")
    page.set_content("""<form onsubmit="event.preventDefault()"><label for="n">Name</label><input id="n">
      <label for="e">Email</label><input id="e" type="email">
      <button type="button" onclick="setTimeout(() => document.body.insertAdjacentHTML('beforeend',
        '<div class=toast>Thanks! The form was submitted successfully.</div>'), 300)">Continue</button></form>""")
    t = BrowserTools(page, ROOT / "runs" / "tests" / "davidson", Human([]), {"board_host": "x"}, str(CV))
    import re as _re
    st = t.read_page()
    t.type_text(_re.search(r"\[(e\d+)\] input:text \"Name", st).group(1), "Adil AMZAZ")
    t.click(_re.search(r"\[(e\d+)\] button \"Continue", t.read_page()).group(1))
    assert t.success and t.submitted, (t.success, t.submitted)
    s.close()
print("\nALL DAVIDSON CHECKS PASSED")
