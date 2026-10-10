"""
Telegram setup, once:
  1. In Telegram, talk to @BotFather (blue check, exact spelling): /newbot -> a name -> a TOKEN.
  2. Put it in .env:   TELEGRAM_BOT_TOKEN=123456:ABC...
  3. python telegram_setup.py   -> it shows which bot the token is, then waits for a message:
     open THAT bot in Telegram and send it "hello". It saves TELEGRAM_CHAT_ID in .env and sends a test message.
"""
import os
import sys
import time

from core import telegram
from core.config import ROOT

if not telegram.token():
    sys.exit(__doc__ + "\n-> TELEGRAM_BOT_TOKEN is not in .env yet (step 2).")
try:
    me = telegram._call("getMe", {}).get("result", {})
except Exception as e:
    sys.exit(f"Telegram refuses this token ({e}). Copy it again from @BotFather into .env (no spaces, no quotes).")
print(f"The token is the bot: {me.get('first_name')}  @{me.get('username')}   https://t.me/{me.get('username')}")

hook = telegram._call("getWebhookInfo", {}).get("result", {})
if hook.get("url"):
    telegram._call("deleteWebhook", {})
    print("A webhook was set on this bot (it hides the messages): removed.")


def find_chat():
    for u in telegram._call("getUpdates", {"timeout": 0}).get("result", []):
        chat = (u.get("message") or u.get("edited_message") or {}).get("chat") or {}
        if chat.get("type") == "private" and chat.get("id"):
            return chat["id"], chat.get("first_name", "")
    return None


found = find_chat()
if not found:
    print(f"\nNo message yet. In Telegram open @{me.get('username')} (link above) and send it: hello")
    print("Waiting up to 2 minutes...", flush=True)
    for _ in range(24):
        time.sleep(5)
        found = find_chat()
        if found:
            break
if not found:
    sys.exit(f"Still no message for @{me.get('username')}. Check that you write to THIS bot (the name above), "
             "not another one, then run again.")
chat_id, name = found
env = ROOT / ".env"
text = env.read_text(encoding="utf-8") if env.exists() else ""
lines = [l for l in text.splitlines() if not l.startswith("TELEGRAM_CHAT_ID=")] + [f"TELEGRAM_CHAT_ID={chat_id}"]
env.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.environ["TELEGRAM_CHAT_ID"] = str(chat_id)
ok = telegram.send("✅ Job agent connected. I will write here when I need you.", "human")
print(f"Chat id {chat_id} ({name}) saved in .env. Test message: {'sent, check Telegram' if ok else 'NOT sent'}")
