"""
Provider outage (OpenAI InternalServerError on every call): after the retries the LLM is paused for a few
minutes (each next offer fails at once instead of 75 s of retries) and the offers do NOT lose a judge attempt.
"""
import time
import litellm
from common import fresh
from core import db, llm
from nodes import store

calls = []


def down(**kw):
    calls.append(kw["model"])
    raise litellm.InternalServerError("boom", llm_provider="openai", model=kw["model"])


litellm.completion = down
llm.time.sleep = lambda s: None                       # no real waiting in the test
con = fresh("llm-down")
from core.config import CONFIG as _C
_C["llm"]["fallbacks"] = []
try:
    llm.call([{"role": "user", "content": "x"}])
    raise AssertionError("should fail")
except llm.LLMDown:
    pass
n = len(calls)
assert n == llm.NUM_RETRIES + 1, calls
t0 = time.time()
try:
    llm.call([{"role": "user", "content": "x"}])        # paused: no call, immediate failure
except llm.LLMDown as e:
    assert "paused" in str(e)
assert len(calls) == n and time.time() - t0 < 1

U = "https://www.example.com/job/1"
app_id = db.upsert_offer(con, U, {"title": "AI Engineer"}, "desc")
store.save_judgment(con, app_id, {"verdict": None, "error": "LLMDown: LLM still failing after 4 retries"})
assert (db.find(con, U)["judge_attempts"] or 0) == 0                     # outage: attempt not counted
store.save_judgment(con, app_id, {"verdict": None, "error": "JSONDecodeError: bad output"})
assert db.find(con, U)["judge_attempts"] == 1                            # a real failure still counts

# fallbacks: the model is down, fallback 1 has no key in .env (skipped), fallback 2 answers
import os
from core.config import CONFIG
llm._down_until[0] = 0
CONFIG["llm"]["fallbacks"] = ["anthropic/claude-haiku-4-5", "gemini/gemini-3.8-flash"]
os.environ.pop("ANTHROPIC_API_KEY", None)
calls.clear()


def chain(**kw):
    calls.append((kw["model"], kw.get("api_key")))
    if kw["model"].startswith("openai/"):
        raise litellm.InternalServerError("boom", llm_provider="openai", model=kw["model"])
    return "ok"


litellm.completion = chain
os.environ["GEMINI_API_KEY"] = "gem-key"
resp, used = llm.call([{"role": "user", "content": "x"}], model="openai/gpt-6-luna")
assert resp == "ok" and used == "gemini/gemini-3.8-flash", (resp, used)
assert [c[0] for c in calls] == ["openai/gpt-6-luna"] * llm.TRIES_PER_MODEL + ["gemini/gemini-3.8-flash"], calls
assert calls[-1][1] == "gem-key"                                               # the key from the environment (.env)

# no request can hang forever: every call carries a timeout (a Timeout = an outage, next model)
assert llm._kwargs("openai/gpt-6-luna", [], None, {})["timeout"] == 120.0

# .env: API keys win over the shell, empty values are ignored, other variables never overridden
from core.config import load_env_file
from common import TMP
env = TMP / "test.env"
env.write_text("OPENAI_API_KEY=from-env-file\nGEMINI_API_KEY=\nJOBAGENT_X=file\n", encoding="utf-8")
os.environ.update(OPENAI_API_KEY="from-shell", GEMINI_API_KEY="gem-shell", JOBAGENT_X="shell")
load_env_file(env)
assert os.environ["OPENAI_API_KEY"] == "from-env-file" and os.environ["GEMINI_API_KEY"] == "gem-shell"
assert os.environ["JOBAGENT_X"] == "shell"
CONFIG["llm"]["fallbacks"] = []
print("\nALL LLM CHECKS PASSED")
