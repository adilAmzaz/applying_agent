"""
Welcome to the Jungle source (browser), read in the agent Chrome.

Since October 2026 WTTJ has NO public search any more: /fr/jobs?query=... shows a "create your profile" page.
The offers are YOUR MATCHES (/fr/jobs-matches), only when logged in, chosen from your WTTJ profile (job title,
skills, preferences). So: one read of the matches per scan (not one per query), and a clear message when the
agent Chrome is not logged in.

Offer link: /fr/companies/<company>/jobs/<job-slug>  -> no numeric id: the identity is "<company>/<job-slug>".
The results list is drawn by JavaScript after the page loads: RESULTS_JS waits for the cards.
Apply: "Postuler" opens WTTJ's own form (needs your WTTJ account, logged in by hand in the agent Chrome)
or sends you to the company site. Same guardrails as Indeed/LinkedIn.
"""

import re
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse

from core.config import CONFIG

NAME = "wttj"
PLATFORM = "wttj"
KIND = "browser"
QUERYLESS = True                                  # the matches do not depend on our queries: read once per scan
STOP_WHEN_KNOWN = False                           # matches are sorted by relevance, not date: read every page
SORT_BY_DATE = True                               # WTTJ cannot sort the matches by date (no such option):
                                                  # the scan reads ALL the pages first, then handles newest first
MATCHES_URL = "https://www.welcometothejungle.com/fr/jobs-matches"
JOB_PATH = re.compile(r"/companies/([^/?#]+)/jobs/([^/?#]+)")

RESULTS_JS = r"""async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const links = () => [...document.querySelectorAll('a[href*="/jobs/"]')]
      .filter(a => /\/companies\/[^\/?#]+\/jobs\/[^\/?#]+/.test(new URL(a.href, location.href).pathname));
  for (let i = 0; i < 20 && !links().length; i++) await sleep(400);      // list drawn after load
  for (let i = 0, n = -1; i < 25 && links().length !== n; i++) {     // matches load while scrolling
    n = links().length; window.scrollBy(0, 2000); await sleep(600);
  }
  const out = new Map();
  const pretty = slug => slug.replace(/[-_]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  const CITY = /^(paris|lyon|lille|nantes|bordeaux|toulouse|marseille|rennes|nice|strasbourg|montpellier|grenoble|nanterre|courbevoie|boulogne|puteaux|issy|levallois|sophia|aix|.{2,40} \(\d{2}\)|france)\b/i;
  const MONTHS = {janvier: 1, 'février': 2, fevrier: 2, mars: 3, avril: 4, mai: 5, juin: 6, juillet: 7, 'août': 8,
                  aout: 8, septembre: 9, octobre: 10, novembre: 11, 'décembre': 12, decembre: 12};
  const iso = d => d.toISOString().slice(0, 10);
  const dateOf = lines => {                         // "10 octobre 2026", "Aujourd'hui", "Hier", "il y a 3 jours"
    for (const l of lines) {
      let m = l.match(/^(?:publi[ée]e? le )?(\d{1,2}) ([a-zéû]+) (\d{4})$/i);
      if (m && MONTHS[m[2].toLowerCase()])
        return `${m[3]}-${String(MONTHS[m[2].toLowerCase()]).padStart(2, '0')}-${m[1].padStart(2, '0')}`;
      if (/^aujourd.hui$/i.test(l)) return iso(new Date());
      if (/^hier$/i.test(l)) return iso(new Date(Date.now() - 864e5));
      m = l.match(/^il y a (\d+) jours?$/i);
      if (m) return iso(new Date(Date.now() - m[1] * 864e5));
    }
    return '';
  };
  const PLACE = /(paris|lyon|lille|nantes|bordeaux|toulouse|marseille|rennes|nice|strasbourg|montpellier|grenoble|france|t[ée]l[ée]travail|remote)/i;
  for (const a of links()) {
    const u = new URL(a.href, location.href);
    const m = u.pathname.match(/\/companies\/([^\/?#]+)\/jobs\/([^\/?#]+)/);
    const id = m[1] + '/' + m[2];
    let card = a.closest('li, article, [data-testid*="search-results-list-item"], [data-testid*="job"]');
    if (!card) {                                    // matches page: plain <div>s, the card holds "Pas pour moi"
      card = a.parentElement;
      for (let i = 0; i < 8 && card.parentElement && !/pas pour moi|enregistrer/i.test(card.innerText || ''); i++)
        card = card.parentElement;
    }
    const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    const h = card.querySelector('h2, h3, h4, [role=heading]');
    const title = ((h && h.innerText) || a.innerText || '').split('\n')[0].trim();
    if (!title) continue;
    const prev = out.get(id);
    if (prev && prev.title) continue;
    const img = card.querySelector('img[alt]');
    out.set(id, {
      jk: id, href: u.origin + u.pathname, title,
      company: (img && img.alt && !/logo$/i.test(img.alt) ? img.alt : '') || pretty(m[1]),
      location: lines.find(l => CITY.test(l) && l.length < 40 && l !== title)
                || lines.find(l => PLACE.test(l) && l.length < 60 && l !== title) || '',
      published: dateOf(lines),
      applied_on_board: /candidature envoy|d[ée]j[àa] postul|vous avez postul/i.test(card.innerText || ''),
      easy_apply: false,
    });
  }
  return [...out.values()];
}"""

CHALLENGE = re.compile(r"just a moment|un instant|attention required|v[ée]rification", re.I)
LOGIN_NEEDED = ("WTTJ shows offers only to a LOGGED-IN profile now (your 'matches'): in the WTTJ agent Chrome "
                "(start_chrome.bat wttj) log in, finish your profile (job title, skills), then scan again")


def results_url(search: dict, page_no: int, base_url: str | None = None) -> str:
    """Your matches (logged in). base_url: a results URL pasted in [search] extra_search_urls (pages start at 1)."""
    if base_url:
        u = urlparse(base_url)
        q = parse_qs(u.query)
        q["page"] = [str(page_no + 1)]
        return urlunparse(u._replace(query=urlencode(q, doseq=True)))
    since = CONFIG.get("wttj", {}).get("published_since", "last_7d")    # last_3d, last_7d, "" = all dates
    params = ([f"published_since={since}"] if since else []) + ([f"page={page_no + 1}"] if page_no else [])
    return MATCHES_URL + ("?" + "&".join(params) if params else "")


def canonical(url: str) -> str | None:
    """Clean offer URL from any WTTJ offer link (language prefix, query and tracking removed)."""
    m = JOB_PATH.search(urlparse(url).path)
    if not m:
        return None
    u = urlparse(url)
    if "welcometothejungle." in u.netloc:
        return f"https://www.welcometothejungle.com/fr/companies/{m.group(1)}/jobs/{m.group(2)}"
    return f"{u.scheme}://{u.netloc}{u.path[:m.end()]}"  # tests: fake site (same form, no trailing slash)


def key_of(url: str) -> str:
    """Same id as the results cards: "<company>/<job-slug>"."""
    m = JOB_PATH.search(urlparse(url).path)
    return f"{m.group(1)}/{m.group(2)}" if m else url


def offer_url(card: dict, results_page_url: str = "") -> str:
    return canonical(card["href"]) or card["href"]


def blocked(url: str, cards: list, title: str = "") -> str | None:
    if not cards and CHALLENGE.search(title or ""):
        return "Welcome to the Jungle shows a robot check: open the agent Chrome, pass it by hand, scan again"
    path = urlparse(url).path
    if not cards and re.search(r"/authenticate/|/get-started|/fr/jobs/?$|/en/jobs/?$", path):
        return LOGIN_NEEDED
    return None
