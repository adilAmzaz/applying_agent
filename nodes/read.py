"""
READ node: an offer page -> its text and how to apply. No LLM.
The only click: the "plus" / "Show more" of the job description itself (LinkedIn cuts it), never anything else.
Works on Indeed, LinkedIn (old, new and public layouts), WTTJ and HelloWork offer pages:
known selectors first, else the section under the title "À propos de l'offre d'emploi" / "About the job".
"""

import re
from urllib.parse import urlparse

from core.db import find_contacts

# Title of the description section (LinkedIn's new layout has no stable class names)
ABOUT_RE = r"^(à propos de l.offre d.emploi|about the job|description du poste|descriptif du poste|le poste)$"

DESCRIPTION_BOX_JS = r"""
  const ABOUT = new RegExp(%r, 'i');
  const known = ['#jobDescriptionText', '[data-testid=jobsearch-JobComponent-description]',          // Indeed
                 '#job-details', '.jobs-description__content', '.jobs-box__html-content',             // LinkedIn
                 '.description__text', '.show-more-less-html'];
  const boxes = known.map(s => document.querySelector(s)).filter(Boolean);
  for (const h of document.querySelectorAll('h1,h2,h3,h4,strong,span,div')) {
    if (h.children.length > 2 || !ABOUT.test((h.innerText || '').trim())) continue;
    let b = h.parentElement;                         // the smallest block around the title that holds the text
    while (b && b !== document.body && b.innerText.length < h.innerText.length + 200) b = b.parentElement;
    if (b && b !== document.body) boxes.push(b);
  }
""" % ABOUT_RE

# click the "plus" / "Show more" INSIDE the description only (never "Afficher plus d'offres d'emploi")
EXPAND_JS = r"""async () => {""" + DESCRIPTION_BOX_JS + r"""
  const MORE = /^(…|\.\.\.)?\s*(plus|voir plus|afficher plus|en savoir plus|see more|show more|more|lire la suite)$/i;
  const clicked = [];
  for (const box of boxes) for (const b of box.querySelectorAll('button, a, [role=button], span')) {
    const t = (b.innerText || b.getAttribute('aria-label') || '').trim();
    const looks = MORE.test(t) || /show-more-less-html__button--more|jobs-description__footer-button|inline-show-more-text__button/.test(String(b.className));
    if (looks && !/offres|jobs|recherches|emplois/i.test(t) && b.offsetParent && !clicked.includes(b)) {
      b.click(); clicked.push(b);
    }
  }
  if (clicked.length) await new Promise(r => setTimeout(r, 900));
  return clicked.length;
}"""

READ_JS = r"""() => {
  const first = list => list.map(s => document.querySelector(s)).find(Boolean);""" + DESCRIPTION_BOX_JS + r"""
  // known description blocks first, then the block under "À propos de l'offre d'emploi"; whole page last
  const d = boxes.find(b => b.innerText.length > 150 && b.innerText.length < 30000) || document.querySelector('main');
  const h = first(['.job-details-jobs-unified-top-card__job-title h1', '.top-card-layout__title',
                   '[data-testid=job-metadata-block] h2', 'h1']);
  const header = first(['[data-testid=jobsearch-JobInfoHeader-companyLocation]', '.jobsearch-CompanyInfoContainer',
                        '.job-details-jobs-unified-top-card__primary-description-container',
                        '.job-details-jobs-unified-top-card__company-name', '.topcard__flavor-row',
                        '[data-testid=job-metadata-block]']);                                      // WTTJ
  const top = first(['.job-details-jobs-unified-top-card__container--two-pane', '.jobs-unified-top-card',
                     '.jobs-details__main-content', '.top-card-layout']);       // LinkedIn: "closed" banner is here
  const buttons = [...document.querySelectorAll('button, a, [role=button]')].map(b => ({
      text: (b.innerText || b.getAttribute('aria-label') || '').trim(), href: b.href || ''}));
  const head = header || (h && h.parentElement !== document.body ? h.parentElement : null);   // new layouts: block of the title
  return {title: h ? h.innerText : document.title, header: head ? head.innerText.slice(0, 400) : '',
          text: (d || document.body).innerText, top: top ? top.innerText.slice(0, 1500) : '', buttons};
}"""

EASY = re.compile(r"postuler maintenant|candidature simplifi|apply now|easily apply|easy apply", re.I)
EXTERNAL = re.compile(r"continuer pour postuler|postuler sur le site|apply on company site|candidater sur le site"
                      r"|site (web )?de l.entreprise|site du recruteur|company website", re.I)
LINKEDIN_EXTERNAL = re.compile(r"^(postuler|apply)( [àa] .*| to .*)?$", re.I)      # LinkedIn "Postuler" = company site
DEAD = re.compile(r"page introuvable|page not found|offre (n'est plus|expir)|no longer available"
                  r"|n.accepte plus de candidatures|no longer accepting applications", re.I)


# Anti-bot / captcha page instead of the offer (Indeed + Cloudflare: "Vérification supplémentaire requise",
# "Un instant...", "Ray ID"): NOT an offer -- never judged (it was saved "LOW 0"), the human solves it
CHALLENGE_TITLE = re.compile(r"^(un instant|just a moment|attention required|v[ée]rification|security check|"
                             r"verify you are human|are you a robot|captcha|access denied|acc[eè]s refus[ée])", re.I)
CHALLENGE_TEXT = re.compile(r"v[ée]rification suppl[ée]mentaire requise|additional verification required|"
                            r"ray id|cloudflare|verify you are (a )?human|v[ée]rifiez que vous [êe]tes (un )?humain|"
                            r"are you a robot|[êe]tes-vous un robot|checking your browser|v[ée]rification de votre navigateur|"
                            r"enable javascript and cookies to continue|hcaptcha|recaptcha|turnstile", re.I)


def challenge(page) -> str | None:
    """The verification / captcha text if this page is an anti-bot page, else None."""
    try:
        title = (page.title() or "").strip()
        body = page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 3000)")
    except Exception:
        return None
    if CHALLENGE_TITLE.match(title):
        return title[:80]
    m = CHALLENGE_TEXT.search(body)
    if m and len(body) < 2500:                     # a real offer page is long; a block page is short
        return m.group(0)
    return None


def read_offer(page, platform: str | None = None) -> dict | None:
    """{title, text, apply_kind (easy|external|none), external_url, contacts} or None if the page is dead."""
    try:
        page.evaluate(EXPAND_JS)                     # the full description, not "... plus"
    except Exception:
        pass
    raw = page.evaluate(READ_JS)
    raw["text"] = re.sub(r"\s*(…|\.\.\.)?\s*(plus|voir plus|show more|see more|show less|voir moins|moins)\s*$", "",
                         raw["text"].strip(), flags=re.I)
    title = re.sub(r"\s+-\s+Indeed\.com$|\s+\|\s+LinkedIn$", "", raw["title"].split("\n")[0]).strip()
    text = f"{title}\n{raw['header']}\n\n{raw['text']}".strip()
    if DEAD.search(title) or DEAD.search(raw["header"]) or len(raw["text"].strip()) < 40:
        return None
    if DEAD.search(raw["top"]) or DEAD.search(raw["text"][:400]):   # closed banner (LinkedIn) / notice (WTTJ)
        return None
    linkedin = platform == "linkedin" or "linkedin." in (page.url or "")
    own_form = platform in ("wttj", "hellowork", "freework") or re.search(r"welcometothejungle\.|hellowork\.|free-work\.",
                                                                       page.url or "")
    kind, ext = "none", None
    for b in raw["buttons"]:
        if EASY.search(b["text"]):
            kind = "easy"
            break
        if own_form and EXTERNAL.search(b["text"]):
            kind, ext = "external", b["href"] or None
            break
        if own_form and re.match(r"(je )?postul|apply|candidater", b["text"], re.I):  # WTTJ / HelloWork / Free-Work: own form or company link
            href_host = urlparse(b["href"]).netloc if b["href"] else ""
            if href_host and not re.search(r"welcometothejungle\.|hellowork\.|free-work\.", href_host) \
                    and href_host != urlparse(page.url).netloc:
                kind, ext = "external", b["href"]
            else:
                kind = "easy"
            break
        if EXTERNAL.search(b["text"]) or (linkedin and LINKEDIN_EXTERNAL.search(b["text"])):
            kind, ext = "external", b["href"] or None
    return {"title": title, "text": text, "apply_kind": kind, "external_url": ext,
            "contacts": find_contacts(text)}
