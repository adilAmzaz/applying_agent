"""
How the agent asks YOU something (supervised runs): in the terminal AND on Telegram (if set up).
The first answer wins: type it in the terminal, or reply to the bot from your phone.
  Telegram reply "ok" / "fait" / "done" = Enter (I did it in Chrome);  "none" / "skip" work as in the terminal.
"""

import queue
import sys
import threading

from core import telegram

_lines: "queue.Queue[str]" = queue.Queue()
_reader = None
AGENT = ""          # set by the scan (agent name): with several agents, a Telegram answer must name / reply to it


def _read_stdin():
    for line in sys.stdin:                         # one reader for the whole run: no lost / stolen lines
        _lines.put(line.rstrip("\n"))


def ask(prompt: str) -> str:
    """The answer, from the terminal or Telegram (whichever comes first)."""
    global _reader
    if not telegram.enabled("human"):
        return input(prompt)
    print(prompt, end="", flush=True)
    offset = telegram.last_update_id()
    text = prompt.replace("\a", "").strip()
    if AGENT:                                       # several agents may be waiting: answers must be addressed
        msg_id = telegram.send_message(f"🙋 [{AGENT}] " + text + f"\n\n↩️ REPLY to this message (swipe it) or start "
                                       f"with \"{AGENT}:\" -- e.g. \"{AGENT}: ok\" / none / skip", "human")
    else:
        msg_id = telegram.send_message("🙋 " + text + "\n\n(reply: your answer, or ok / none / skip)", "human")
    if _reader is None:
        _reader = threading.Thread(target=_read_stdin, daemon=True)
        _reader.start()
    while True:
        try:
            line = _lines.get(timeout=0.2)
            print()
            return line
        except queue.Empty:
            pass
        if AGENT:
            offset, reply = telegram.poll_reply(offset, wait=2, reply_to=msg_id or None, tag=AGENT)
        else:
            offset, reply = telegram.poll_reply(offset, wait=2)
        if reply is not None:
            print(f"{reply}   (answered on Telegram)")
            telegram.send(f"✓ {'[' + AGENT + '] ' if AGENT else ''}received: {reply[:100]}", "human")
            low = reply.strip().lower()
            return "" if low in ("ok", "fait", "done", "c'est fait", "go", "continue", "continuer") else reply
