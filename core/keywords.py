"""Free keyword filter (no LLM): case/accent/plural/word-order insensitive, FR/EN synonyms."""

import re
import unicodedata

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
