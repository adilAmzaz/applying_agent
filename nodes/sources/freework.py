"""
Free-Work source (browser): IT jobs AND freelance missions, public search pages read in the agent Chrome.

Search : https://www.free-work.com/fr/tech-it/jobs?query=<q>&page=<n>   (page 1 = no page=)
Offer  : /fr/tech-it/job-mission/<category>/<slug>                         -> key = <slug>
Cards  : <h2> title, contract types (CDI / Freelance / CDD), date, company, "LIEU" <city>. The "latest offers"
         ticker at the top of every page (<fw-marquee>) is NOT a result: ignored.
Apply  : "Postuler" opens Free-Work's own form, which needs your Free-Work account (log in BY HAND once in the
         agent Chrome: start_chrome.bat freework). Same guardrails as the other boards.
"""

import re
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

from core.config import CONFIG

NAME = "freework"
PLATFORM = "freework"
KIND = "browser"
JOB_PATH = re.compile(r"/job-mission/([^/?#]+)/([^/?#]+)")

RESULTS_JS = r"""async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const RE = /\/job-mission\/([^\/?#]+)\/([^\/?#]+)/;
  const links = () => [...document.querySelectorAll('a[href*="/job-mission/"]')]
      .filter(a => RE.test(a.getAttribute('href') || '') && !a.closest('fw-marquee'));
  for (let i = 0; i < 15 && !links().length; i++) await sleep(400);
  const out = new Map();
  for (const a of links()) {
    const url = new URL(a.getAttribute('href'), location.href);
    const slug = url.pathname.match(RE)[2];
    if (out.has(slug)) continue;
    let card = a;                                   // the result block: the one with the <h2> title
    for (let i = 0; i < 10 && card.parentElement; i++) {
      card = card.parentElement;
      if (card.querySelector('h2, h3') && (card.innerText || '').length > 80) break;
    }
    const h = card.querySelector('h2, h3');
    const title = ((h && h.innerText) || a.innerText || '').trim().split('\n')[0];
    if (!title || /^voir cette offre$/i.test(title)) continue;
    const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    let outer = card;                               // "LIEU" sits in a side panel next to the text block
    for (let i = 0; i < 4 && outer.parentElement && !/(^|\n)\s*(lieu|localisation)\s*\n/i.test(outer.innerText || ''); i++)
      outer = outer.parentElement;
    const side = (outer.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    const at = side.findIndex(l => /^(lieu|localisation)$/i.test(l));
    const date = lines.findIndex(l => /^\d{2}\/\d{2}\/\d{4}$/.test(l) || /^il y a /i.test(l));
    const contracts = lines.filter(l => /^(cdi|cdd|freelance|stage|alternance|int[ée]rim)$/i.test(l));
    out.set(slug, {
      jk: slug, href: url.origin + url.pathname, title,
      company: date >= 0 && lines[date + 1] && lines[date + 1].length < 80 ? lines[date + 1] : '',
      location: at >= 0 ? (side[at + 1] || '') : '',
      contract: contracts.join(', '),
      easy_apply: true,                              // Free-Work's own form ("Postuler")
      applied_on_board: /d[ée]j[àa] postul|candidature envoy|vous avez postul|postul[ée] le/i.test(card.innerText || ''),
    });
  }
  return [...out.values()];
}"""

CHALLENGE = re.compile(r"just a moment|un instant|attention required|v[ée]rification|captcha", re.I)


# newest first: a results page where every offer is already known = the rest is older -> next query
STOP_WHEN_KNOWN = True


def results_url(search: dict, page_no: int, base_url: str | None = None) -> str:
    """Free-Work pages start at 1 (page=). [freework] contracts = ["permanent", "contractor"] filters."""
    if base_url:
        u = urlparse(base_url)
        q = parse_qs(u.query)
        if page_no:
            q["page"] = [str(page_no + 1)]
        return urlunparse(u._replace(query=urlencode(q, doseq=True)))
    cfg = CONFIG.get("freework", {})
    url = f"https://www.free-work.com/fr/tech-it/jobs?query={quote(search['query'])}"
    for c in cfg.get("contracts", []):               # permanent (CDI), contractor (freelance), fixed-term...
        url += f"&contracts={quote(c)}"
    if cfg.get("locations"):                         # e.g. "fr~~~" (France) or "fr~ile-de-france~~"
        url += f"&locations={quote(cfg['locations'], safe='~')}"
    sort = cfg.get("sort", "date")                   # "date" = newest first (default), "relevance" = the site's order
    if sort and sort != "relevance":
        url += f"&sort={quote(sort)}"
    return url + (f"&page={page_no + 1}" if page_no else "")


def canonical(url: str) -> str | None:
    u = urlparse(url)
    m = JOB_PATH.search(u.path)
    if not m:
        return None
    if "free-work." in u.netloc:
        return f"https://www.free-work.com/fr/tech-it/job-mission/{m.group(1)}/{m.group(2)}"
    return f"{u.scheme}://{u.netloc}{u.path[:m.end()]}"  # tests: fake site


def key_of(url: str) -> str:
    m = JOB_PATH.search(urlparse(url).path)
    return m.group(2) if m else url


def offer_url(card: dict, results_page_url: str = "") -> str:
    return canonical(card["href"]) or card["href"]


def blocked(url: str, cards: list, title: str = "") -> str | None:
    if not cards and CHALLENGE.search(title or ""):
        return "Free-Work shows a robot check: open the agent Chrome, pass it by hand, scan again"
    return None
