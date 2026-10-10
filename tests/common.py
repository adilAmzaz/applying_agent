"""
Shared offline test setup: 2 local fake sites (job board :8767, company site :8771), headless Chromium,
a temporary database / examples file, and a scripted "LLM" (judge + apply agent). No API key, no Indeed.
"""

import builtins
import functools
import http.server
import json
import os
import re
import sys
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / "runs" / "tests"
TMP.mkdir(parents=True, exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
SCRIPT = Path(sys.argv[0]).stem or "test"               # each test file: its own browser profile, profile copy, reports
os.environ.update(BROWSER="chromium", HEADLESS="1", BROWSER_PROFILE=str(TMP / f"profile-{SCRIPT}"))
import shutil as _sh                                     # noqa: E402
for _c in list((TMP / f"profile-{SCRIPT}").rglob("*Cache*")):     # the fake pages change: never a cached old one
    if _c.is_dir():
        _sh.rmtree(_c, ignore_errors=True)
BOARD = "http://127.0.0.1:8767"

LINKEDIN = "http://127.0.0.1:8772"
WTTJ = "http://127.0.0.1:8773"
HELLOWORK = "http://127.0.0.1:8774"
FREEWORK = "http://127.0.0.1:8775"
import fakes                                            # noqa: E402
_servers = fakes.start()                                # run_all.py serves them already: then nothing to start

from core.config import KEY_ENV                         # noqa: E402
for _var in KEY_ENV.values():                           # the scripted LLM needs no key, but core/llm skips
    os.environ.setdefault(_var, "test-key")             # a model whose key is missing
from core import db                                     # noqa: E402
from core import answers                                # noqa: E402
import shutil                                           # noqa: E402
shutil.copy(ROOT / "profile.json", TMP / f"profile-{SCRIPT}.json")
answers.PATH = TMP / f"profile-{SCRIPT}.json"           # tests never touch your profile.json
answers.OLD = TMP / f"answers-old-{SCRIPT}.json"
REPORTS = TMP / f"reports-{SCRIPT}"
from core import accounts                               # noqa: E402
accounts.PATH = TMP / f"accounts-{SCRIPT}.json"         # tests never touch your accounts.json
accounts.SECRETS = TMP / f"site-passwords-{SCRIPT}.json"   # nor your .site_passwords.json
from core.config import CONFIG                          # noqa: E402

CV = TMP / "cv_test.pdf"
CV.write_bytes(b"%PDF-1.4 fake cv")


def fresh(name: str, keep_db: bool = False, **overrides):
    """New empty database + config for one scenario (keep_db: same config, database kept: agent processes)."""
    db.DB_PATH = TMP / f"{name}.db"
    if db.DB_PATH.exists() and not keep_db:
        db.DB_PATH.unlink()
    CONFIG["search"].update(query="", queries=[], extra_search_urls=[BOARD + "/results.html"], max_pages=1, source="indeed",
                            sources=["indeed"])
    for platform in ("indeed", "linkedin", "wttj", "hellowork", "freework"):
        CONFIG[platform] = {"pause_seconds": 0.2, "max_pages": 1}
    CONFIG["prefilter"] = {"any_of": [], "mandatory": [], "excluded": ["power bi"]}
    CONFIG["judge"]["examples_file"] = str((TMP / f"{name}-examples.md").relative_to(ROOT))
    CONFIG["apply"].update(cv_path=str(CV), external_sites=True, max_steps=30, autopilot=False)   # test_autopilot: on
    CONFIG["auto_apply"].update(enabled=False, verdicts=["high"], min_score=85, submit=False,
                                approve_legal=False, max_per_run=5, supervised=False)
    CONFIG["llm"]["fallbacks"] = []                     # tests never depend on your config.toml models
    CONFIG.setdefault("telegram", {})["enabled"] = False
    CONFIG["notify"] = {"reports_dir": str(REPORTS.relative_to(ROOT))}
    CONFIG["dedupe"] = {"enabled": True, "rejudge_if_title_changed": True}
    CONFIG["avoid"] = {"sites": [], "companies": []}   # your [avoid] list never changes the tests
    for section, values in overrides.items():
        CONFIG[section].update(values)
    return db.connect()


# ------------------------------------------------------------------ scripted LLM
CALLS = {"judge": 0, "apply": 0, "images": 0, "maybe_prompt": 0}
JUDGE = {"ACME": ("high", 92), "Gamma": ("maybe", 60), "Delta": ("high", 88)}


def _ref(state, pattern):
    line = [l for l in state.splitlines() if re.search(pattern, l, re.I) and re.search(r"\[(f\d+)?e\d", l)][-1]
    return re.search(r"\[((?:f\d+)?e\d+)\]", line).group(1)


def _plan(state: str, last: str, history: str):
    """What a good apply agent does, as rules."""
    if not state:
        return "read_page", {}
    if "TITLE: SUBMITTED" in state or "Candidature envoy" in state:
        return "finish", {"status": "submitted", "summary": "sent"}
    # unknown company site: explore (cookie banner, find the apply link, captcha, look)
    omega = "8771/careers" in state or "8771/security" in state or "8771/apply_frame" in state
    if omega and "uploaded cv_test.pdf" in history and "no form field here" in state and "BLOCKED" not in last:
        return "finish", {"status": "submitted", "summary": "sent"}
    if "NOBODY HERE" in last or "skipped it" in last:
        return "finish", {"status": "needs_human", "summary": "captcha: nobody to solve it"}
    if omega and "CAPTCHA" in state and "the human did it" not in last:
        return "wait_for_human", {"reason": "solve the captcha"}
    if omega and "Tout refuser" in state:
        return "click", {"ref": _ref(state, "Tout refuser")}
    if omega and "no form field here" in state:
        if last.lstrip().startswith("[") and "Je postule" in last:
            return "click", {"ref": re.search(r"\[((?:f\d+)?e\d+)\]", last).group(1)}
        if "screenshot taken" not in history:
            return "look", {}
        return "find", {"text": "postuler|apply|candidater|je postule"}
    if re.search(r"Oui \[question: Êtes-vous à l.aise avec le travail hybride[^\n]*checked=false", state):
        return "set_checked", {"ref": _ref(state, r"Oui \[question: Êtes-vous à l.aise"), "checked": True}
    if "JOB BOARD OFFER PAGE" in state:
        if "Candidature simplifiée" in state and "Enregistrer" in state and "BLOCKED" not in last:
            return "click", {"ref": _ref(state, '"Enregistrer')}            # LinkedIn save: must be BLOCKED
        if "Candidature simplifiée" in state:
            return "click", {"ref": _ref(state, "Candidature simplifiée")}
        if "Postuler maintenant" in state and "Activer" in state and "BLOCKED" not in last:
            return "click", {"ref": _ref(state, "Activer")}                  # must be BLOCKED
        if "Postuler maintenant" in state:
            return "click", {"ref": _ref(state, "Postuler maintenant")}
        return "click", {"ref": _ref(state, 'Continuer pour postuler|"Postuler|"Je postule')}
    if re.search(r'Combien[^\n]*"(?![^\n]*value=)', state) and 'value="3 ans"' not in state:
        return "type_text", {"ref": _ref(state, "Combien"), "text": "3 ans"}
    if "Combien" in state and "Courant" not in state:
        return "select_option", {"ref": _ref(state, "anglais"), "option": "Courant"}
    if "Combien" in state:
        return "click", {"ref": _ref(state, "Continuer|Suivant")}
    if "Créer un compte" in state and "account creation" not in history:
        return "click", {"ref": _ref(state, "Créer un compte")}             # must be BLOCKED
    if "Nom complet" in state and not re.search(r'Nom complet" value=', state):
        return "type_text", {"ref": _ref(state, "Nom complet"), "text": "Adil Amzaz"}
    if '"Email"' in state and not re.search(r'"Email" value=', state):
        return "type_text", {"ref": _ref(state, '"Email"'), "text": "adil@example.com"}
    if "CV (PDF)" in state and not re.search(r'CV \(PDF\)[^"\n]*" value=', state):
        return "upload_cv", {"ref": _ref(state, r"CV \(PDF\)")}
    for legal in ("Approuver", "politique de confidentialit"):
        if re.search(legal + r"[^\n]*checked=false", state):
            if "DENIED" in history:
                return "finish", {"status": "needs_human", "summary": "privacy checkbox needs approval"}
            return "set_checked", {"ref": _ref(state, legal), "checked": True}
    if "Message au recruteur" in state and not re.search(r'Message au recruteur" value=', state):
        return "type_text", {"ref": _ref(state, "Message au recruteur"), "text": "Bonjour, ma candidature."}
    if re.search(r"alertes[^\n]*checked=true", state):
        return "set_checked", {"ref": _ref(state, "alertes"), "checked": False}
    if re.search(r"Suivre[^\n]*checked=true", state):
        return "set_checked", {"ref": _ref(state, "Suivre"), "checked": False}   # LinkedIn "follow company"
    if "Examiner" in state or "Vérifier" in state:
        return "click", {"ref": _ref(state, "Examiner|Vérifier")}
    for send in ("Déposer ma candidature", "Envoyer ma candidature", "Envoyer la candidature", '"Je postule'):
        if send in state:
            if "BLOCKED" in last:
                return "finish", {"status": "ready_for_review", "summary": "filled, waiting for the human"}
            return "click", {"ref": _ref(state, send)}
    return "finish", {"status": "stuck", "summary": "unknown page"}


def _msg(content=None, name=None, args=None, n=0):
    calls = [types.SimpleNamespace(id=f"c{n}", function=types.SimpleNamespace(
        name=name, arguments=json.dumps(args)))] if name else None
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
        content=content, tool_calls=calls))], usage=types.SimpleNamespace(prompt_tokens=100, completion_tokens=10))


def fake_completion(model, messages, **kw):
    if "You screen job offers" in str(messages[0]["content"]):
        CALLS["judge"] += 1
        offer = messages[-1]["content"]
        company = next((c for c in JUDGE if c in offer), "Other")
        verdict, score = JUDGE.get(company, ("low", 10))
        return _msg("```json\n" + json.dumps({
            "verdict": verdict, "score": score, "reasons": [f"{company} reason"], "red_flags": [],
            "title": "Engineer", "company": company, "location": "Paris", "contract_type": "CDI",
            "skills": ["Python", "LLM"], "summary": f"{company} mission."}) + "\n```")
    CALLS["apply"] += 1
    CALLS["images"] += sum(1 for m in messages if isinstance(m.get("content"), list))
    CALLS["maybe_prompt"] += "PARTIAL match" in messages[0]["content"]
    tools_out = [m["content"] for m in messages if m["role"] == "tool"]
    state = next((t for t in reversed(tools_out) if "ELEMENTS:" in t), "")
    name, args = _plan(state, tools_out[-1] if tools_out else "", "\n".join(tools_out))
    return _msg(name=name, args=args, n=len(messages))


import litellm                                          # noqa: E402
litellm.completion = fake_completion


class Human:
    """Scripted terminal answers; records every question."""
    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, prompt=""):
        a = self.answers.pop(0) if self.answers else ""
        self.asked.append((prompt.strip()[:60], a))
        print(prompt, a)
        return a


builtins.input = lambda prompt="": (_ for _ in ()).throw(AssertionError(f"unexpected input(): {prompt}"))
