"""
Telegram with a FAKE Telegram API (no network): messages sent, answers from YOUR chat read, other chats ignored,
terminal answers still work, scan report summary sent, Telegram down = nothing breaks.
"""
import http.server
import json
import os
import threading
import time
import urllib.parse
from common import CONFIG, fresh
fresh("telegram")                                    # reports go to the test folder, not yours

SENT, UPDATES = [], []


class FakeTelegram(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        params = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
        method = self.path.rsplit("/", 1)[-1]
        assert self.path.startswith("/botTEST-TOKEN/"), self.path
        if method == "sendMessage":
            SENT.append(params)
            out = {"ok": True, "result": {"message_id": len(SENT)}}
        else:                                                    # getUpdates with Telegram's offset rules
            off = int(params.get("offset", 0))
            res = UPDATES[-1:] if off == -1 else [u for u in UPDATES if u["update_id"] >= off]
            out = {"ok": True, "result": res}
        body = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8781), FakeTelegram)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(TELEGRAM_API="http://127.0.0.1:8781", TELEGRAM_BOT_TOKEN="TEST-TOKEN", TELEGRAM_CHAT_ID="42")
CONFIG["telegram"] = {"enabled": True}
from core import human, telegram

UPDATES.append({"update_id": 1, "message": {"chat": {"id": 42}, "text": "old message"}})   # before the question


def reply_later(text, chat=42, delay=1.0):
    def go():
        time.sleep(delay)
        UPDATES.append({"update_id": UPDATES[-1]["update_id"] + 1, "message": {"chat": {"id": chat}, "text": text}})
    threading.Thread(target=go, daemon=True).start()


# 1) a question goes to Telegram; YOUR reply answers it (another chat is ignored; the old message too)
reply_later("I am someone else", chat=999, delay=0.5)
reply_later("2 ans", delay=1.5)
assert human.ask("Combien d'années de TypeScript ? > ") == "2 ans"
assert "Combien d'années de TypeScript" in SENT[0]["text"] and SENT[0]["chat_id"] == "42"
assert any("received: 2 ans" in m["text"] for m in SENT)

# 2) "ok" on Telegram = Enter (I did it in Chrome)
reply_later("ok")
assert human.ask(">>> HUMAN NEEDED: solve the captcha > ") == ""

# 3) the terminal still answers (first answer wins)
threading.Timer(0.5, lambda: human._lines.put("none")).start()
assert human.ask(">>> HUMAN NEEDED: captcha? > ") == "none"

# 3b) several agents ask at the same time: an answer goes ONLY to the agent it is addressed to
human.AGENT = "indeed"
def reply_to_later(text, reply_to=None, delay=1.0):
    def go():
        time.sleep(delay)
        m = {"chat": {"id": 42}, "text": text}
        if reply_to:
            m["reply_to_message"] = {"message_id": reply_to}
        UPDATES.append({"update_id": UPDATES[-1]["update_id"] + 1, "message": m})
    threading.Thread(target=go, daemon=True).start()
reply_to_later("ok", delay=0.5)                                   # plain "ok": for nobody in particular -> ignored
reply_to_later("linkedin: skip", delay=1.0)                       # for the linkedin agent -> ignored here
reply_to_later("indeed: none", delay=2.0)                         # for this agent
assert human.ask(">>> HUMAN NEEDED: captcha > ") == "none"
assert "[indeed]" in [m for m in SENT if "captcha" in m["text"]][-1]["text"]
n = len(SENT)
reply_to_later("skip", reply_to=n + 1, delay=1.0)                 # a swipe-reply to the question message itself
assert human.ask(">>> HUMAN NEEDED: login > ") == "skip"
human.AGENT = ""

# 4) end of scan: summary on Telegram
from nodes.notify import report
SENT.clear()
report([{"id": 7, "verdict": "high", "score": 91, "title": "AI Engineer", "company": "ACME", "url": "u", "reasons": [],
         "apply_status": "applied"},
        {"id": 8, "verdict": "maybe", "score": 55, "title": "ML Eng", "company": "Beta", "url": "u", "reasons": [],
         "apply_status": "needs_human"}], {"blocked_sources": "linkedin"}, "linkedin")
text = SENT[-1]["text"]
assert "Scan done — linkedin" in text and "1 applications sent" in text and "#8 needs_human" in text, text
assert "stopped: linkedin" in text and "91 AI Engineer | ACME" in text

# 5) only the kinds you chose ([telegram] notify)
CONFIG["telegram"]["notify"] = ["human"]
assert telegram.send("x", "report") is False and telegram.send("y", "human") is True
# 6) Telegram down: nothing breaks
os.environ["TELEGRAM_API"] = "http://127.0.0.1:9"                                    # nothing listens there
assert telegram.send("lost", "human") is False
print("\nALL TELEGRAM CHECKS PASSED")
