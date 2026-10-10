"""
Indeed source: search URLs, reading a results page, offer URL.
A new site (hellowork.py, wttj.py...) needs the same names: NAME, PLATFORM, KIND, results_url, RESULTS_JS, offer_url
(optional: blocked(url, cards) -> reason when the site shows a login wall / captcha).
Email sources (KIND = "email") instead have SENDERS and parse(text) -> cards: see indeed_email.py.
"""

from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse

NAME = "indeed"
PLATFORM = "indeed"      # same platform = same offer ids (dedupe across browser and email)
KIND = "browser"

RESULTS_JS = r"""() => {
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[data-jk], a[href*="jk="]')) {
    let u; try { u = new URL(a.href, location.href); } catch (e) { continue; }
    const jk = a.dataset.jk || u.searchParams.get('jk') || u.searchParams.get('vjk');
    if (!jk || seen.has(jk)) continue;
    seen.add(jk);
    const card = a.closest('li, .job_seen_beacon, article, [data-testid=slider_item]') || a.parentElement;
    const q = s => ((card.querySelector(s) || {}).innerText || '').trim();
    out.push({
      jk, href: u.href,
      title: (a.innerText || a.title || '').trim(),
      company: q('[data-testid=company-name], .companyName, .company'),
      location: q('[data-testid=text-location], .companyLocation, .location'),
      easy_apply: /candidature simplifi|easily apply/i.test(card.innerText || ''),
    });
  }
  return out;
}"""


def results_url(search: dict, page_no: int, base_url: str | None = None) -> str:
    """Page 0, 1, 2... (Indeed: start=0, 10, 20). base_url = a results URL pasted from the site."""
    if base_url:
        u = urlparse(base_url)
        q = parse_qs(u.query)
        q["start"] = [str(page_no * 10)]
        q.pop("vjk", None)
        return urlunparse(u._replace(query=urlencode(q, doseq=True)))
    url = f"https://fr.indeed.com/jobs?q={quote(search['query'])}&l={quote(search['location'])}"
    if search.get("easy_apply_only"):
        url += "&sc=0kf%3Aattr%28DSQF7%29%3B"
    if page_no:
        url += f"&start={page_no * 10}"
    return url


def offer_url(card: dict, results_page_url: str) -> str:
    """The clean offer page viewjob?jk=... (other hosts, e.g. tests: the card link)."""
    u = urlparse(results_page_url)
    if "indeed." in u.netloc:
        return f"{u.scheme}://{u.netloc}/viewjob?jk={card['jk']}"
    return card["href"]
