"""
Indeed job-alert emails (donotreply@jobalert.indeed.com) -> offer cards, then the normal chain
(dedupe -> read the offer page -> prefilter -> judge). Create the alerts on Indeed (one per wording).

One offer in the email (plain text part):
    Ingénieur IA / Machine Learning (F/H)          <- title
    ENOVIA - Vélizy-Villacoublay (78)              <- company - location
    Employeur réactif / Candidature simplifiée     <- optional badges
    1 150 € par mois                               <- optional salary
    Nous recherchons un ingénieur IA ...           <- snippet
    il y a 6 jours                                 <- age
    https://fr.indeed.com/rc/clk/dl?jk=5a4d3aa4db5c53fe&...
The jk in the link is the Indeed id: same offer as in the browser search -> judged once.
"""

import re
from urllib.parse import urlparse, parse_qs

from nodes.sources.mail import blocks_before_links

NAME = "indeed_email"
PLATFORM = "indeed"
KIND = "email"
SENDERS = ["jobalert.indeed.com"]

LINK = re.compile(r"https?://\S*[?&](?:jk|vjk)=[0-9a-f]+\S*", re.I)
BADGES = re.compile(r"^(employeur r[ée]actif|candidature simplifi[ée]e|nouveau|urgent|responsive employer|easily apply)$", re.I)
AGE = re.compile(r"^(publi[ée] |il y a |posted |\d+\+? (jours?|days?)|aujourd)", re.I)


def parse(text: str) -> list[dict]:
    cards = []
    for link, lines in blocks_before_links(text, LINK, last_paragraph=True):
        jk = (parse_qs(urlparse(link).query).get("jk") or parse_qs(urlparse(link).query).get("vjk") or [None])[0]
        if not jk or not lines:
            continue
        company, location = "", ""
        if len(lines) > 1:
            company, _, location = lines[1].rpartition(" - ")
            if not company:
                company, location = lines[1], ""
        cards.append({"jk": jk, "href": link, "title": lines[0], "company": company.strip(),
                      "location": location.strip(),
                      "easy_apply": any(re.match(r"candidature simplifi|easily apply", l, re.I) for l in lines)})
    return cards


def offer_url(card: dict, _unused: str = "") -> str:
    """Clean offer page (the email link is a tracking redirect)."""
    u = urlparse(card["href"])
    if "indeed." in u.netloc:
        return f"https://{u.netloc}/viewjob?jk={card['jk']}"
    return card["href"]                              # tests: fake job board
