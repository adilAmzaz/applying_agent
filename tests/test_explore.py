"""
The apply agent on an UNKNOWN company site (the case where it used to get lost):
cookie banner, no form, "Je postule" far down the page (a link the old page summary dropped),
a security check, then the form inside an embedded frame (like Workday / SmartRecruiters).

  supervised (you watching)  -> the captcha is asked in the terminal, then the form is SENT
  unattended                 -> stops at the captcha: needs_human
"""
import re
from pathlib import Path
import time
from common import BOARD, CALLS, CONFIG, ROOT, Human, fresh
from playwright.sync_api import sync_playwright
from core.browser import Session
from nodes.apply import apply

URL = BOARD + "/job6.html?jk=F6"


def run(name, supervised, ask):
    fresh(name, auto_apply={"enabled": True, "submit": True, "approve_legal": True, "supervised": supervised})
    with sync_playwright() as p:
        s = Session(p)
        page = s.new_tab(URL)
        res = apply(page, URL, "auto", ask if supervised else None, ROOT / "runs" / "tests" / name, verdict="maybe")
        s.close()
    return res


class SlowHuman(Human):
    """Answers the 'HUMAN NEEDED' prompt after the captcha page 'is solved' (it redirects after 12 s)."""
    def __call__(self, prompt=""):
        if "HUMAN NEEDED" in prompt:
            time.sleep(12.5)
        return super().__call__(prompt)


# 1) supervised: captcha by the human, form in a frame filled and SENT ------------------------
human = SlowHuman([""])
CALLS.update(apply=0, images=0, maybe_prompt=0)
res = run("explore1", True, human)
print(res["status"], res["summary"][:300], CALLS)
assert res["status"] == "submitted" and res["submitted"], res["summary"]
assert any("HUMAN NEEDED" in q for q, a in human.asked), human.asked
assert "done by you: solve the captcha" in res["summary"]
assert CALLS["images"] >= 1                                                   # look(): the screenshot reached the LLM
assert CALLS["maybe_prompt"] >= 1                                             # "maybe" offer: open to other roles
log = (ROOT / "runs" / "tests" / "explore1" / "actions.jsonl").read_text(encoding="utf-8")
assert '"Tout refuser"' in log and '"Je postule"' in log and "upload_cv" in log
assert '"el": "Recevoir des alertes emploi", "wanted": false' in log          # opt-in unticked, inside the frame

# 2) unattended: nobody for the captcha -> needs_human, nothing sent ----------------------------------
res = run("explore2", False, None)
print(res["status"], res["summary"][:200])
assert res["status"] == "needs_human" and not res["submitted"], res

# 3) captcha detection: LinkedIn-like page with INVISIBLE anti-robot frames = no captcha (the false alarm)
from core.tools import BrowserTools
LONG = "<p>" + "Description du poste, missions, profil recherché. " * 80 + "</p>"
PAGES = {
    "invisible": f"""<h1>INGENIEUR AI H/F</h1><button>Postuler</button>{LONG}
        <iframe src="http://127.0.0.1:8771/recaptcha/enterprise/anchor?k=x&size=invisible" width="256" height="60"></iframe>
        <iframe src="http://127.0.0.1:8771/arkoselabs/fc/challenge" style="width:0;height:0;border:0"></iframe>
        <iframe title="recaptcha" src="http://127.0.0.1:8771/x" style="position:absolute;left:-9999px;width:300px;height:80px"></iframe>
        <footer>This site is protected by reCAPTCHA and the Google Privacy Policy. Security check of your account.</footer>""",
    "visible": """<h1>Un instant</h1><iframe title="reCAPTCHA" src="http://127.0.0.1:8771/recaptcha/api2/anchor?k=x&size=normal"
                     width="304" height="78"></iframe>""",
    "text": "<h1>Vérification de sécurité</h1><p>Prouvez que vous êtes humain pour continuer.</p>",
}
fresh("captcha")
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(BOARD + "/job6.html?jk=F6")
    for name, html in PAGES.items():
        page.set_content(html)
        page.wait_for_timeout(300)
        (ROOT / "runs" / "tests" / f"captcha-{name}").mkdir(parents=True, exist_ok=True)
        t = BrowserTools(page, ROOT / "runs" / "tests" / f"captcha-{name}", Human([]), {"board_host": "x", "supervised": True})
        state = t.read_page()
        print(name, t.captcha)
        assert t.captcha == (name != "invisible"), (name, state[:400])
    # the human answers "none" to a false alarm: the warning stops on this site, the agent goes on
    page.set_content(PAGES["visible"])
    (ROOT / "runs" / "tests" / "captcha-none").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "captcha-none", Human(["none"]), {"board_host": "x", "supervised": True})
    t.read_page()
    out = t.wait_for_human("solve the captcha")
    assert "NOTHING to do here" in out and "CAPTCHA" not in out and not t.captcha and not t.unanswered, out[:300]
    s.close()

# 4) the Assystem Easy Apply step that blocked: years-of-experience dropdown + handicap box, in a dialog
from core import answers
from nodes.apply import system_prompt
ASSYSTEM = """<main><h1>Ingénieur Machine Learning - MLOps H/F</h1><p>Assystem. Description de l'offre...</p></main>
<div role="dialog"><h2>Postuler chez Assystem</h2><h3>Questions supplémentaires</h3>
 <p>Je souhaite faire part à Assystem de ma situation de handicap (RQTH, CMI, IPP, Invalidité...)</p>
 <input type="checkbox" id="h"><label for="h">Confirmé</label>
 <label for="y">Combien d'années d'expérience avez-vous sur ce poste ?</label>
 <select id="y" required><option>Sélectionnez une option</option><option>Moins d'un an</option><option>1 à 3 ans</option>
   <option>3 à 5 ans</option><option>Plus de 5 ans</option></select>
 <button>Retour</button><button>Suivant</button></div>"""
import shutil
shutil.copy(ROOT / "profile.json", answers.PATH)                                 # fresh copy of the profile
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(BOARD + "/job6.html?jk=F6")
    page.set_content(ASSYSTEM)
    (ROOT / "runs" / "tests" / "assystem").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "assystem", Human(["1 an en IA"]), {"board_host": "x", "supervised": True})
    state = t.read_page()
    print(state)
    ref = re.search(r"\[(e\d+)\] select[^\n]*Combien", state).group(1)
    assert "options=[" in state and "Plus de 5 ans" in state                       # the agent SEES the options
    assert re.search(r'"Confirmé \[question: Je souhaite faire part à Assystem de ma situation de handicap', state), state
    assert "Assystem. Description" not in t.get_text() and "Questions supplémentaires" in t.get_text()  # the dialog
    start = time.time()
    out = t.select_option(ref, "banana")
    assert "NO OPTION matches" in out and "1 à 3 ans" in out and time.time() - start < 5, out   # no 30 s wait
    out = t.select_option(ref, "1 an")
    assert out.startswith('selected "1 à 3 ans"'), out[:80]
    assert page.evaluate("() => document.getElementById('y').selectedOptions[0].text") == "1 à 3 ans"
    assert 'value="1 à 3 ans"' in t.read_page()                                     # the state shows the LABEL
    assert page.evaluate("() => document.getElementById('h').checked") is False      # handicap box left alone
    # the candidate's answer is remembered and given to the next applications
    assert t.ask("Combien d'années d'expérience en Machine Learning ?") == "1 an en IA"
    assert "1 an en IA" in system_prompt(True, True) and "Combien d'années" in system_prompt(True, True)
    import json as _j
    assert _j.loads(answers.PATH.read_text(encoding="utf-8"))["answers_given"]["Combien d'années d'expérience en Machine Learning ?"] == "1 an en IA"
    assert "handicap / RQTH" in system_prompt(True, True)
    s.close()

# 5) the Keyrus form: CV drop zone with a HIDDEN file input + "téléchargez" link (opens the OS file picker)
from core.tools import resolve_cv
assert resolve_cv("cv/my.pdf") == str(ROOT / "cv" / "my.pdf")                   # relative to the project
KEYRUS = """<h2>Informations personnelles</h2><form>
 <label for="fn">Prénom</label><input id="fn"> <label for="ln">Nom</label><input id="ln">
 <label for="em">E-mail*</label><input id="em" type="email" required>
 <label for="ph">Téléphone</label><select aria-label="Pays"><option>+33</option></select><input id="ph" type="tel">
 <p>Importer un CV</p>
 <div class="dz">Déposez votre fichier ou <a href="#" onclick="document.getElementById('f').click(); return false">téléchargez</a>
   <input type="file" id="f" style="display:none" accept=".pdf"></div>
 <button>Postuler</button></form>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(BOARD + "/job6.html?jk=F6")
    page.set_content(KEYRUS)
    (ROOT / "runs" / "tests" / "keyrus").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "keyrus", Human([]), {"board_host": "x"}, str(CONFIG["apply"]["cv_path"]))
    state = t.read_page()
    print(state)
    file_line = [l for l in state.splitlines() if "(file input)" in l]
    assert file_line and "Déposez votre fichier" in file_line[0], state              # the hidden input is visible to the agent
    link = re.search(r"\[(e\d+)\] a \"téléchargez", state).group(1)
    out = t.upload_cv(link)                                                          # ref of the drop zone link
    assert out.startswith("uploaded"), out[:120]
    assert page.evaluate("() => document.getElementById('f').files[0].name") == "cv_test.pdf"
    # the CONTENT is there (a path gave Windows Chrome an empty file): same size, starts with %PDF
    assert page.evaluate("() => document.getElementById('f').files[0].size") == Path(CONFIG["apply"]["cv_path"]).stat().st_size
    assert page.evaluate("async () => (await document.getElementById('f').files[0].text()).slice(0, 4)") == "%PDF"
    # clicking "téléchargez" (OS file picker) never blocks: the CV is given automatically
    page.set_content(KEYRUS)
    state = t.read_page()
    t.click(re.search(r"\[(e\d+)\] a \"téléchargez", state).group(1))
    assert page.evaluate("() => document.getElementById('f').files.length") == 1
    s.close()

# 6) Workday (Deloitte): home-made dropdown that toggles on click + date field that only takes key presses
WORKDAY = """<h2>Questions de candidature</h2>
 <label id="lx">Niveau d'expérience*</label>
 <button id="dd" aria-haspopup="listbox" aria-labelledby="lx" onclick="toggle()">Sélectionnez une valeur</button>
 <ul role="listbox" id="lb" style="display:none">
   <li role="option">0-1 an</li><li role="option">1-3 ans</li><li role="option">3-5 ans</li>
   <li role="option">5-7 ans</li><li role="option">7-10 ans</li></ul>
 <label for="d">Date de disponibilité*</label><input id="d" placeholder="JJ/MM/AAAA">
 <button>Enregistrer et continuer</button>
<script>
 function toggle() { const l = document.getElementById('lb'); l.style.display = l.style.display === 'none' ? 'block' : 'none'; }
 document.querySelectorAll('[role=option]').forEach(o => o.onclick = () => {
   document.getElementById('dd').innerText = o.innerText; toggle(); });
 // masked date: only real key presses count, a pasted value is wiped
 let buf = '';
 const d = document.getElementById('d');
 const show = () => { const b = buf.slice(0, 8); d.value = [b.slice(0, 2), b.slice(2, 4), b.slice(4)].filter(Boolean).join('/'); };
 d.addEventListener('keydown', e => { if (/^\d$/.test(e.key)) buf += e.key;
   else if (e.key === 'Backspace') buf = buf.slice(0, -1); e.preventDefault(); show(); });
 d.addEventListener('input', show);
</script>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(BOARD + "/job6.html?jk=F6")
    page.set_content(WORKDAY)
    (ROOT / "runs" / "tests" / "workday").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "workday", Human([]), {"board_host": "x"})
    state = t.read_page()
    print(state)
    dd = re.search(r"\[(e\d+)\] dropdown\(use select_option\) \"Niveau d'expérience", state).group(1)
    page.click("#dd")                                                   # the agent had already opened it once
    out = t.select_option(dd, "2")                                       # profile: 2 years
    assert out.startswith('selected "1-3 ans"'), out[:200]
    assert page.inner_text("#dd") == "1-3 ans"
    state = t.read_page()
    date = re.search(r"\[(e\d+)\] input:text \"Date de disponibilit", state).group(1)
    out = t.type_text(date, "09/10/2026")
    assert page.input_value("#d") == "09/10/2026", (page.input_value("#d"), out[:100])
    # once a list is open, its options are elements the agent can click
    page.click("#dd")
    assert '[e' in t.read_page() and 'option "5-7 ans"' in t.read_page()
    s.close()

# 7) answers given go INTO profile.json; the first version's answers.json is merged in
answers.OLD.write_text(_j.dumps({"k": {"question": "Avez-vous déjà travaillé pour Deloitte ?", "answer": "non",
                                       "date": "2026-10-08"}}), encoding="utf-8")
assert answers.migrate_old_file() == 1 and not answers.OLD.exists()
prof = _j.loads(answers.PATH.read_text(encoding="utf-8"))
assert prof["answers_given"]["Avez-vous déjà travaillé pour Deloitte ?"] == "non"
assert "target_roles" in prof                     # the rest is kept

# 8) success toast (Recruiterflow), send twice prevented, errors shown, REQUIRED by "*", LinkedIn cards ignored
from core import policy
assert policy.check("click", {"name": "Présenter Une Demande"}, "https://x.com/apply", {"board_host": "y"})[0] == policy.FORBIDDEN
RF = """<form onsubmit="event.preventDefault()"><label for="n">Ville*</label><input id="n">
 <div id="err"></div><button type="button" id="go">Go!</button></form>
<ul id="similar"></ul>
<script>
 document.getElementById('go').onclick = () => {
   if (!document.getElementById('n').value) { document.getElementById('err').innerHTML = '<p role="alert">Ce champ est obligatoire</p>'; return; }
   window.sent = (window.sent || 0) + 1;
   const t = document.createElement('div'); t.className = 'toast'; t.innerText = 'Your application has been submitted!';
   document.body.appendChild(t); setTimeout(() => t.remove(), 900);   // a toast that disappears quickly
 };
 // LinkedIn-like: a job card "Candidature envoyée" appears in a list BEFORE the agent fills anything
 setTimeout(() => document.getElementById('similar').innerHTML =
   '<li class="job-card-container" data-job-id="1">Data Engineer · Candidature envoyée</li>', 200);
</script>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(BOARD + "/job6.html?jk=F6")
    page.set_content(RF)
    page.wait_for_timeout(400)
    (ROOT / "runs" / "tests" / "rf").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "rf", Human([]), {"board_host": "x"}, str(CONFIG["apply"]["cv_path"]))
    state = t.read_page()
    assert "Ville*\" REQUIRED" in state and not t.success, state                    # "*" = required; card ignored
    go = re.search(r"\[(e\d+)\] button \"Go!", state).group(1)
    out = t.click(go)                                                               # nothing typed: error
    assert "ERRORS SHOWN ON THE PAGE" in out and "obligatoire" in out and not t.success, out[:400]
    t.type_text(re.search(r"\[(e\d+)\] input:text \"Ville", out).group(1), "Paris")
    out = t.click(re.search(r"\[(e\d+)\] button \"Go!", t.read_page()).group(1))
    assert t.success and t.submitted and "THE APPLICATION IS SENT" in out, (t.success, out[:300])
    out = t.click(go)                                                               # never twice
    assert out.startswith("ALREADY SENT") and page.evaluate("() => window.sent") == 1
    t.close()
    assert not t._watched and not page._impl_obj.listeners("filechooser"), "file picker still intercepted"
    s.close()
print("\nALL EXPLORE CHECKS PASSED")
