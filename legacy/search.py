"""
SEARCH side: build the search URL, read the results page, filter offers by keywords.
No LLM and no clicks here: results are read from the page, navigation is done by URL.
"""

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse

CRITERIA_FILE = Path("criteria.json")

DEFAULT_CRITERIA = {
    "query": "AI engineer",
    "location": "Paris",
    "any_of": [],             # at least ONE must appear in title + description
    "mandatory": [],          # ALL must appear (each may be "a|b")
    "excluded": [],           # NONE may appear
    "easy_apply_only": True,  # Indeed "Candidature simplifiée" filter
    "max_pages": 3,
    "search_url": "",         # optional: paste any results URL instead of query/location
}

# Reads the offer cards of a results page (Indeed markup + generic fallback on any link with jk=)
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


# ------------------------------------------------------------------ criteria
def load_criteria() -> dict:
    """Last criteria. Old files (before 'any_of' existed): their keywords meant 'one of them' in practice."""
    c = dict(DEFAULT_CRITERIA)
    if CRITERIA_FILE.exists():
        saved = json.loads(CRITERIA_FILE.read_text(encoding="utf-8"))
        if "any_of" not in saved:
            saved["any_of"], saved["mandatory"] = saved.get("mandatory", []), []
        c.update(saved)
    return c


def ask_criteria() -> dict:
    """Ask in the terminal, with the last values as defaults (Enter = keep)."""
    last = load_criteria()

    def ask(label, value):
        shown = ", ".join(value) if isinstance(value, list) else value
        ans = input(f"{label} [{shown}]: ").strip()
        if not ans:
            return value
        if isinstance(value, list):
            return [] if ans == "-" else [k.strip() for k in ans.split(",") if k.strip()]
        if isinstance(value, bool):
            return ans.lower() in ("y", "yes", "o", "oui")
        if isinstance(value, int):
            return int(ans)
        return ans

    print("\nSearch criteria (Enter = keep, '-' = empty list)")
    c = {
        "query": ask("Job title / keywords to search", last["query"]),
        "location": ask("Location", last["location"]),
        "any_of": ask("Keywords, AT LEAST ONE must appear (comma separated)", last.get("any_of", [])),
        "mandatory": ask("Keywords that ALL must appear (comma, 'a|b' = a or b)", last["mandatory"]),
        "excluded": ask("EXCLUDED keywords, comma separated", last["excluded"]),
        "easy_apply_only": ask("Easy apply only (y/n)", last["easy_apply_only"]),
        "max_pages": ask("Max result pages", last["max_pages"]),
        "search_url": last.get("search_url", ""),
    }
    CRITERIA_FILE.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


# ------------------------------------------------------------------ URLs
def results_url(c: dict, page_no: int) -> str:
    """Page 0, 1, 2... of the results (Indeed: start=0, 10, 20...)."""
    if c.get("search_url"):
        u = urlparse(c["search_url"])
        q = parse_qs(u.query)
        q["start"] = [str(page_no * 10)]
        q.pop("vjk", None)
        return urlunparse(u._replace(query=urlencode(q, doseq=True)))
    url = f"https://fr.indeed.com/jobs?q={quote(c['query'])}&l={quote(c['location'])}"
    if c.get("easy_apply_only"):
        url += "&sc=0kf%3Aattr%28DSQF7%29%3B"
    if page_no:
        url += f"&start={page_no * 10}"
    return url


def offer_url(card: dict, results_page_url: str) -> str:
    """Indeed: the clean offer page viewjob?jk=... ; other sites: the card link."""
    u = urlparse(results_page_url)
    if "indeed." in u.netloc:
        return f"{u.scheme}://{u.netloc}/viewjob?jk={card['jk']}"
    return card["href"]


# ------------------------------------------------------------------ keywords
# Built-in equivalents (FR/EN). Each list = interchangeable spellings of one idea.
SYNONYMS = [
    ["ia", "ai", "intelligence artificielle", "artificial intelligence"],
    ["agent", "agentic", "agentique", "multi-agent", "multiagent"],
    ["llm", "large language model", "grand modele de langage", "modele de langage"],
    ["genai", "ia generative", "ai generative", "generative ai", "gen ai"],
    ["ml", "machine learning", "apprentissage automatique"],
    ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    ["nlp", "traitement du langage naturel", "natural language processing"],
    ["deep learning", "apprentissage profond"],
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower()


def _stem(tok: str) -> str:
    # agents -> agent, modeles -> modele (not "ss": process)
    return tok[:-1] if len(tok) > 3 and tok[-1] in "sx" and not tok.endswith("ss") else tok


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9+#]+", _norm(text))]


def _variants(term: str) -> list[list[str]]:
    """'ai agent' -> every spelling: [ai, agent], [ia, agent], [ia, agentic], [intelligence, artificielle, agent]..."""
    words = _tokens(term)
    phrase = " ".join(words)
    alts_per_word = []
    for group in SYNONYMS:                                   # whole term is a known idea (e.g. "machine learning")
        if phrase in [" ".join(_tokens(g)) for g in group]:
            return [_tokens(g) for g in group]
    for w in words:
        alts = [[w]]
        for group in SYNONYMS:
            if w in [" ".join(_tokens(g)) for g in group]:
                alts = [_tokens(g) for g in group]
                break
        alts_per_word.append(alts)
    out = [[]]
    for alts in alts_per_word:
        out = [o + a for o in out for a in alts][:200]
    return out


def _phrase_in(tokens: list[str], phrase: list[str]) -> bool:
    """All words of the phrase close together, in ANY order ('agents IA' matches 'AI agent')."""
    if len(phrase) == 1:
        return phrase[0] in tokens
    window = len(phrase) + 1                     # words at most ~1 word apart
    first_positions = [i for i, t in enumerate(tokens) if t == phrase[0]]
    for i in first_positions:
        span = tokens[max(0, i - window): i + window + 1]
        if all(w in span for w in phrase[1:]):
            return True
    return False


def term_in(text_tokens: list[str], term: str) -> bool:
    """A term may hold alternatives with '|': 'rag|llm' = rag OR llm."""
    return any(_phrase_in(text_tokens, v) for alt in term.split("|") if alt.strip()
               for v in _variants(alt))


def keyword_check(text: str, c: dict) -> tuple[bool, str, list]:
    """(passes, reason, keywords found).
    any_of    : at least ONE must appear (empty = no constraint)
    mandatory : ALL must appear (each can be 'a|b' = a or b)
    excluded  : NONE may appear
    Case/accent insensitive, plurals, FR/EN synonyms (IA = AI...), word order free."""
    toks = _tokens(text)
    found = [k for k in c.get("any_of", []) + c.get("mandatory", []) if term_in(toks, k)]
    if c.get("any_of") and not any(term_in(toks, k) for k in c["any_of"]):
        return False, "none of: " + ", ".join(c["any_of"]), []
    missing = [k for k in c.get("mandatory", []) if not term_in(toks, k)]
    if missing:
        return False, "missing: " + ", ".join(missing), found
    bad = [k for k in c.get("excluded", []) if term_in(toks, k)]
    if bad:
        return False, "excluded: " + ", ".join(bad), found
    return True, "", found
