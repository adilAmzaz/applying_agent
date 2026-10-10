"""Loads config.toml once. Everything else imports CONFIG from here."""

import os
try:
    import tomllib                      # Python 3.11+
except ImportError:                     # Python 3.10: pip install tomli
    import tomli as tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("JOBAGENT_CONFIG") or ROOT / "config.toml")


# provider (start of the model name) -> the API key variable LiteLLM uses. Put the keys in .env
KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY",
           "mistral": "MISTRAL_API_KEY", "groq": "GROQ_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
           "openrouter": "OPENROUTER_API_KEY", "xai": "XAI_API_KEY", "together_ai": "TOGETHERAI_API_KEY",
           "cohere": "COHERE_API_KEY", "azure": "AZURE_API_KEY"}


def load_env_file(path: Path = ROOT / ".env"):
    """Secrets (API keys, mail app password) in a .env file next to config.toml: KEY=value per line.
    API keys (*_API_KEY, *_API_BASE): the .env value WINS over the shell (one place for all keys).
    Other variables: never override one already set. Empty values are ignored. Keep .env out of git."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
            if not v:
                continue
            if k.endswith(("_API_KEY", "_API_BASE", "_API_VERSION")):
                os.environ[k] = v
            else:
                os.environ.setdefault(k, v)


def key_env(model: str) -> str | None:
    """'openai/gpt-6-luna' -> 'OPENAI_API_KEY' (None: local model, e.g. ollama)."""
    return KEY_ENV.get(model.split("/", 1)[0]) if "/" in model else "OPENAI_API_KEY"


load_env_file()


def load(path: Path = CONFIG_PATH) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    llm = cfg.setdefault("llm", {})
    if os.environ.get("MODEL"):                     # quick override from the command line
        llm["model"] = os.environ["MODEL"]
    llm["judge_model"] = os.environ.get("JUDGE_MODEL") or llm.get("judge_model") or llm["model"]
    # fallbacks, in order: used when the model keeps failing (outage, bad key, model removed)
    chain = [llm.get("fallback_model_1") or llm.get("fallback_model"), llm.get("fallback_model_2")]
    llm["fallbacks"] = [m for m in chain if m]
    llm["fallback_model"] = llm["fallbacks"][0] if llm["fallbacks"] else llm["model"]
    return cfg


CONFIG = load()


def read_text(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""
