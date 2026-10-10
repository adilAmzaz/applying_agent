"""
SmartRecruiters "oneclick-ui" (Sopra Steria): the form is made of WEB COMPONENTS, the fields live in shadow roots.
The agent saw "Informations personnelles" but no field at all and gave up. Now the scan goes inside shadow roots:
fields with their labels, required flags, the CV drop zone, and the autopilot fills them.
"""
import re
from common import CV, LINKEDIN, ROOT, Human
from playwright.sync_api import sync_playwright
from core.browser import Session
from core.tools import BrowserTools

PAGE = """<h2>Informations personnelles</h2>
<form id="f">
  <spl-input label="Prénom" required id="fn"></spl-input>
  <spl-input label="Nom" required id="ln"></spl-input>
  <spl-input label="E-mail" required type="email" id="em"></spl-input>
  <spl-dropzone id="dz" required></spl-dropzone>
  <button type="button" id="next">Suivant</button>
</form>
<script>
customElements.define('spl-input', class extends HTMLElement {
  connectedCallback() {
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = `<label for="i">${this.getAttribute('label')}${this.hasAttribute('required') ? '*' : ''}</label>
                   <input id="i" type="${this.getAttribute('type') || 'text'}">`;
    r.querySelector('input').addEventListener('input', e => this.value = e.target.value);
  }
});
customElements.define('spl-dropzone', class extends HTMLElement {
  connectedCallback() {
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = `<div>Choisissez un fichier ou déposez-le ici</div><input type="file" style="display:none">`;
    r.querySelector('input').addEventListener('change', e => window.cv = e.target.files[0].size);
  }
});
</script>"""
SR_PAGE = """<h2>Postulez facilement</h2>
<form id="f2">
  <sr-dropzone id="dz2"></sr-dropzone>
  <div id="exp"><h3>Expérience</h3></div>
  <sr-autocomplete label="Intitulé" required id="ti"></sr-autocomplete>
  <button type="button">Suivant</button>
</form>
<script>
const TITLES = [["Machine Learning Engineer", "Ingénieur en apprentissage machine"],
                ["Machine Learning Scientist", "Scientifique en apprentissage machine"]];
customElements.define('spl-select-option', class extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    this.attachShadow({mode: 'open'}).innerHTML = '<div style="padding:8px"><slot></slot></div>';
  }
});
customElements.define('sr-autocomplete', class extends HTMLElement {
  connectedCallback() {
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = `<label for="i">${this.getAttribute('label')}*</label>
      <input id="i" role="combobox" aria-autocomplete="both" aria-controls="menu" required>
      <div role="listbox" id="menu"></div>`;
    const inp = r.querySelector('input'), menu = r.querySelector('#menu');
    let timer;
    inp.addEventListener('input', () => {             // like the real one: answers a little later
      clearTimeout(timer);
      this.value = '';                                // typed text alone is NOT a value
      timer = setTimeout(() => {
        const q = inp.value.trim().toLowerCase();
        menu.innerHTML = '';
        if (!q) return;
        const items = [["#spl-custom-option", inp.value.trim()]].concat(
            TITLES.filter(([v]) => v.toLowerCase().includes(q)).map(([v, label]) => [v, label]));
        for (const [v, label] of items) {
          const o = document.createElement('spl-select-option');
          o.setAttribute('value', v); o.textContent = label;
          o.addEventListener('click', () => {
            this.value = v === '#spl-custom-option' ? inp.value.trim() : v;
            inp.value = this.value; menu.innerHTML = '';
          });
          menu.appendChild(o);
        }
      }, 400);
    });
  }
});
customElements.define('sr-dropzone', class extends HTMLElement {
  connectedCallback() {
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = `<div>Choisissez un fichier ou déposez-le ici</div><input type="file" style="display:none">`;
    const f = r.querySelector('input');
    f.addEventListener('change', () => {
      f.value = '';                                   // SmartRecruiters takes the file and empties its input
      const busy = document.createElement('div');
      busy.className = 'spinner'; busy.textContent = 'Analyse de votre CV...';
      document.body.appendChild(busy);
      setTimeout(() => {                              // ~2.5 s later: the experience read from the CV
        busy.remove();
        document.getElementById('exp').insertAdjacentHTML('beforeend', '<div class="card"><b>Data Scientist</b>' +
          '<p>2026 - Actuellement. ' + 'Projets LLM, RAG, fine-tuning, agents, bases vectorielles. '.repeat(8) + '</p></div>');
      }, 2500);
    });
  }
});
</script>"""
UIMM_PAGE = """<p>Votre candidature est presque terminée ! Afin de la finaliser, merci de créer votre compte.</p>
<form><p>Civilité*</p>
  <label><input type="radio" name="c" value="m">Monsieur</label> <label><input type="radio" name="c" value="f">Madame</label>
  <div class="fl"><input type="text" id="n"><label for="n">Nom*</label></div>
  <div class="fl"><input type="text" id="pn"><label for="pn">Prénom*</label></div>
  <div class="fl"><input type="email"><label>Email*</label></div>
  <div class="fl"><input type="password" id="p1"><label>Mot de passe*</label><small>8 caractères minimum</small></div>
  <div class="fl"><input type="password" id="p2"><label>Confirmation du mot de passe*</label></div>
  <button type="button">Valider</button>
</form>
<script>   // a key handler that loses the "&" typed in the first field (the confirmation then differs)
document.getElementById('p1').addEventListener('keydown', e => { if (e.key === '&') e.preventDefault(); });
</script>"""
PROFILE = {"identity": {"first_name": "Adil", "last_name": "AMZAZ", "email": "adil@example.com"}}

with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(PAGE)
    (ROOT / "runs" / "tests" / "shadow").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "shadow", Human([]), {"board_host": "x"}, str(CV))
    state = t.read_page()
    print(state)
    assert re.search(r'input:text "Prénom\*?" REQUIRED', state), state
    assert re.search(r'input:email "E-mail\*?" REQUIRED', state), state
    assert re.search(r'"Choisissez un fichier[^"]*\(file input\)" REQUIRED', state), state
    did = t.autopilot(PROFILE)
    print(did)
    vals = page.evaluate("() => ['fn', 'ln', 'em'].map(i => document.getElementById(i).value)")
    assert vals == ["Adil", "AMZAZ", "adil@example.com"], (vals, did)
    assert page.evaluate("() => window.cv") == CV.stat().st_size, did               # CV in the shadow drop zone

    # while YOU act in Chrome (captcha, login...), your own "Attach" must open the real file picker (Kpler)
    class Checker(Human):
        def __call__(self, prompt=""):
            self.during = len(page._impl_obj.listeners("filechooser"))
            return super().__call__(prompt)
    t.close()
    h = Checker([""])
    t2 = BrowserTools(page, ROOT / "runs" / "tests" / "shadow", h, {"board_host": "x", "supervised": True}, str(CV))
    before = len(page._impl_obj.listeners("filechooser"))
    t2.wait_for_human("solve the captcha")
    assert before >= 1 and h.during == 0 and len(page._impl_obj.listeners("filechooser")) == before, (before, h.during)
    t2.close()

    # SmartRecruiters again: 1) after the CV upload the site READS the CV (a few seconds) and fills the form,
    # then clears its file input -> the agent waits, says so, keeps what was filled;
    # 2) job-title search field: the suggestions are <spl-select-option> web components inside a listbox
    page2 = s.new_tab(LINKEDIN + "/jobs/view/3900000008/")
    page2.set_content(SR_PAGE)
    t3 = BrowserTools(page2, ROOT / "runs" / "tests" / "shadow", Human([]), {"board_host": "x"}, str(CV))
    state = t3.read_page()
    dz = re.search(r"\[((?:f\d+)?e\d+)\][^\n]*Choisissez un fichier", state).group(1)
    out = t3.upload_cv(dz)
    print(out[:400])
    assert out.startswith("uploaded") and "THE SITE READ YOUR CV" in out, out[:300]
    assert "Data Scientist" in out or page2.evaluate("() => document.body.innerText.includes('Data Scientist')")
    state = t3.read_page()
    title = re.search(r'\[((?:f\d+)?e\d+)\][^\n]*"Intitul', state).group(1)
    out = t3.search_select(title, "Machine Learning Engineer")
    print(out[:200])
    assert out.startswith("selected") and "verified: True" in out, out[:300]
    assert page2.evaluate("() => document.getElementById('ti').value") == "Machine Learning Engineer"
    t3.close()

    # UIMM (lindustrie-recrute.fr): floating labels AFTER the field -> each field had the PREVIOUS label
    # ("Madame" on Nom, "Nom" on Prénom...); and the password confirmation did not match
    import os
    os.environ["JOBAGENT_ACCOUNT_PASSWORD"] = "Test-pass1&x"
    page3 = s.new_tab(LINKEDIN + "/jobs/view/3900000009/")
    page3.set_content(UIMM_PAGE)
    t4 = BrowserTools(page3, ROOT / "runs" / "tests" / "shadow", Human([]), {"board_host": "x", "accounts": True}, str(CV))
    state = t4.read_page()
    print(state)
    for want in ("Nom*", "Prénom*", "Email*", "Mot de passe*", "Confirmation du mot de passe*"):
        assert re.search(r'input:\w+ "%s"' % re.escape(want), state), (want, state)
    assert not re.search(r'input:text "Madame"', state), state
    pw = re.search(r'\[((?:f\d+)?e\d+)\] input:password "Mot de passe', state).group(1)
    out = t4.fill_password(pw)
    assert "verified: True" in out and "2 password fields" in out, out[:300]
    assert page3.evaluate("() => document.getElementById('p1').value === document.getElementById('p2').value")
    t4.close()

    # Free-Work: "Je postule" on an offer you already applied to -> red toast "a déjà une candidature sur cette
    # offre": that IS applied (saved, next offer), not a reason to click again and call the human
    page4 = s.new_tab(LINKEDIN + "/jobs/view/3900000010/")
    page4.set_content("""<form><h2>Postuler à cette offre</h2><p>CV partagé: Cv_Adil.pdf</p><textarea>Bonjour</textarea>
      <button type="button" onclick="setTimeout(() => document.body.insertAdjacentHTML('beforeend',
        '<div class=toast-error><b>Une erreur est survenue</b><p>L\\'utilisateur sélectionné a déjà une candidature sur cette offre.</p></div>'), 500)">Je postule</button></form>""")
    t5 = BrowserTools(page4, ROOT / "runs" / "tests" / "shadow", Human([]), {"board_host": "x", "allow_submit": True}, str(CV))
    state = t5.read_page()
    t5.click(re.search(r'\[((?:f\d+)?e\d+)\][^\n]*"Je postule', state).group(1))
    page4.wait_for_timeout(800)
    t5.read_page()
    assert "déjà une candidature" in t5.success, t5.success
    t5.close()
    s.close()
print("\nALL SHADOW CHECKS PASSED")
