"""One function to call any LLM (LiteLLM): retries, fallback model, provider quirks."""

import json
import os
import sys
import time

import litellm

from core.config import CONFIG, key_env

litellm.suppress_debug_info = True          # no "Give Feedback / Get Help" banners
litellm.drop_params = True                  # silently drop params a provider doesn't support

NUM_RETRIES = int(os.environ.get("NUM_RETRIES", "4"))       # tries on ONE model (when it has no fallback)
TRIES_PER_MODEL = int(os.environ.get("TRIES_PER_MODEL", "2"))  # with fallbacks: 2 tries, then the next model
SKIP_MODEL_ERRORS = tuple(e for e in (                     # this model cannot work now: next one at once
    litellm.AuthenticationError, litellm.NotFoundError, getattr(litellm, "PermissionDeniedError", None)) if e)
_warned: set = set()
TRANSIENT_ERRORS = tuple(e for e in (
    litellm.RateLimitError, litellm.ServiceUnavailableError, litellm.InternalServerError,
    litellm.APIConnectionError, litellm.Timeout,
    getattr(litellm, "BadGatewayError", None)) if e)
_last_call = [0.0]
DOWN_PAUSE = int(os.environ.get("LLM_DOWN_PAUSE", "300"))
_down_until = [0.0]                         # provider down (all retries failed): no call before this time


class LLMDown(RuntimeError):
    """The provider keeps failing (5xx / 429 / network): an outage, not a problem with the offer."""


def has_key(model: str) -> bool:
    var = key_env(model)
    return var is None or bool(os.environ.get(var))


def _kwargs(model: str, messages, tools, extra) -> dict:
    kw = dict(model=model, messages=messages, **extra)
    if (var := key_env(model)) and os.environ.get(var):
        kw["api_key"] = os.environ[var]          # the key from .env (core/config.load_env_file)
    if tools:
        kw.update(tools=tools, tool_choice="auto")
    if not model.startswith(("ollama/", "ollama_chat/")):
        kw["timeout"] = float(CONFIG["llm"].get("timeout_seconds", 120))   # a hung request never freezes the agent
    if model.startswith(("anthropic/", "ollama/", "ollama_chat/")):
        kw["temperature"] = 0                # Gemini 3+ / OpenAI GPT-5+ reject custom temperature
    if model.startswith(("ollama/", "ollama_chat/")):
        kw["num_ctx"] = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))   # default context is too small
        kw["timeout"] = 900
        if os.environ.get("OLLAMA_API_BASE"):                             # e.g. Kaggle behind a tunnel
            kw["api_base"] = os.environ["OLLAMA_API_BASE"].rstrip("/")
        if os.environ.get("OLLAMA_THINK"):
            kw["think"] = os.environ["OLLAMA_THINK"].lower() == "true"
    return kw


def chain_for(model: str) -> list[str]:
    """The model, then [llm] fallback_model_1, fallback_model_2 (without duplicates)."""
    out = []
    for m in [model] + list(CONFIG["llm"].get("fallbacks") or []):
        if m and m not in out:
            out.append(m)
    return out


def call(messages, model: str | None = None, tools=None, **extra):
    """Returns (response, model_used). Each model: retries on 429/5xx with backoff, then the next fallback.
    A model without its API key in .env (or with a bad key / removed model) is skipped at once."""
    model = model or CONFIG["llm"]["model"]
    if time.time() < _down_until[0]:            # outage: fail at once instead of minutes of retries per offer
        left = int(_down_until[0] - time.time())
        raise LLMDown(f"LLM still failing (all models down, paused {left}s more)")
    gap = float(CONFIG["llm"].get("min_seconds_between_calls", 0))
    chain = chain_for(model)
    tries = NUM_RETRIES + 1 if len(chain) == 1 else TRIES_PER_MODEL
    last = None
    for m in chain:
        if not has_key(m):
            if m not in _warned:
                _warned.add(m)
                print(f"   ! {m}: no {key_env(m)} in .env -> skipped")
            last = last or f"no {key_env(m)}"
            continue
        for attempt in range(tries):
            wait = gap - (time.time() - _last_call[0])
            if wait > 0:
                time.sleep(wait)                 # free tiers: N requests per minute
            _last_call[0] = time.time()
            try:
                return litellm.completion(**_kwargs(m, messages, tools, extra)), m
            except SKIP_MODEL_ERRORS as e:
                print(f"   ! {type(e).__name__} on {m} (key / model): next model")
                last = type(e).__name__
                break
            except TRANSIENT_ERRORS as e:
                last = type(e).__name__
                if attempt == tries - 1:
                    print(f"   ! {type(e).__name__} on {m}: giving up on it"
                          + (", next model" if m != chain[-1] else ""))
                    break
                pause = min(60, 5 * 2 ** attempt)
                print(f"   ! {type(e).__name__} on {m}: retry in {pause}s")
                time.sleep(pause)
    _down_until[0] = time.time() + DOWN_PAUSE
    print(f"   ! all models down ({', '.join(chain)}): no LLM call for {DOWN_PAUSE // 60} min "
          "(offers stay 'new', judged next scan)")
    raise LLMDown(f"LLM still failing on {', '.join(chain)}: {last}")


def usage_of(resp) -> dict:
    u = getattr(resp, "usage", None)
    return {"in": (u.prompt_tokens or 0) if u else 0, "out": (u.completion_tokens or 0) if u else 0}


def parse_json(content: str) -> dict:
    """Tolerates ```json fences and text around the object."""
    content = content or "{}"
    return json.loads(content[content.find("{"): content.rfind("}") + 1])


def check_server(model: str | None = None):
    """Ollama only: is the server up and does it have the model? (other providers: nothing to check)"""
    model = model or CONFIG["llm"]["model"]
    if not model.startswith(("ollama/", "ollama_chat/")):
        return
    import urllib.request
    base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434").rstrip("/")
    name = model.split("/", 1)[1]
    try:
        tags = json.load(urllib.request.urlopen(base + "/api/tags", timeout=15))
    except Exception as e:
        sys.exit(f"\nOllama not reachable at {base} ({getattr(e, 'code', '') or type(e).__name__}).\n"
                 "  Kaggle: notebook running? 'ollama serve' alive? new trycloudflare URL in OLLAMA_API_BASE?")
    names = [m["name"] for m in tags.get("models", [])]
    if name not in names:
        sys.exit(f"\nModel '{name}' not on {base}. Available: {names}\n  -> ollama pull {name}")
