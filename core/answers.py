"""
Answers you gave to the apply agent (ask_human) are written INTO profile.json, section "answers_given".
The next applications read them with the rest of the profile: the same question is never asked twice.
Edit them in profile.json like any other field (wrong answer -> fix or delete the line).
"""

import json
import re
import unicodedata
from datetime import date

from core.config import ROOT

PATH = ROOT / "profile.json"
OLD = ROOT / "answers.json"                     # first version: merged into the profile, then renamed
SECTION = "answers_given"


def _key(q: str) -> str:
    q = unicodedata.normalize("NFKD", q).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", q).split())[:200]


def _read() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load() -> dict:
    """{question: answer} given so far."""
    return dict(_read().get(SECTION, {}))


def remember(question: str, answer: str):
    profile = _read()
    if not profile and PATH.exists():           # unreadable profile: never overwrite it
        return
    given = profile.setdefault(SECTION, {})
    q = question.strip()[:300]
    for old in [k for k in given if _key(k) == _key(q)]:
        del given[old]
    given[q] = answer.strip()[:500]
    PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def migrate_old_file():
    """answers.json (first version) -> profile.json answers_given; the old file is renamed .merged."""
    if not OLD.exists():
        return 0
    try:
        old = json.loads(OLD.read_text(encoding="utf-8"))
    except ValueError:
        return 0
    for item in old.values():
        remember(item["question"], item["answer"])
    OLD.rename(OLD.with_suffix(".json.merged"))
    return len(old)


def for_prompt(limit: int = 40) -> str:
    items = list(load().items())[-limit:]
    return "\n".join(f"- Q: {q}\n  A: {a}" for q, a in items)
