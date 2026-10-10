"""
Default account for recruitment sites (config.toml [accounts]): the email of profile.json identity (or
[accounts] email) and a password read from the environment / .env (JOBAGENT_ACCOUNT_PASSWORD).

The password is never written to a file by the agent, never shown to the LLM, never logged: the fill_password
tool types it directly into the password field. accounts.json (next to config.toml) only lists the sites where
an account was created / used, so the agent knows "log in" vs "create".
"""

import json
import os
from datetime import date

from core.config import CONFIG, ROOT

PATH = ROOT / "accounts.json"
# Sites where YOU logged in with another password than the default one: saved only when you type it yourself in
# the terminal (hidden), never shown to the AI, never logged, never sent to Telegram. Local file, keep it private.
SECRETS = ROOT / ".site_passwords.json"


def settings() -> dict:
    return CONFIG.get("accounts", {})


def enabled() -> bool:
    return bool(settings().get("enabled")) and bool(password())


def password() -> str:
    return os.environ.get(settings().get("password_env", "JOBAGENT_ACCOUNT_PASSWORD"), "")


def email(profile: dict) -> str:
    return settings().get("email") or (profile.get("identity") or {}).get("email", "")


def known_sites() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember(site: str, what: str, login: str = "", url: str = ""):
    """accounts.json: one entry per site -> the login email, when it was created / last used, what happened.
    The password is NEVER written: it is the same for every site (.env JOBAGENT_ACCOUNT_PASSWORD)."""
    data = known_sites()
    today = date.today().isoformat()
    e = data.get(site) or {"first_seen": today}
    e.update(last=what, date=today)
    if login:
        e["login"] = login
    if url:
        e["url"] = url[:200]
    if what == "account created" and "created" not in e:
        e["created"] = today
    e["history"] = (e.get("history") or [])[-9:] + [f"{today} {what}"]
    data[site] = e
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _secrets() -> dict:
    try:
        return json.loads(SECRETS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def password_for(site: str) -> str:
    """The password to type on this site: the one you saved for it, else the default one (.env)."""
    return _secrets().get(site) or password()


def save_login(site: str, login: str, pw: str = ""):
    """You logged in by hand: remember the login (accounts.json) and, if you typed one, this site's own password
    (.site_passwords.json, not accounts.json). Empty password = the default one from .env is used here."""
    remember(site, "logged in by you", login)
    if pw and pw != password():
        data = _secrets()
        data[site] = pw
        SECRETS.write_text(json.dumps(data, indent=1), encoding="utf-8")
        try:
            os.chmod(SECRETS, 0o600)
        except OSError:
            pass
