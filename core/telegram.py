"""
Telegram: the agent tells you when it needs you, and you can answer from your phone.

Setup (once): @BotFather -> /newbot -> token in .env (TELEGRAM_BOT_TOKEN=...), send any message to your bot,
then `python telegram_setup.py` (finds your chat id, writes TELEGRAM_CHAT_ID to .env, sends a test message).
Only messages from YOUR chat are read. Never raises: Telegram down = the agent goes on (terminal only).
"""

import json
import os
import time
import urllib.parse
import urllib.request

from core.config import CONFIG

API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")      # tests: a fake local server


def settings() -> dict:
    return CONFIG.get("telegram", {})


def token() -> str:
    return os.environ.get(settings().get("token_env", "TELEGRAM_BOT_TOKEN"), "")


def chat_id() -> str:
    return os.environ.get(settings().get("chat_env", "TELEGRAM_CHAT_ID"), "")


def enabled(kind: str = "") -> bool:
    s = settings()
    on = bool(s.get("enabled", True)) and bool(token()) and bool(chat_id())
    return on and (not kind or kind in s.get("notify", ["human", "needs_human", "report", "errors"]))


def _call(method: str, params: dict, timeout: float = 10) -> dict:
    url = f"{os.environ.get('TELEGRAM_API', API)}/bot{token()}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
        return json.loads(r.read().decode())


def send(text: str, kind: str = "human") -> bool:
    """Sends a message to your chat. False (silently) when disabled or Telegram is unreachable."""
    return send_message(text, kind) is not None


def send_message(text: str, kind: str = "human") -> int | None:
    """Like send(), but returns the message id (to recognise the replies TO this message), None if not sent."""
    if not enabled(kind):
        return None
    try:
        r = _call("sendMessage", {"chat_id": chat_id(), "text": text[:4000], "disable_web_page_preview": "true"})
        return (r.get("result") or {}).get("message_id", 0) if r.get("ok") else None
    except Exception as e:
        print(f"   (telegram: not sent: {type(e).__name__})")
        return None


def last_update_id() -> int:
    """Everything up to now is old: only replies sent AFTER a question count."""
    try:
        res = _call("getUpdates", {"offset": -1, "timeout": 0}).get("result", [])
        return res[-1]["update_id"] if res else 0
    except Exception:
        return 0


def poll_reply(after: int, wait: float = 2, reply_to: int | None = None, tag: str = "") -> tuple[int, str | None]:
    """(new offset, text of the first message from YOUR chat after `after`) -- None when nothing yet.
    Several agents ask at the same time: with reply_to / tag, only a Telegram REPLY to that question, or a message
    starting with the tag ("indeed: ok"), answers it -- a reply meant for another agent is ignored."""
    try:
        res = _call("getUpdates", {"offset": after + 1, "timeout": int(wait)}, timeout=wait + 10).get("result", [])
    except Exception:
        time.sleep(wait)
        return after, None
    shared = reply_to is not None or bool(tag)       # other agents read the same messages: never move past them
    start = after
    for u in res:
        after = max(after, u["update_id"])
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat_id()) or not msg.get("text"):
            continue
        text = msg["text"].strip()
        if reply_to is None and not tag:
            return after, text                          # one agent alone: any message answers
        if reply_to and (msg.get("reply_to_message") or {}).get("message_id") == reply_to:
            return after, text
        if tag and text.lower().startswith(tag.lower()):
            return after, text[len(tag):].lstrip(" :,-").strip()
    return (start if shared else after), None
