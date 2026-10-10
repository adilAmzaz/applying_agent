"""
Free-Work job-alert emails -> offer cards. Format not seen yet: generic reader (board_email.py).
"""

from nodes.sources import freework
from nodes.sources.board_email import make_parser

NAME = "freework_email"
PLATFORM = "freework"
KIND = "email"
SENDERS = ["free-work"]

parse = make_parser(freework.canonical, freework.key_of)
key_of = freework.key_of


def offer_url(card: dict, _unused: str = "") -> str:
    return freework.canonical(card["href"]) or card["href"]
