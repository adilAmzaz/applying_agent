"""
LinkedIn source (browser): search pages of your logged-in LinkedIn in the agent Chrome.

Same names as indeed.py. LinkedIn is stricter than Indeed with automation: config.toml [linkedin] keeps it slow
(pause_seconds, max_pages). If LinkedIn shows a login wall or a security check, the LinkedIn searches stop for this
scan (the other sources go on) and the report says so: log in by hand in the agent Chrome, then scan again.
"""

import re
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse

from core.config import CONFIG

NAME = "linkedin"
PLATFORM = "linkedin"
KIND = "browser"
PER_PAGE = 25
DATE_POSTED = {"day": "r86400", "week": "r604800", "month": "r2592000"}

# async: the results list loads its cards while you scroll it (and empties the ones far away),
# so cards are collected at each scroll step.
RESULTS_JS = r"""async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const found = new Map();
  const clean = t => (t || '').split('\n').map(s => s.trim()).filter(Boolean)[0] || '';
  const idOf = (card, a) => {
    const d = card.dataset || {};
    if (d.jobId) return d.jobId;
    if (d.occludableJobId) return d.occludableJobId;
    const urn = card.getAttribute('data-entity-urn') || '';
    if (/jobPosting:(\d+)/.test(urn)) return urn.match(/jobPosting:(\d+)/)[1];
    const m = (a && a.href || '').match(/\/jobs\/view\/(?:[^\/?]*-)?(\d{6,})/);
    return m ? m[1] : null;
  };
  const collect = () => {
    const cards = document.querySelectorAll('[data-job-id], [data-occludable-job-id], .base-card[data-entity-urn], .job-search-card');
    for (const card of cards) {
      const a = card.querySelector('a[href*="/jobs/view/"], a.job-card-container__link, a.base-card__full-link')
                || (card.matches('a') ? card : null);
      const id = idOf(card, a);
      if (!id) continue;
      const q = s => clean((card.querySelector(s) || {}).innerText);
      let title = q('.job-card-list__title--link strong, .job-card-list__title, .base-search-card__title')
                  || clean(a && (a.innerText || a.getAttribute('aria-label')));
      title = title.replace(/\s+(with verification|avec v[ée]rification)$/i, '');
      if (!title) continue;                       // card not rendered yet: taken at a later scroll step
      const text = card.innerText || '';
      found.set(id, {
        jk: id, href: a ? a.href : location.href, title,
        company: q('.artdeco-entity-lockup__subtitle, .job-card-container__primary-description, .base-search-card__subtitle'),
        location: q('.job-card-container__metadata-wrapper li, .artdeco-entity-lockup__caption, .job-search-card__location'),
        easy_apply: /candidature simplifi|easy apply/i.test(text),
        applied_on_board: /candidature envoy|applied/i.test(q('.job-card-container__footer-job-state, .job-card-container__footer-item') || ''),
      });
    }
  };
  collect();
  const first = document.querySelector('[data-job-id], [data-occludable-job-id], .base-card');
  let box = first && first.parentElement;
  while (box && !(box.scrollHeight > box.clientHeight + 20 && /(auto|scroll)/.test(getComputedStyle(box).overflowY)))
    box = box.parentElement;
  for (let i = 0; i < 14; i++) {
    if (box) box.scrollBy(0, 700); else window.scrollBy(0, 700);
    await sleep(350);
    collect();
  }
  return [...found.values()];
}"""

BLOCKED_URL = re.compile(r"/authwall|/login|/checkpoint|/uas/|/signup", re.I)


def results_url(search: dict, page_no: int, base_url: str | None = None) -> str:
    cfg = CONFIG.get("linkedin", {})
    if base_url:
        u = urlparse(base_url)
        q = parse_qs(u.query)
        q["start"] = [str(page_no * PER_PAGE)]
        q.pop("currentJobId", None)
        return urlunparse(u._replace(query=urlencode(q, doseq=True)))
    url = (f"https://www.linkedin.com/jobs/search/?keywords={quote(search['query'])}"
           f"&location={quote(cfg.get('location') or search['location'])}")
    if DATE_POSTED.get(cfg.get("date_posted", "week")):
        url += f"&f_TPR={DATE_POSTED[cfg.get('date_posted', 'week')]}"
    if cfg.get("easy_apply_only", search.get("easy_apply_only")):
        url += "&f_AL=true"
    if page_no:
        url += f"&start={page_no * PER_PAGE}"
    return url


def offer_url(card: dict, results_page_url: str) -> str:
    """Clean offer page /jobs/view/<id>/ (tests: the card link)."""
    if "linkedin." in urlparse(results_page_url).netloc:
        return f"https://www.linkedin.com/jobs/view/{card['jk']}/"
    return card["href"]


def blocked(url: str, cards: list, title: str = "") -> str | None:
    """Login wall / security check: LinkedIn searches stop for this scan."""
    if BLOCKED_URL.search(urlparse(url).path):
        return "LinkedIn asks to log in / a security check: open the agent Chrome, log in by hand, scan again"
    return None
