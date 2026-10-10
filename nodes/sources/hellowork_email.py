"""
HelloWork job-alert emails -> offer cards. Format not seen yet: generic reader (board_email.py).
"""

from nodes.sources import hellowork
from nodes.sources.board_email import make_parser

NAME = "hellowork_email"
PLATFORM = "hellowork"
KIND = "email"
SENDERS = ["hellowork"]

parse = make_parser(hellowork.canonical, hellowork.key_of)
key_of = hellowork.key_of


def offer_url(card: dict, _unused: str = "") -> str:
    return hellowork.canonical(card["href"]) or card["href"]
