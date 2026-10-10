"""
LinkedIn job-alert emails (jobalerts-noreply@linkedin.com) -> offer cards, then the normal chain.
The agent never browses LinkedIn for this source until it opens the offer page in YOUR logged-in agent Chrome
(the same page you would open by clicking the email).

One offer in the email (plain text part):
    ---------------------------------------------------------
    System Reliability Engineer (Python)          <- title
    Quarkslab                                      <- company
    75011, Paris, Ile-de-France, France            <- location
    | Easy Apply                                   <- optional
    Voir l'offre d'emploi : https://www.linkedin.com/comm/jobs/view/2453474129?...
Newer emails may put "Company · Location" on one line: handled too.
"""

import re

from nodes.sources.mail import blocks_before_links

NAME = "linkedin_email"
PLATFORM = "linkedin"
KIND = "email"
SENDERS = ["jobalerts-noreply@linkedin.com"]

LINK = re.compile(r"https?://\S*/jobs/view/(?:[^/?\s]*-)?(\d{6,})\S*", re.I)
SEP = re.compile(r"^[-=_.]{8,}$")
EASY = re.compile(r"easy apply|candidature simplifi", re.I)
NOISE = re.compile(r"^(voir l.offre|view job|postuler|apply|nouveau|new|promu|promoted|\d+ (candidats|applicants)"
                   r"|recrutement actif|actively recruiting|il y a |\d+ (jours?|days?|heures?|hours?)"
                   r"|top candidat|top applicant|en vue|vous [êe]tes un top)", re.I)
# email header glued to the FIRST offer: "Votre alerte Emploi pour X (France)" / "Plus de 30 nouvelles offres..."
HEADER = re.compile(r"^(votre alerte (emploi|d.emploi)|your job alert|plus de \d+|\d+\+? nouvelles? offres?|\d+\+? new jobs?"
                    r"|.*(correspondent|match(es)?) (à|a) vos pr[ée]f[ée]rences|.*match your preferences"
                    r"|nouvelles offres d.emploi issues|new jobs from your other|offres d.emploi\s*:|jobs?\s*:|.*<strong)", re.I)
TAG = re.compile(r"<[^>]+>")


def parse(text: str) -> list[dict]:
    cards, seen = [], set()
    for link, lines in blocks_before_links(text, LINK, SEP):
        jid = LINK.search(link).group(1)
        flags = " ".join(lines)
        heads = [i for i, l in enumerate(lines) if HEADER.match(l.lstrip("| ").strip())]
        if heads:
            lines = lines[heads[-1] + 1:]               # keep what comes after the email header
        lines = [TAG.sub("", l).lstrip("| ").strip() for l in lines]
        lines = [l for l in lines if l and not EASY.fullmatch(l) and not NOISE.match(l)]
        if jid in seen or not lines:
            continue
        seen.add(jid)
        company, location = (lines[1] if len(lines) > 1 else ""), (lines[2] if len(lines) > 2 else "")
        if "·" in company and not location:
            company, _, location = company.partition("·")
        if "linkedin." in link:
            link = f"https://www.linkedin.com/jobs/view/{jid}/"     # no tracking tokens in the db
        cards.append({"jk": jid, "href": link, "title": lines[0], "company": company.strip(),
                      "location": location.strip(), "easy_apply": bool(EASY.search(flags))})
    return cards


def offer_url(card: dict, _unused: str = "") -> str:
    if "linkedin." in card["href"]:
        return f"https://www.linkedin.com/jobs/view/{card['jk']}/"
    return card["href"]                              # tests: fake site
