"""
Offline test of the whole hunt (search graph + apply node), no API key, no Indeed:
fake results page with 3 offers, a scripted "human" and a scripted "LLM".

  python tests/test_hunt.py

Expected: offer 1 (ACME, has LangGraph) -> human says apply -> agent fills -> applied
          offer 2 (BetaCorp, no LangGraph) -> filtered by the mandatory keyword, never shown
          offer 3 (Gamma, has LangGraph)  -> human says skip
          the results tab is never clicked (the "Créer une alerte" button stays untouched)
"""
import builtins, functools, http.server, json, os, sys, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
os.environ["BROWSER"] = "chromium"
SITE = ROOT / "tests" / "fake_site"
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8767), functools.partial(
    http.server.SimpleHTTPRequestHandler, directory=str(SITE)))
srv.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start()

import explore
def headless_session(self, p):
    self.browser = None
    self.ctx = p.chromium.launch_persistent_context(str(ROOT / "runs" / "test-profile-hunt"), headless=True)
explore.Session.__init__ = headless_session

import db
db.DB_PATH = ROOT / "runs" / "test-hunt.db"
db.DB_PATH.parent.mkdir(exist_ok=True)
if db.DB_PATH.exists():
    db.DB_PATH.unlink()

# scripted human: decide offer 1, the agent's questions, "submitted?", decide offer 3
answers = iter(["a", "3 ans", "y", "y", "s",      # hunt 1: apply ACME, skip Gamma
                "s"])                              # hunt 2: BetaCorp (was filtered) is shown again -> skip
asked = []
def human(prompt=""):
    a = next(answers)
    asked.append((prompt.strip()[:40], a))
    print(prompt, a)
    return a
builtins.input = human

import litellm
import test_fake_llm_planner as fake            # same scripted LLM as test_fake_llm.py
litellm.completion = fake.fake_completion

import agent, hunt
agent.check_llm_server = lambda: None
criteria = {"query": "", "location": "", "mandatory": ["LangGraph"], "excluded": ["stage"],
            "easy_apply_only": True, "max_pages": 1, "search_url": "http://127.0.0.1:8767/results.html"}
state = hunt.hunt(criteria, ask=human)

con = db.connect()
rows = {r["company"]: r for r in con.execute("SELECT * FROM applications")}
print({k: v["status"] for k, v in rows.items()})
assert rows["ACME IA"]["status"] == "applied" and rows["ACME IA"]["applied_at"]
assert rows["BetaCorp"]["status"] == "filtered" and "LangGraph" in rows["BetaCorp"]["notes"]
skipped = [r for r in rows.values() if r["status"] == "skipped"]
assert len(skipped) == 1 and "job3" in skipped[0]["url"]
assert sum(1 for p, a in asked if p.startswith("Apply?")) == 2, asked        # BetaCorp never asked
assert state["stats"]["filtered"] == 1 and state["stats"]["skipped"] == 1

# ---- hunt 2: new keywords. Filtered offers are RE-CHECKED, applied/skipped ones are not shown.
asked.clear()
state2 = hunt.hunt({**criteria, "mandatory": [], "any_of": ["SQL", "power bi"]}, ask=human)
shown = [p for p, a in asked if p.startswith("Apply?")]
assert len(shown) == 1, asked                                           # only BetaCorp
assert state2["stats"].get("known_applied") == 1 and state2["stats"].get("known_skipped") == 1, state2["stats"]
assert state2["stats"]["filtered"] == 0                                 # Gamma not re-read (skipped)
print("\nALL HUNT CHECKS PASSED")
