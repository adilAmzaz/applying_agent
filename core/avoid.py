"""
[avoid] in config.toml: sites and companies where the agent NEVER applies.
The offer is still read, judged and saved (you see it in the report); only the application is skipped.

  sites     = ["3ds.com"]          a site matches itself and its sub-domains: "3ds.com" -> www.3ds.com, careers.3ds.com
  companies = ["Dassault Systemes"]  compared without accents / case, on the company of the offer

Checked twice: before applying (offer page, its "apply on the company site" link, company name), and during
the application (each page the agent lands on: a job board can send you to the company site).
"""
import re
import unicodedata
from urllib.parse import urlparse

from core.config import CONFIG


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _host(url_or_host: str, port: bool = False) -> str:
    s = (url_or_host or "").strip().lower()
    u = urlparse(s if "://" in s else "https://" + s)
    h = (u.netloc.split("@")[-1] if port else u.hostname) or ""
    return h[4:] if h.startswith("www.") else h


def site(url: str) -> str | None:
    """The [avoid] site this URL is on, or None."""
    for s in CONFIG.get("avoid", {}).get("sites", []):
        with_port = ":" in _host(s, port=True)              # "127.0.0.1:8771" (tests): host AND port
        h, a = _host(url, with_port), _host(s, with_port)
        if h and a and (h == a or h.endswith("." + a)):
            return s
    return None


def company(name: str) -> str | None:
    """The [avoid] company matching this company name, or None (whole words: "ACME" never matches "ACMEX")."""
    n = f" {_norm(name)} "
    for c in CONFIG.get("avoid", {}).get("companies", []):
        if _norm(c) and f" {_norm(c)} " in n:
            return c
    return None


def reason(*urls: str, company_name: str = "") -> str | None:
    """'avoided site 3ds.com' / 'avoided company X' / None."""
    for u in urls:
        if u and (s := site(u)):
            return f"avoided site {s} ([avoid] in config.toml)"
    if company_name and (c := company(company_name)):
        return f"avoided company {c} ([avoid] in config.toml)"
    return None
