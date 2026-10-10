"""
Generic reader for job-alert emails of a board whose exact email format was not seen yet (WTTJ, HelloWork).

  - a direct offer link (the board's offer URL)  -> id known at once
  - a tracking link (click.../track/redirect)      -> card marked "resolve": the read node opens it, takes the
    real offer address from the page and only then checks "already seen?"
  - SAFETY: a tracking link is opened only when an offer (title + company) is written just before it,
    and never when its label / link looks like unsubscribe, settings, apps, help...
The text lines just before each link: title / company / place (when present).
"""

import re
from urllib.parse import urlparse

from nodes.sources.mail import blocks_before_links

LINK = re.compile(r"https?://[^\s<>\"')]+", re.I)            # every link: the sender is already the board
TRACKING = re.compile(r"click|track|/ls/|redirect|url\d*\.|links?\.|/r/|/c/", re.I)
FOOTER = re.compile(r"unsubscribe|desabonn|désabonn|preferences|pr[ée]f[ée]rences|settings|parametres|paramètres|"
                    r"/alerts?\b|/alertes?\b|apps\.apple|play\.google|privacy|confidentialit|/legal|cgu|help|aide|"
                    r"facebook|instagram|linkedin\.com|twitter|tiktok|youtube", re.I)
FOOTER_LABEL = re.compile(r"d[ée]sabonn|unsubscribe|g[ée]rer|manage|pr[ée]f[ée]rences|param[eè]tres|settings|"
                          r"t[ée]l[ée]charg|download|aide|help|confidentialit|privacy|voir toutes|see all|"
                          r"modifier (mon|l.)alerte", re.I)
NOISE = re.compile(r"^(voir l.offre|voir l.annonce|voir|postuler|d[ée]couvrir|view|apply|see|nouveau|new|[<>→›»]+)$", re.I)


def make_parser(canonical, key_of):
    """canonical(url) -> clean offer URL or None (not an offer link); key_of(url) -> the board's offer id."""
    def parse(text: str) -> list[dict]:
        cards, seen = [], set()
        for link, lines in blocks_before_links(text, LINK):
            if FOOTER.search(link) or (lines and FOOTER_LABEL.search(lines[-1])):
                continue                              # unsubscribe / settings / apps: NEVER opened
            lines = [l for l in lines if not NOISE.match(l)]
            canon = canonical(link)
            if canon is None and (not TRACKING.search(link) or len(lines) < 2):
                continue                              # not an offer, or a tracking link with no offer before it
            if not lines:
                continue
            key = key_of(canon) if canon else link
            if key in seen:
                continue
            seen.add(key)
            cards.append({"jk": key, "href": link,
                          "title": lines[-3] if len(lines) >= 3 else lines[0],
                          "company": lines[-2] if len(lines) >= 3 else (lines[1] if len(lines) > 1 else ""),
                          "location": lines[-1] if len(lines) >= 3 else "",
                          "easy_apply": False, "resolve": canon is None})
        return cards
    return parse
