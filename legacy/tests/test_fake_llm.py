"""
Offline test of the whole pipeline (tools + policy + agent loop) WITHOUT an API key:
a scripted "fake LLM" drives a fake 3-page Indeed-like form served locally.

  python tests/test_fake_llm.py

Checks: typing is verified, legal checkbox asks the human, pre-checked alert is turned off,
the final "Déposer ma candidature" click is BLOCKED, page text injection is ignored.
"""
import builtins, functools, http.server, json, os, re, sys, threading, types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
SITE = ROOT / "tests" / "fake_site"
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), functools.partial(
    http.server.SimpleHTTPRequestHandler, directory=str(SITE)))
srv.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start()

os.environ["BROWSER"] = "chromium"                   # no Windows Chrome needed for the test
import explore
def headless_session(self, p):                      # no CDP for the test
    self.browser = None
    self.ctx = p.chromium.launch_persistent_context(str(ROOT / "runs" / "test-profile"), headless=True)
explore.Session.__init__ = headless_session

human = iter(["3 ans", "y", "y"])            # python years, legal checkbox, "did you submit?"                          # answers typed by the "human"
builtins.input = lambda prompt="": (print(prompt, end=""), a := next(human), print(a))[1]

import db
db.DB_PATH = ROOT / "runs" / "test-jobs.db"           # never touch the real jobs.db
db.DB_PATH.parent.mkdir(exist_ok=True)
if db.DB_PATH.exists():
    db.DB_PATH.unlink()
import agent, litellm

def ref(state, pattern):
    line = [l for l in state.splitlines() if re.search(pattern, l, re.I) and "[e" in l][-1]
    return re.search(r"\[(e\d+)\]", line).group(1)

def plan(state, asked, blocked, last=""):
    """What a good LLM should do, as rules."""
    if not state:                                       return "read_page", {}
    if "Postuler maintenant" in state and "BLOCKED" not in last: return "click", {"ref": ref(state, "Activer")}  # must be blocked
    if "Postuler maintenant" in state:                  return "click", {"ref": ref(state, "Postuler maintenant")}
    if "Combien" in state and not asked:                return "ask_human", {"question": "Years of Python?"}
    if "Combien" in state and 'value="3 ans"' not in state:
        return "type_text", {"ref": ref(state, "Combien"), "text": "3 ans"}
    if "Combien" in state and "Courant" not in state:   return "select_option", {"ref": ref(state, "anglais"), "option": "Courant"}
    if "Combien" in state:                              return "click", {"ref": ref(state, "Continuer")}
    if re.search(r"Approuver[^\n]*checked=false", state): return "set_checked", {"ref": ref(state, "Approuver"), "checked": True}
    if re.search(r"alertes[^\n]*checked=true", state):  return "set_checked", {"ref": ref(state, "alertes"), "checked": False}
    if "Examiner" in state:                             return "click", {"ref": ref(state, "Examiner")}
    if "Relisez" in state and not blocked:              return "click", {"ref": ref(state, "Déposer")}  # must be blocked
    return "finish", {"status": "ready_for_review", "summary": "Python: 3 ans, anglais: Courant, privacy approved, alert off."}

def fake_completion(model, messages, **kw):
    if not kw.get("tools"):                              # offer extraction call (no tools, JSON answer)
        content = json.dumps({"title": "AI Engineer H/F", "company": "ACME IA", "location": "Paris",
                              "contract_type": "CDI", "remote": "hybrid", "salary": "50-60 k€",
                              "skills": ["Python", "LangGraph", "Qdrant"], "summary": "RAG and LLM agents.",
                              "contact_name": "Marie Dupont", "contact_email": None, "contact_phone": None})
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content="```json\n" + content + "\n```", tool_calls=None))], usage=None)
    tools_out = [m["content"] for m in messages if m["role"] == "tool"]
    state = next((t for t in reversed(tools_out) if "ELEMENTS:" in t), "")
    asked = any(m["role"] == "assistant" and m.get("tool_calls") and
                m["tool_calls"][0]["function"]["name"] == "ask_human" for m in messages)
    blocked = any(t.startswith("BLOCKED") and "submit" in t for t in tools_out)
    name, args = plan(state, asked, blocked, tools_out[-1] if tools_out else "")
    tc = types.SimpleNamespace(id=f"c{len(messages)}", function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=None, tool_calls=[tc]))], usage=None)

litellm.completion = fake_completion
agent.run("http://127.0.0.1:8765/job.html")

log = [json.loads(l) for l in open(sorted((ROOT / "runs").glob("agent-*/actions.jsonl"))[-1], encoding="utf-8")]
verdicts = [(e["action"], e["verdict"]) for e in log if e["kind"] == "policy"]
assert ("check", "ask") in verdicts, "legal checkbox must ask the human"
assert sum(v == ("click", "forbidden") for v in verdicts) == 2, "alert 'Activer' AND final submit must be blocked"
assert any(e["kind"] == "set_checked" and e["wanted"] is False and e["after"] is False for e in log), "alert must be turned off"
assert log[-1]["result"]["status"] == "ready_for_review"
con = db.connect()
row = con.execute("SELECT * FROM applications").fetchone()
assert row["company"] == "ACME IA" and row["contract_type"] == "CDI"
assert row["contact_email"] == "recrutement@acme-ia.fr", row["contact_email"]   # filled by the regex backup
assert row["contact_phone"] == "01 23 45 67 89", row["contact_phone"]
assert row["status"] == "applied" and row["applied_at"], (row["status"], row["applied_at"])
assert "LangGraph" in row["description"]
db.add_relance(con, row["id"], "email", "test")
assert con.execute("SELECT relance_count FROM applications_overview").fetchone()[0] == 1
print("\nALL CHECKS PASSED")
