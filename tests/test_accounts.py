"""
Default account on recruitment sites: the password comes from the environment (.env), is typed by fill_password,
never shown to the LLM, never logged. Never on Google / LinkedIn / Microsoft..., never "Continuer avec Google".
"""
import json
import os
import re
from common import CONFIG, LINKEDIN, ROOT, Human, fresh
from playwright.sync_api import sync_playwright
from core import accounts, policy
from core.browser import Session
from core.tools import BrowserTools

SECRET = "Test-Only-Pw-123!"
os.environ["JOBAGENT_TEST_ACCOUNT_PW"] = SECRET
fresh("accounts")
CONFIG["accounts"] = {"enabled": True, "password_env": "JOBAGENT_TEST_ACCOUNT_PW"}
accounts.PATH = ROOT / "runs" / "tests" / "accounts.json"
accounts.PATH.unlink(missing_ok=True)
assert accounts.enabled()

on = {"accounts": True, "board_host": "www.linkedin.com"}
off = {"accounts": False, "board_host": "www.linkedin.com"}
wd = "https://onepoint.wd3.myworkdayjobs.com/fr-FR/careers/job/apply"
pw = {"name": "Mot de passe*", "type": "password"}
assert policy.check("fill_password", pw, wd, on)[0] == policy.ALLOW
assert policy.check("fill_password", pw, wd, off)[0] == policy.FORBIDDEN                 # disabled
assert policy.check("fill_password", pw, "https://accounts.google.com/signin", on)[0] == policy.FORBIDDEN
assert policy.check("fill_password", pw, "https://www.linkedin.com/login", on)[0] == policy.FORBIDDEN
assert policy.check("type", pw, wd, on)[0] == policy.FORBIDDEN                           # the LLM never types it
assert policy.check("click", {"name": "Créer un compte"}, wd, on)[0] == policy.ALLOW
assert policy.check("click", {"name": "Se connecter"}, wd, on)[0] == policy.ALLOW
assert policy.check("click", {"name": "Créer un compte"}, wd, off)[0] == policy.FORBIDDEN
assert policy.check("click", {"name": "Continuer avec Google"}, wd, on)[0] == policy.FORBIDDEN   # no SSO
assert policy.check("click", {"name": "Sign in with LinkedIn"}, wd, on)[0] == policy.FORBIDDEN
assert policy.check("click", {"name": "Mot de passe oublié ?"}, wd, on)[0] == policy.FORBIDDEN

REGISTER = """<h2>Créer un compte</h2><form onsubmit="event.preventDefault()">
 <label for="em">Adresse e-mail*</label><input id="em" type="email" required>
 <label for="p1">Mot de passe*</label><input id="p1" type="password" required>
 <label for="p2">Vérifier le nouveau mot de passe*</label><input id="p2" type="password" required>
 <script>p1.addEventListener('input', () => p2.value = '');</script>
 <button type="button">Continuer avec Google</button><button id="go">Créer un compte</button></form>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(REGISTER)
    run = ROOT / "runs" / "tests" / "accounts"
    run.mkdir(parents=True, exist_ok=True)
    (run / "actions.jsonl").unlink(missing_ok=True)
    t = BrowserTools(page, run, Human([]), {"board_host": "x", "accounts": True})
    state = t.read_page()
    ref = re.search(r'\[(e\d+)\] input:password "Mot de passe', state).group(1)
    out = t.fill_password(ref)                                                  # ONE call: both fields
    assert "in the 2 password fields" in out and "verified: True" in out and SECRET not in out, out[:160]
    assert page.input_value("#p1") == SECRET and page.input_value("#p2") == SECRET
    ref = re.search(r'\[(e\d+)\] input:password "Mot de passe', state).group(1)
    assert t.type_text(ref, "something").startswith("BLOCKED")                 # typing a password: refused
    google = re.search(r'\[(e\d+)\] button "Continuer avec Google', state).group(1)
    assert t.click(google).startswith("BLOCKED")
    assert SECRET not in t.read_page()                                            # never in what the LLM sees
    t.close()
    # BairesDev: login page of a site with NO account yet -> straight to "Sign Up here" (the link was not even shown)
    page2 = s.new_tab(LINKEDIN + "/jobs/view/3900000008/")
    accounts.PATH.write_text("{}", encoding="utf-8")
    page2.set_content("""<h1>Applicant Site</h1><button>Sign in with Google</button>
      <label for="u">Username *</label><input id="u"><label for="c">Access Code *</label><input id="c" type="password">
      <button>Sign In</button><p>Don't have an account? <a href="#signup">Sign Up here</a></p>""")
    t2 = BrowserTools(page2, run, Human([]), {"board_host": "x", "accounts": True})
    st = t2.read_page()
    assert re.search(r'NO ACCOUNT on this site yet .*click \[e\d+\] "Sign Up here"', st), st
    accounts.remember("127.0.0.1:8772", "account created")
    assert "NO ACCOUNT" not in t2.read_page()                                      # known site: log in
    t2.close()

    # LCL: sign-up refused, "this email already has an account", site NOT in accounts.json -> the human logs in,
    # then (terminal, hidden input) gives the login + this site's password: saved, typed alone next time
    accounts.SECRETS = ROOT / "runs" / "tests" / ".site_passwords.json"
    accounts.SECRETS.unlink(missing_ok=True)
    data = accounts.known_sites(); data.pop("127.0.0.1:8772", None)
    accounts.PATH.write_text(json.dumps(data), encoding="utf-8")
    page3 = s.new_tab(LINKEDIN + "/jobs/view/3900000003/")
    page3.set_content("""<h2>Créer un compte</h2><label for="e">E-mail</label><input id="e" value="adil@example.com">
      <label for="p">Mot de passe</label><input id="p" type="password"><label for="p2">Confirmation</label><input id="p2" type="password">
      <p class="error">Cette adresse e-mail est déjà utilisée.</p><button>Créer mon compte</button>""")
    asked = []
    def secret(q, hidden):
        asked.append((q, hidden))
        return "Site-Own-Pw-9" if hidden else "adil@example.com"
    t3 = BrowserTools(page3, run, Human(["", ""]), {"board_host": "x", "accounts": True, "supervised": True,
                                                   "ask_secret": secret})
    st = t3.read_page()
    assert "AN ACCOUNT ALREADY EXISTS" in st and "NO ACCOUNT" not in st, st
    t3.wait_for_human("log in: an account already exists on this site")
    assert accounts.known_sites()["127.0.0.1:8772"]["login"] == "adil@example.com"
    assert accounts.password_for("127.0.0.1:8772") == "Site-Own-Pw-9" and accounts.password_for("other") == SECRET
    assert [h for _, h in asked] == [False, True]                                  # the password asked hidden
    assert "YOU HAVE AN ACCOUNT" in t3.read_page()
    out = t3.fill_password(re.search(r'\[(e\d+)\] input:password "Mot de passe', t3.read_page()).group(1))
    assert "verified: True" in out
    assert page3.evaluate("() => document.getElementById('p').value") == "Site-Own-Pw-9"
    t3.close()
    s.close()
log = (run / "actions.jsonl").read_text(encoding="utf-8")
assert SECRET not in log and "Site-Own-Pw-9" not in log and "fill_password" in log   # never in the logs
assert "Site-Own-Pw-9" not in accounts.PATH.read_text(encoding="utf-8")         # not in accounts.json
assert "127.0.0.1:8772" in accounts.known_sites()                                # the site is remembered
from nodes.apply import account_rule
assert "fill_password" in account_rule() and SECRET not in account_rule()
print("\nALL ACCOUNT CHECKS PASSED")
