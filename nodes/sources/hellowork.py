"""
HelloWork source (browser): public search pages, read in the agent Chrome.

Offer link: /fr-fr/emplois/<id>.html  -> numeric id.
Apply: "Postuler" opens HelloWork's own form (needs your HelloWork account, logged in by hand in the agent
Chrome) or "Postuler sur le site du recruteur" (company site). Same guardrails as the other boards.
"""

import re
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse

from core.config import CONFIG

NAME = "hellowork"
PLATFORM = "hellowork"
KIND = "browser"
JOB_PATH = re.compile(r"/emplois/(\d{5,})\.html")

RESULTS_JS = r"""async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const RE = /\/emplois\/(\d{5,})\.html/;
  const links = () => [...document.querySelectorAll('a[href*="/emplois/"]')].filter(a => RE.test(a.href));
  for (let i = 0; i < 15 && !links().length; i++) await sleep(400);
  const out = new Map();
  const PLACE = /(paris|lyon|lille|nantes|bordeaux|toulouse|marseille|rennes|nice|strasbourg|montpellier|grenoble|france|t[ée]l[ée]travail|\(\d{2,3}\)|\d{2} -)/i;
  for (const a of links()) {
    const id = a.href.match(RE)[1];
    if (out.has(id) && out.get(id).title) continue;
    const card = a.closest('li, article, [data-cy*="serpCard"], [data-id-storage-target]') || a.parentElement;
    const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    const h = card.querySelector('h2, h3, [role=heading]');
    const head = ((h && h.innerText) || a.getAttribute('aria-label') || a.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    const title = head[0] || '';
    if (!title) continue;
    out.set(id, {
      jk: id, href: new URL(a.href, location.href).origin + new URL(a.href, location.href).pathname, title,
      company: head[1] || lines.find(l => l !== title && l.length < 60 && !PLACE.test(l)) || '',
      location: lines.find(l => PLACE.test(l) && l.length < 60 && l !== title) || '',
      easy_apply: /candidature (simplifi|facile|rapide)|postuler en 1 clic/i.test(card.innerText || ''),
      applied_on_board: /d[ée]j[àa] postul|candidature envoy/i.test(card.innerText || ''),
    });
  }
  return [...out.values()];
}"""

CHALLENGE = re.compile(r"just a moment|un instant|attention required|v[ée]rification|captcha", re.I)


def results_url(search: dict, page_no: int, base_url: str | None = None) -> str:
    """HelloWork pages start at 1 (p=)."""
    if base_url:
        u = urlparse(base_url)
        q = parse_qs(u.query)
        q["p"] = [str(page_no + 1)]
        return urlunparse(u._replace(query=urlencode(q, doseq=True)))
    cfg = CONFIG.get("hellowork", {})
    loc = (cfg.get("location") or search.get("location") or "").strip()
    url = f"https://www.hellowork.com/fr-fr/emploi/recherche.html?k={quote(search['query'])}"
    if loc and loc.lower() != "france":
        url += f"&l={quote(loc)}"
    if cfg.get("date_posted"):                       # HelloWork "d" filter: h (24h), w (week), m (month)
        url += f"&d={ {'day': 'h', 'week': 'w', 'month': 'm'}.get(cfg['date_posted'], 'all') }"
    return url + (f"&p={page_no + 1}" if page_no else "")


def canonical(url: str) -> str | None:
    u = urlparse(url)
    m = JOB_PATH.search(u.path)
    if not m:
        return None
    if "hellowork." in u.netloc:
        return f"https://www.hellowork.com/fr-fr/emplois/{m.group(1)}.html"
    return f"{u.scheme}://{u.netloc}{u.path[:m.end()]}"  # tests: fake site


def key_of(url: str) -> str:
    m = JOB_PATH.search(urlparse(url).path)
    return m.group(1) if m else url


def offer_url(card: dict, results_page_url: str = "") -> str:
    return canonical(card["href"]) or card["href"]


def blocked(url: str, cards: list, title: str = "") -> str | None:
    if not cards and CHALLENGE.search(title or ""):
        return "HelloWork shows a robot check: open the agent Chrome, pass it by hand, scan again"
    return None
