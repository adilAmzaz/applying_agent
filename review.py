"""
Review what the scan found (you are here): high first, then maybe. Apply / skip / later.

  python review.py                      # high + maybe, one by one: you decide
  python review.py high                 # only high
  python review.py --apply high,maybe   # apply to ALL pending high + maybe offers, until sent, you watching
                                        # (captchas / logins / unknown questions asked here)
  python review.py --apply high --max 5
"""

import sys

from playwright.sync_api import sync_playwright

from core import llm
from core.browser import SessionPool
from core.config import CONFIG
from graphs.review import run_auto, run_review


def full_apply(levels):
    """--apply: apply until sent, accepting the legal boxes, you watching."""
    CONFIG["auto_apply"].update(enabled=True, verdicts=levels, submit=True, approve_legal=True, supervised=True)


if __name__ == "__main__":
    args, levels, limit, rest = sys.argv[1:], None, None, []
    i = 0
    while i < len(args):
        if args[i] == "--apply":
            has_value = i + 1 < len(args) and not args[i + 1].startswith("--")
            levels = tuple(args[i + 1].split(",")) if has_value else ("high",)
            i += 2 if has_value else 1
        elif args[i] == "--max":
            limit, i = int(args[i + 1]), i + 2
        else:
            rest.append(args[i])
            i += 1
    llm.check_server()
    with sync_playwright() as p:
        s = SessionPool(p)               # each offer in the Chrome of its site's agent
        if levels:
            full_apply(list(levels))
            from core import human
            run_auto(s, ask=human.ask, verdicts=levels, limit=limit)        # terminal or Telegram
        else:
            run_review(s, verdicts=tuple(rest) or ("high", "maybe"))
        s.close()
