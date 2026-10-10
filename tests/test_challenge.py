"""
Indeed + Cloudflare: sometimes the OFFER page is "Vérification supplémentaire requise" (Ray ID) instead of the
offer. It used to be judged "LOW 0" under the title of the block page, and the scan went on opening offers.
Now: never judged / saved; you watching -> the agent asks you to solve it, then goes on; nobody -> the source
stops for this scan (its offers come back next scan). `python jobs.py reset blocked-pages` repairs old rows.
"""
from common import BOARD, CALLS, fresh
from playwright.sync_api import sync_playwright
from core import db
from core.browser import Session
import graphs.scan as scan_mod
from nodes import reset


def scan():
    with sync_playwright() as p:
        s = Session(p)
        st = scan_mod.run_scan(s)
        s.close()
    return st


SEARCH = {"sources": ["indeed"], "extra_search_urls": [BOARD + "/results_cf.html"]}

# 1) nobody watching: the captcha offer stops indeed for this scan -- nothing judged, nothing saved ------
con = fresh("cf1", search=SEARCH)
CALLS.update(judge=0)
st = scan()
rows = con.execute("SELECT listing_title, status FROM applications").fetchall()
print(st["stats"], [tuple(r) for r in rows])
assert CALLS["judge"] == 0 and rows == [], rows                     # not "LOW 0", not even saved
assert st["stats"].get("blocked_indeed") == 1 and "indeed" in st["stats"].get("blocked_sources", ""), st["stats"]

# 2) you watching: asked once, you solve it (Enter), the offer is read and judged, then the next one ---------
asked = []
scan_mod.human.ask = lambda prompt: asked.append(prompt) or ""
con = fresh("cf2", search=SEARCH, auto_apply={"supervised": True})
CALLS.update(judge=0)
st = scan()
rows = {r["listing_title"]: r for r in con.execute("SELECT * FROM applications")}
print(st["stats"], {k: v["status"] for k, v in rows.items()})
assert len(asked) == 1 and "verification / captcha" in asked[0], asked
assert CALLS["judge"] == 2 and "ML Engineer" in rows and "Zeta" in rows["ML Engineer"]["description"]

# 3) old rows judged on a verification page: found by "reset blocked-pages" ---------------------------------
x = db.upsert_offer(con, "https://fr.indeed.com/viewjob?jk=bad1", {"title": "Vérification supplémentaire requise"},
                    "Vérification supplémentaire requise\nVoici votre Ray ID pour cette requête : a48")
db.update(con, x, status="judged", verdict="low", score=0)
found, what = reset.select(con, ["blocked-pages"])
assert [r["id"] for r in found] == [x], [dict(r) for r in found]
print("\nALL CHALLENGE CHECKS PASSED")
