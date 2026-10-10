"""
Shared by the email sources: read job-alert emails from your mailbox (IMAP, READ-ONLY).

  - the mailbox is opened read-only: nothing is marked read, moved or deleted
  - each email is parsed once (table mail_seen); emails older than [email] since_days are ignored
  - the password is NOT in config.toml: a Gmail "app password" in the environment variable named by
    [email] password_env (Google account -> Security -> 2-step verification -> App passwords)

Tests replace fetch_messages() by fixtures: no network.
"""

import email
import email.message
import email.policy
import html
import imaplib
import os
import re
from datetime import date, timedelta

from core import db
from core.config import CONFIG


class MailError(RuntimeError):
    pass


def fetch_messages(senders: list[str]) -> list[dict]:
    """[{message_id, subject, sender, text}] of the emails from these senders since [email] since_days."""
    cfg = CONFIG.get("email", {})
    password = os.environ.get(cfg.get("password_env", "JOBAGENT_MAIL_PASSWORD"), "")
    if not cfg.get("address") or not password:
        raise MailError(f"email sources: set [email] address and the app password in ${cfg.get('password_env')}")
    since = (date.today() - timedelta(days=int(cfg.get("since_days", 7)))).strftime("%d-%b-%Y")
    out = []
    try:
        box = imaplib.IMAP4_SSL(cfg.get("imap_host", "imap.gmail.com"))
        box.login(cfg["address"], password)
        box.select(cfg.get("folder", "INBOX"), readonly=True)
        nums = []
        for sender in senders:
            # FROM: the alert itself (or an automatic Gmail forward, which keeps the sender)
            # BODY: alerts forwarded BY HAND, as attachments (.eml) or quoted in the body
            typ, data = box.search(None, "SINCE", since, "OR", "FROM", f'"{sender}"', "BODY", f'"{sender}"')
            nums += [n for n in (data[0].split() if typ == "OK" else []) if n not in nums]
        for fwd in cfg.get("forwarded_from", []):
            # alerts forwarded by hand as attachments: Gmail does not search inside attachments,
            # so read every email from these addresses; messages_in() keeps only the alerts inside
            typ, data = box.search(None, "SINCE", since, "FROM", f'"{fwd}"')
            nums += [n for n in (data[0].split() if typ == "OK" else []) if n not in nums]
        for num in nums:
            typ, msg = box.fetch(num, "(BODY.PEEK[])")              # PEEK: not marked as read
            if typ == "OK" and msg and isinstance(msg[0], tuple):
                out += messages_in(msg[0][1], senders)
        box.logout()
    except (imaplib.IMAP4.error, OSError) as e:
        raise MailError(f"mailbox: {e}")
    return out


def messages_in(raw: bytes, senders: list[str]) -> list[dict]:
    """The alert emails inside one email: itself, or the alerts it carries as attachments
    (several alerts forwarded together as .eml files). Only emails from these senders."""
    m = email.message_from_bytes(raw, policy=email.policy.default)
    inner = [p.get_content() for p in m.walk() if p.get_content_type() == "message/rfc822"]
    out = []
    for msg in inner:
        if not isinstance(msg, email.message.Message):
            continue
        d = parse_raw(msg.as_bytes())
        if _from_sender(d["sender"], senders):
            d["message_id"] = d["message_id"] or f"{m['Message-ID']}#{len(out)}"
            out.append(d)
    if inner:
        return out
    d = parse_raw(raw)
    # quoted forward (no attachment): the original sender is only in the text
    return [d] if _from_sender(d["sender"], senders) or any(s.lower() in d["text"].lower() for s in senders) else []


def _from_sender(sender: str, senders: list[str]) -> bool:
    return any(s.lower() in sender.lower() for s in senders)


def parse_raw(raw: bytes) -> dict:
    m = email.message_from_bytes(raw, policy=email.policy.default)
    part = m.get_body(preferencelist=("plain",))
    if part is not None:
        text = part.get_content()
    else:
        h = m.get_body(preferencelist=("html",))
        text = html_to_text(h.get_content() if h is not None else "")
    return {"message_id": (m["Message-ID"] or "").strip() or f"{m['Date']}|{m['Subject']}",
            "subject": str(m["Subject"] or ""), "sender": str(m["From"] or ""), "text": text}


def html_to_text(h: str) -> str:
    """HTML-only email -> text where each link is written 'text' then the URL on its own line."""
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: f"{m.group(2)}\n{m.group(1)}\n", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return "\n".join(" ".join(l.split()) for l in t.splitlines())


# account / application emails from the same senders: not job alerts
NOT_ALERT = re.compile(r"profil|password|mot de passe|bienvenue|welcome to|confirm|v[ée]rifi|s[ée]curit|"
                       r"candidature (envoy|re[çc]u)|application (sent|received)|votre candidature|your application|"
                       r"alerte emploi .* (est )?maintenant active|is now active|newsletter|facture|invoice", re.I)


def new_messages(con, source_name: str, senders: list[str]) -> list[dict]:
    """Messages never parsed before (mail_seen), job alerts only."""
    msgs = [m for m in fetch_messages(senders) if not NOT_ALERT.search(m.get("subject", ""))]
    seen = {r[0] for r in con.execute("SELECT message_id FROM mail_seen")}
    return [m for m in msgs if m["message_id"] not in seen]


def mark_seen(con, done: list):
    """done = [(message_id, source, offers)] -- called at the end of the scan."""
    con.executemany("INSERT OR IGNORE INTO mail_seen (message_id, source, offers, seen_at) VALUES (?,?,?,?)",
                    [(mid, src, n, db.now()) for mid, src, n in done])
    con.commit()


def blocks_before_links(text: str, link_re: re.Pattern, sep_re: re.Pattern | None = None,
                        last_paragraph: bool = False) -> list[tuple[str, list]]:
    """[(link, lines of the offer)]: for each job link, the lines between the previous job link and it.
    sep_re: a separator line that starts a new offer ("-----" in LinkedIn emails).
    last_paragraph: keep only the lines after the last empty line (Indeed: one paragraph per offer)."""
    out, block = [], []
    for raw in text.splitlines():
        line = raw.strip()
        m = link_re.search(line)
        if m:
            label = line[:m.start()].strip().rstrip(":").strip()      # "Voir l'offre : https://..." -> "Voir l'offre"
            out.append((m.group(0), [l for l in block + [label] if l]))
            block = []
            continue
        if (sep_re and sep_re.match(line)) or re.search(r"https?://", line):
            block = []                              # separator, or another link (search page, footer...)
            continue
        if last_paragraph and not line:
            block = []
            continue
        block.append(line)
    return out
