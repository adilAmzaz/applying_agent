"""
SQLite database of the offers the agent processed and the applications sent.

  applications : one row per offer (unique by platform + job id)
  relances     : one row per follow-up (relance) done on an application

File: jobs.db in the project folder (open it with DB Browser for SQLite, or `python jobs.py`).
"""

import json
import os
import re
import sqlite3
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DB_PATH = Path(os.environ.get("JOBS_DB") or Path(__file__).resolve().parent.parent / "jobs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL,            -- indeed, hellowork, wttj...
    job_key          TEXT NOT NULL,            -- platform job id (Indeed jk) or the URL
    url              TEXT NOT NULL,
    -- extracted from the offer --------------------------------------------
    title            TEXT,
    company          TEXT,
    location         TEXT,
    contract_type    TEXT,                     -- CDI, CDD, freelance, stage...
    remote           TEXT,                     -- on-site / hybrid / full remote
    salary           TEXT,
    experience_required TEXT,
    skills           TEXT,                     -- JSON list
    summary          TEXT,                     -- 2-3 lines written by the LLM
    description      TEXT,                     -- full text of the offer
    contact_name     TEXT,
    contact_email    TEXT,
    contact_phone    TEXT,
    -- application -----------------------------------------------------------
    -- judge (1 LLM call per offer) ----------------------------------------
    verdict          TEXT,                     -- high | maybe | low
    score            INTEGER,                  -- 0-100
    judge_reasons    TEXT,                     -- JSON list
    red_flags        TEXT,                     -- JSON list
    judged_at        TEXT,
    apply_kind       TEXT,                     -- easy (on the job board) | external (company site) | none
    external_url     TEXT,
    source           TEXT,                     -- which search found it
    decision         TEXT,                     -- your answer in review: apply | skip
    auto             INTEGER DEFAULT 0,        -- 1 = applied by scan.py without you
    status           TEXT NOT NULL DEFAULT 'new',
        -- new | prefiltered (free keywords) | judged | skipped (you said no) | ready_for_review
        -- | needs_human (login, account, question it could not answer) | applied | stuck
        -- | interview | rejected | offer | no_answer | closed (offer page gone / no longer accepting)
    applied_at       TEXT,                     -- ISO date when YOU clicked "Déposer"
    agent_summary    TEXT,                     -- what the agent filled (finish summary)
    notes            TEXT,
    model            TEXT,
    tokens_in        INTEGER DEFAULT 0,
    tokens_out       INTEGER DEFAULT 0,
    run_dir          TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (platform, job_key)
);

CREATE TABLE IF NOT EXISTS relances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    done_at         TEXT NOT NULL,             -- ISO date
    channel         TEXT,                      -- email, phone, linkedin, platform
    note            TEXT
);

-- alert emails already read by the email sources (never parsed twice)
CREATE TABLE IF NOT EXISTS mail_seen (
    message_id      TEXT PRIMARY KEY,
    source          TEXT,
    offers          INTEGER,
    seen_at         TEXT NOT NULL
);

-- one line per application with its follow-up info: what you look at day to day
DROP VIEW IF EXISTS applications_overview;
CREATE VIEW applications_overview AS
SELECT a.id, a.status, a.verdict, a.score, a.company, a.title, a.location, a.contract_type, a.apply_kind, a.applied_at,
       a.contact_email, a.contact_phone,
       COUNT(r.id)            AS relance_count,
       MAX(r.done_at)         AS last_relance_at,
       a.url
FROM applications a LEFT JOIN relances r ON r.application_id = a.id
GROUP BY a.id;
"""

# Columns the extractor is allowed to fill
OFFER_FIELDS = ["title", "company", "location", "contract_type", "remote", "salary",
                "experience_required", "skills", "summary", "contact_name",
                "contact_email", "contact_phone"]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or DB_PATH, timeout=60)      # several agents at once: a write waits, never fails
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


# Columns added after the first version: old jobs.db files get them automatically
NEW_COLUMNS = {"verdict": "TEXT", "score": "INTEGER", "judge_reasons": "TEXT", "red_flags": "TEXT",
               "judged_at": "TEXT", "apply_kind": "TEXT", "external_url": "TEXT", "source": "TEXT",
               "decision": "TEXT", "auto": "INTEGER DEFAULT 0",
               "listing_title": "TEXT",               # title as shown in the results list (dedupe compares it)
               "last_scan": "TEXT",                   # name of the last scan that processed it (reset last-scan)
               "judge_attempts": "INTEGER DEFAULT 0"}


def _migrate(con):
    have = {r[1] for r in con.execute("PRAGMA table_info(applications)")}
    for col, typ in NEW_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE applications ADD COLUMN {col} {typ}")
    # old keyword filter ('filtered'): let the judge see those offers
    con.execute("UPDATE applications SET status='new' WHERE status='filtered'")
    con.commit()


def job_identity(url: str) -> tuple[str, str]:
    """(platform, job_key): the same offer opened from different links gets the same key."""
    host = urlparse(url).netloc.lower()
    q = parse_qs(urlparse(url).query)
    if "indeed." in host:
        jk = (q.get("jk") or q.get("vjk") or [None])[0]
        return "indeed", jk or url
    if "linkedin." in host:                          # /jobs/view/4012345678/ or ?currentJobId=4012345678
        m = re.search(r"/jobs/view/(?:[^/?]*-)?(\d{6,})", url)
        jid = m.group(1) if m else (q.get("currentJobId") or [None])[0]
        return "linkedin", jid or url.split("?")[0]
    if "welcometothejungle." in host:               # /fr/companies/<company>/jobs/<job-slug> (no numeric id)
        m = re.search(r"/companies/([^/?#]+)/jobs/([^/?#]+)", urlparse(url).path)
        if m:
            return "wttj", f"{m.group(1)}/{m.group(2)}"
    if "hellowork." in host:                        # /fr-fr/emplois/<id>.html
        m = re.search(r"/emplois/(\d{5,})\.html", url)
        if m:
            return "hellowork", m.group(1)
    if "free-work." in host:                        # /fr/tech-it/job-mission/<category>/<slug>
        m = re.search(r"/job-mission/[^/?#]+/([^/?#]+)", url)
        if m:
            return "freework", m.group(1)
    for name in ("malt", "free-work"):
        if name in host:
            return name, url.split("?")[0]
    return host or "other", url.split("?")[0].split("#")[0].rstrip("/")     # "/x" and "/x/": the same page


def find(con, url: str):
    platform, key = job_identity(url)
    return con.execute("SELECT * FROM applications WHERE platform=? AND job_key=?",
                       (platform, key)).fetchone()


# Statuses meaning "you already sent this application"
APPLIED_STATUSES = ("applied", "interview", "rejected", "offer", "no_answer")


def save_judgment(con, app_id: int, j: dict):
    update(con, app_id, verdict=j.get("verdict"), score=j.get("score"),
           judge_reasons=json.dumps(j.get("reasons") or [], ensure_ascii=False),
           red_flags=json.dumps(j.get("red_flags") or [], ensure_ascii=False),
           judged_at=now(), status="judged")


def pending_review(con, verdicts=("high", "maybe")):
    q = ",".join("?" * len(verdicts))
    return con.execute(f"SELECT * FROM applications WHERE status='judged' AND verdict IN ({q}) "
                       "ORDER BY score DESC, id", tuple(verdicts)).fetchall()


def upsert_offer(con, url: str, offer: dict, description: str) -> int:
    """Insert the offer, or refresh its extracted fields. Never touches status/applied_at."""
    platform, key = job_identity(url)
    fields = {k: offer.get(k) for k in OFFER_FIELDS}
    if isinstance(fields["skills"], (list, tuple)):
        fields["skills"] = json.dumps(fields["skills"], ensure_ascii=False)
    row = find(con, url)
    if row:
        # keep existing values when the new extraction is empty
        sets = {k: v for k, v in fields.items() if v not in (None, "", "[]")}
        sets.update(description=description or row["description"], updated_at=now())
        con.execute(f"UPDATE applications SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                    (*sets.values(), row["id"]))
        con.commit()
        return row["id"]
    cols = dict(platform=platform, job_key=key, url=url, description=description,
                created_at=now(), updated_at=now(), **fields)
    cur = con.execute(f"INSERT INTO applications ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                      tuple(cols.values()))
    con.commit()
    return cur.lastrowid


def update(con, app_id: int, **fields):
    fields["updated_at"] = now()
    con.execute(f"UPDATE applications SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), app_id))
    con.commit()


def mark_applied(con, app_id: int, when: str | None = None):
    update(con, app_id, status="applied", applied_at=when or date.today().isoformat())


def add_relance(con, app_id: int, channel: str = "", note: str = "", when: str | None = None) -> int:
    cur = con.execute("INSERT INTO relances (application_id, done_at, channel, note) VALUES (?,?,?,?)",
                      (app_id, when or date.today().isoformat(), channel, note))
    update(con, app_id)
    return cur.lastrowid


def relances_due(con, days: int = 7):
    """Applied more than `days` ago, still waiting, and no follow-up in the last `days` days."""
    return con.execute("""
        SELECT * FROM applications_overview
        WHERE status = 'applied'
          AND julianday('now') - julianday(applied_at) >= ?
          AND (last_relance_at IS NULL OR julianday('now') - julianday(last_relance_at) >= ?)
        ORDER BY applied_at""", (days, days)).fetchall()


# ---------------------------------------------------------------- contacts (regex)
# Deterministic backup for the LLM: an email/phone written in the offer is never missed.
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?:\+33\s?|0033\s?|\b0)[1-9](?:[\s.-]?\d{2}){4}\b")
IGNORED_EMAIL = re.compile(r"noreply|no-reply|donotreply|example\.|indeed\.com|sentry", re.I)


def find_contacts(text: str) -> dict:
    emails = [e for e in dict.fromkeys(EMAIL_RE.findall(text or "")) if not IGNORED_EMAIL.search(e)]
    phones = list(dict.fromkeys(m.group(0).strip() for m in PHONE_RE.finditer(text or "")))
    return {"contact_email": ", ".join(emails) or None, "contact_phone": ", ".join(phones) or None}
