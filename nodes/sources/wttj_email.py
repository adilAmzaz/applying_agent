"""
Welcome to the Jungle job-alert emails -> offer cards (create the alert on a WTTJ search: "Créer une alerte").
Format not seen yet: generic reader (board_email.py), direct and tracking links.
"""

from nodes.sources import wttj
from nodes.sources.board_email import make_parser

NAME = "wttj_email"
PLATFORM = "wttj"
KIND = "email"
SENDERS = ["welcometothejungle", "wttj.co"]

parse = make_parser(wttj.canonical, wttj.key_of)
key_of = wttj.key_of


def offer_url(card: dict, _unused: str = "") -> str:
    return wttj.canonical(card["href"]) or card["href"]
