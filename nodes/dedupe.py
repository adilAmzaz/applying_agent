"""
DEDUPE node: "have I already handled this offer?" -- before the offer page is even opened.

Identity of an offer, kept in the database for every offer seen:
  platform + platform_id   (Indeed: the "jk" id; a platform without an id in its links: the link itself)
  url                      (the link)
  listing_title            (the title shown in the results list)
Rule (config.toml [dedupe]): SAME offer = same platform id (same link) AND same title.
Company is NOT used: two entities of a company posting the same job are two offers.
  - same link, same title, already judged/applied/skipped  -> skipped (no page opened, no LLM)
  - same link, title changed                               -> processed again (the offer was edited)
  - new link                                               -> processed
  - judge failed 3 times on it                             -> skipped
Disable with [dedupe] enabled = false (then every offer is re-read and RE-JUDGED: costs tokens).
"""

import re
import unicodedata

from core import db
from core.config import CONFIG

REPROCESS = {"new", "prefiltered"}      # statuses that are always processed again
MAX_JUDGE_ATTEMPTS = 3


def _norm(title: str | None) -> str:
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\s+-\s+indeed\.com$|\s+\|\s+linkedin$|\s+(with verification|avec verification)$", "", t)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def seen_before(con, url: str, listing_title: str) -> tuple[bool, str]:
    """(skip?, why). Called with the link and the title of a results card."""
    cfg = CONFIG.get("dedupe", {})
    if not cfg.get("enabled", True):
        return False, ""
    row = db.find(con, url)
    if row is None:
        return False, ""
    if row["status"] == "new" and (row["judge_attempts"] or 0) >= MAX_JUDGE_ATTEMPTS:
        return True, f"judge failed {MAX_JUDGE_ATTEMPTS} times (#{row['id']})"
    if row["status"] in db.APPLIED_STATUSES:       # already sent: never again, even if the title changed
        return True, f"already {row['status']} (#{row['id']}, id {row['job_key']})"
    if row["status"] in REPROCESS:
        return False, ""
    known = {_norm(t) for t in (row["listing_title"], row["title"]) if t}      # card title, page title
    if cfg.get("rejudge_if_title_changed", True) and known and _norm(listing_title) not in known:
        return False, f"title changed since #{row['id']}"
    return True, f"already {row['status']} (#{row['id']})"


def already_applied(con, app_id: int):
    """The row if this offer (same link) was already sent, else None. Used before ANY apply."""
    row = con.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    return row if row is not None and row["status"] in db.APPLIED_STATUSES else None


def _company(c: str | None) -> str:
    c = _norm(c)
    return " ".join(w for w in c.split() if w not in {"sas", "sa", "sarl", "group", "groupe", "france", "inc", "ltd"})


def _title(t: str | None) -> str:
    t = _norm(t)
    t = re.sub(r"\b(h f|f h|h f x|f h x|m f|f m|m w d|h f n|f h nb|h f nb|cdi|cdd|freelance)\b", " ", t)
    return " ".join(t.split())


def applied_elsewhere(con, app_id: int):
    """The row of the SAME job already sent through ANOTHER link (Indeed -> Free-Work, LinkedIn -> company
    site...): same company and same title (H/F, CDI... ignored). None if not found. Used before any apply."""
    row = con.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    if row is None or not _company(row["company"]):
        return None
    titles = {_title(t) for t in (row["title"], row["listing_title"]) if t} - {""}
    marks = ",".join("?" * len(db.APPLIED_STATUSES))
    for other in con.execute(f"SELECT * FROM applications WHERE id != ? AND status IN ({marks})",
                             (app_id, *db.APPLIED_STATUSES)):
        if _company(other["company"]) == _company(row["company"]) and \
                titles & ({_title(t) for t in (other["title"], other["listing_title"]) if t} - {""}):
            return other
    return None
