"""
Apply to ONE offer by URL (interactive), outside of scan/review.

  python apply_one.py "https://fr.indeed.com/viewjob?jk=..."
  python apply_one.py "https://www.linkedin.com/jobs/view/4012345678/"
"""

import sys
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

from core import db, llm
from core.browser import SessionPool
from core.config import ROOT
from graphs.review import apply_now
from nodes import store
from nodes.read import read_offer


def normalize(url: str) -> str:
    q = parse_qs(urlparse(url).query)
    if "indeed." in url and "/viewjob" not in url and q.get("vjk"):
        return f"https://fr.indeed.com/viewjob?jk={q['vjk'][0]}"
    if "linkedin." in url and q.get("currentJobId"):            # link copied from a LinkedIn search page
        return f"https://www.linkedin.com/jobs/view/{q['currentJobId'][0]}/"
    return url


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url = normalize(sys.argv[1])
    llm.check_server()
    con = db.connect()
    with sync_playwright() as p:
        s = SessionPool(p)
        page = s.for_platform(db.job_identity(url)[0]).new_tab(url)   # the Chrome logged in to this site
        offer = read_offer(page) or {"title": "", "text": "", "apply_kind": "none"}
        app_id = store.save_offer(con, url, offer, "manual")
        page.close()
        apply_now(s, con, con.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone(), input)
        s.close()
