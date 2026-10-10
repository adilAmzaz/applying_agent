"""
Fields that went wrong on real sites:
  Lefebvre Dalloz: address search "Rue de la Paix" -> picked "..., Lyon": now street + postal code + city,
                   and only a suggestion in the candidate's city
  Nextra (Factorial): "Préfixe téléphonique" -> "France (+33)" by the autopilot
  WTTJ "Votre profil a été amélioré": not a job alert (it became a fake offer)
"""
import json
import re
from common import CV, LINKEDIN, ROOT, Human
from playwright.sync_api import sync_playwright
from core import answers
from core.autofill import value_for
from core.browser import Session
from core.tools import BrowserTools
from nodes.sources.mail import NOT_ALERT

IDENT = {"phone": "+33 6 12 34 56 78", "phone_national": "06 12 34 56 78", "address": "Rue de la Paix",
         "postal_code": "75012", "city": "Paris", "country": "France"}
answers.PATH.write_text(json.dumps({"identity": IDENT}, ensure_ascii=False), encoding="utf-8")

# phone prefix
OPTS = ["Afghanistan (+93)", "Guadeloupe (+590)", "France (+33)", "Polynésie française (+689)"]
assert value_for("Préfixe téléphonique", "select", OPTS, {"identity": IDENT}) == "France (+33)"
assert value_for("Indicatif", "text", None, {"identity": IDENT}) == "+33"
assert value_for("Téléphone *", "text", None, {"identity": IDENT}) == "06 12 34 56 78"   # the number is unchanged

# job alerts only
for s in ["Votre profil a été amélioré !", "Votre alerte emploi AI engineer (France) est maintenant active",
          "Votre candidature a bien été envoyée"]:
    assert NOT_ALERT.search(s), s
for s in ["Ingénieur IA (F/H) à ENOVIA. 22 offres d'emploi supplémentaires ingenieur ia (France)",
          "« AI engineer » : 5 nouvelles offres", "Nouvelles offres pour vous : Machine Learning Engineer"]:
    assert not NOT_ALERT.search(s), s

# address search (Google-Places-like suggestions)
ADDR = """<label for="a">Adresse</label><input id="a" autocomplete="off"><div id="sug"></div>
<script>
 a.addEventListener('input', () => {
   const q = a.value.toLowerCase(), all = ["Rue de la Paix, Lyon, France", "Rue de la Paix, 75012 Paris, France",
                                           "Rue de la Paix, Bois-Colombes, France"];
   const hits = q.includes('paris') || q.includes('75012') ? all.filter(x => x.toLowerCase().includes('paris'))
              : q.includes('nowhere') ? [] : all.filter(x => !x.includes('Paris'));
   sug.innerHTML = hits.map(h => `<div class="pac-item">${h}</div>`).join('');
   document.querySelectorAll('.pac-item').forEach(o => o.onclick = () => { a.value = o.innerText; sug.innerHTML = ''; });
 });
</script>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(ADDR)
    (ROOT / "runs" / "tests" / "fields").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "fields", Human([]), {"board_host": "x"})
    ref = re.search(r"\[(e\d+)\] input:text \"Adresse", t.read_page()).group(1)
    out = t.search_select(ref, "Rue de la Paix")
    assert page.input_value("#a") == "Rue de la Paix, 75012 Paris, France", out[:300]
    # the site has nothing in Paris: refuse the other cities instead of picking Lyon
    page.set_content(ADDR.replace("q.includes('paris') || q.includes('75012')", "false"))
    t = BrowserTools(page, ROOT / "runs" / "tests" / "fields", Human([]), {"board_host": "x"})
    ref = re.search(r"\[(e\d+)\] input:text \"Adresse", t.read_page()).group(1)
    out = t.search_select(ref, "Rue de la Paix")
    assert out.startswith("No suggestion in Paris") and "Lyon" not in page.input_value("#a"), out[:300]

    # Workday (wd3, onepoint): "taper Entrée" search; "Aucun article." left in the list is NOT an option; a school
    # missing from the list -> "Autre", Enter, "Autre Ecole/Université" (the site's own instructions)
    WD = """<p>Pour trouver une école : écrire le nom, taper "Entrée" et sélectionner votre école. Si votre école
    n'apparait pas, écrire "Autre", taper "Entrée" puis sélectionner "Autre Ecole/Université"</p>
    <label id="l1">Établissement ou université*</label>
    <div data-uxi-widget-type="selectinput"><div id="pill"></div><input id="sb" aria-labelledby="l1"></div>
    <div id="list" role="listbox"><div role="option" data-automation-id="promptOption">Aucun article.</div></div>
    <script>
     var schools = SCHOOLS;
     sb.addEventListener('keydown', e => { if (e.key !== 'Enter') return;
       const q = sb.value.toLowerCase();
       var found = q.includes(' ') ? [] : schools.filter(s => s.toLowerCase().includes(q));   // full name: nothing
       var hits = q === 'autre' ? ['Autre Ecole/Université']
                  : found.length ? ['Résultats de la recherche (' + found.length + ')', ...found] : [];
       setTimeout(() => {
         list.innerHTML = (hits.length ? hits : ['Aucun article.'])
           .map(s => `<div role="option" data-automation-id="promptOption">${s}</div>`).join('');
         document.querySelectorAll('[data-automation-id=promptOption]').forEach(o => o.onclick = () => {
           if (o.innerText === 'Aucun article.') return;
           pill.innerHTML = `<div data-automation-id="selectedItem">${o.innerText}</div>`;
           sb.value = ''; list.innerHTML = ''; window.school = o.innerText; });
       }, 1200);                                              // the site answers late
     });
    </script>"""
    for schools, expect in ([["IAE Limoges", "Université de Lille", "Université de Limoges"], "Université de Limoges"],
                            [["Université de Lille"], "Autre Ecole/Université"]):
        page.set_content(WD.replace("SCHOOLS", json.dumps(schools)))
        t = BrowserTools(page, ROOT / "runs" / "tests" / "fields", Human([]), {"board_host": "x"})
        state = t.read_page()
        ref = re.search(r"\[(e\d+)\] search-field\(use search_select\) \"Établissement", state).group(1)
        out = t.type_text(ref, "Université de Limoges")            # typing on a search field -> searched + picked
        assert page.evaluate("() => window.school") == expect, out[:400]
        assert "Aucun article" not in out.split("\n")[1], out[:300]

    # Lever (Kpler): "Current location" erases what is typed unless a suggestion is picked; the CV is analysed after
    # upload, so it must never be uploaded again (the agent uploaded it 4 times and the fields kept changing)
    LEVER = """<form><label for="cv">Resume/CV</label><input type="file" id="cv" required>
    <label for="loc">Current location</label><input id="loc" name="location" class="location-input">
    <div class="dropdown-results"></div><input type="email" id="em"></form>
    <script>
     var picked = false;
     loc.addEventListener('input', () => { picked = false;
       document.querySelector('.dropdown-results').innerHTML = loc.value.length > 2 ?
         ['Paris, France', 'Paris, Texas, United States'].map(x => `<div class="dropdown-location">${x}</div>`).join('') : '';
       document.querySelectorAll('.dropdown-location').forEach(d => d.onclick = () => {
         loc.value = d.innerText; picked = true; document.querySelector('.dropdown-results').innerHTML = ''; });
     });
     loc.addEventListener('blur', () => setTimeout(() => { if (!picked) loc.value = ''; }, 150));
    </script>"""
    page.set_content(LEVER)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "fields", Human([]), {"board_host": "x"}, str(CV))
    did = t.autopilot({"identity": IDENT})
    assert page.input_value("#loc") == "Paris, France", did
    ref = re.search(r"\[(e\d+)\] input:file", t.read_page()).group(1)
    assert t.upload_cv(ref).startswith("ALREADY ATTACHED"), "uploaded twice"

    # SmartRecruiters "Intitulé*" (job title): suggestions, but free text is accepted -> no "Autre", text kept
    page.set_content("""<label for="jt">Intitulé*</label><input id="jt" role="combobox" aria-autocomplete="list">
      <div id="sug"></div><script>jt.addEventListener('input', () => { sug.innerHTML = jt.value.length > 2 ?
        '<div role="option">Machine Operator</div>' : ''; });</script>""")
    t = BrowserTools(page, ROOT / "runs" / "tests" / "fields", Human([]), {"board_host": "x"})
    ref = re.search(r"\[(e\d+)\] search-field\(use search_select\) \"Intitulé", t.read_page()).group(1)
    out = t.type_text(ref, "AI / Machine Learning Engineer")
    assert page.input_value("#jt") == "AI / Machine Learning Engineer" and "free text" in out, out[:300]

    # Greenhouse (Capco): an aria-hidden "requiredInput" beside each dropdown (the agent filled them and looped), and a
    # "Capco employee email address" field that is NOT your email
    page.set_content("""<form><label for="fn">Prénom</label><input id="fn" required>
      <label id="pl" for="pays">Pays*</label><input id="pays" role="combobox" aria-labelledby="pl" required>
      <input required tabindex="-1" aria-hidden="true" class="requiredInput" value="">
      <label for="ce">Capco employee email address</label><input id="ce">
      <label for="em">Adresse e-mail</label><input id="em" type="email" required></form>""")
    t = BrowserTools(page, ROOT / "runs" / "tests" / "fields", Human([]), {"board_host": "x"})
    state = t.read_page()
    assert state.count("Pays") == 1 and 'aria-hidden' not in state, state
    t.autopilot({"identity": {**IDENT, "first_name": "Adil", "email": "adil@example.com"}})
    assert page.input_value("#em") == "adil@example.com" and page.input_value("#ce") == "", "employee email filled"
    assert page.input_value(".requiredInput") == ""
    from core.autofill import value_for as vf
    assert vf("Reasonable Adjustments*", "select", ["Yes", "No"], {"sensitive_answers": {"handicap_rqth": "no"}}) == "No"
    s.close()
print("\nALL FIELD CHECKS PASSED")
