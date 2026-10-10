"""
AUTOPILOT values: what to put in a form field WITHOUT asking the LLM.

  value_for(label, kind, options, profile) -> str | None
    kind: "text" | "number" | "select" | "radio" | "textarea"
Sources, in order: answers learned from earlier applications (profile "form_answers"), the identity,
years of experience per technology, languages, availability, notice period. None = the LLM decides.

learn(...) stores the answers the LLM gave to NEW questions into profile "form_answers" at the end of an
application that went through (sensitive questions are never learned).
"""

import json
import re
import unicodedata
from datetime import datetime

from core.policy import NEGATIVE, TALENT

YES = re.compile(r"^(yes|oui|i agree|j.accepte|accept|agree|d.accord|ok)\b", re.I)

SENSITIVE = re.compile(r"handicap|rqth|sant[ée]|health|disab|religio|origine|ethni|race|genre|gender|sexe|"
                       r"orientation|nationalit|ressortissant|citizen|titre de s[ée]jour|visa|work (permit|authori)|"
                       r"autoris[ée] [àa] travailler|permis de travail|sponsor|v[ée]t[ée]ran|politi|syndic|date de naissance|"
                       r"birth|[âa]ge\b|salaire actuel|current salary|password|mot de passe", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\[question:", " ", s)
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", s).split())


def question_of(label: str) -> str:
    """'Oui [question: Êtes-vous ...]' -> 'Êtes-vous ...' ; 'Ville*' -> 'Ville'."""
    m = re.search(r"\[question:\s*(.+?)\]\s*$", label or "")
    return (m.group(1) if m else label or "").strip().rstrip("*✱").strip()


# identity fields: label pattern -> profile identity key
IDENTITY = [
    (r"^(pr[ée]nom|first name|given name)", "first_name"),
    (r"^(nom de famille|last name|family name|surname|^nom$)|^nom\b(?!.*(entreprise|soci[ée]t[ée]|company|[ée]cole))", "last_name"),
    (r"(nom complet|full name|^name$|^nom et pr[ée]nom)", "full_name"),
    (r"(e-?mail|\bmail\b|courriel|adresse [ée]lectronique)", "email"),     # "Adresse mail" (iCIMS) is the email
    (r"(t[ée]l[ée]phone|phone|mobile|portable)", "phone"),
    (r"(code postal|postal|zip)", "postal_code"),
    (r"^(ville|city|localit[ée])|current location|lieu de r[ée]sidence", "city"),
    (r"^(adresse|address|rue|street)(?!.*(e-?mail|\bmail\b|courriel|[ée]lectronique))", "address"),
    (r"^(pays|country)$", "country"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"(site web|website|portfolio)", "portfolio"),
    (r"^(civilit[ée]|titre|title|pr[ée]fixe|salutation)$", "civility"),
]

# about SOMEONE ELSE (Capco: "Capco employee email address"): never your identity
OTHER_PERSON = re.compile(r"employee|employ[ée]|referr|r[ée]f[ée]r|parrain|coopt|manager|recruiter|recruteur|"
                          r"contact person|personne [àa] contacter|emergency|urgence|reference", re.I)

YEARS_Q = re.compile(r"combien d.ann[ée]es|how many years|years of (work )?experience|ann[ée]es d.exp[ée]rience|"
                     r"nombre d.ann[ée]es", re.I)
YEARS_KEYS = [  # (pattern in the question, profile years_experience key)
    (r"python", "python"),
    (r"\bjava\b|spring", "java_spring"),
    (r"machine learning|\bml\b|\bia\b|\bai\b|intelligence artificielle|deep learning|llm|nlp|data scien|g[ée]n[ée]rati|mlops", "ai_ml"),
    (r"d[ée]veloppement|software|logiciel|programm|informatique|ing[ée]nierie", "software_engineering_total"),
]
LANG_LEVEL = {"bilingual": ["Bilingue", "Natif ou bilingue", "Native or bilingual", "Courant", "Fluent"],
              "native": ["Langue maternelle", "Native", "Natif ou bilingue", "Bilingue", "Courant"],
              "fluent": ["Courant", "Professionnel", "Fluent", "Professional", "Professional working proficiency",
                         "Avancé", "Advanced", "C1"],
              "intermediate": ["Intermédiaire", "Intermediate", "Limited working proficiency", "B1", "B2"]}
LANGS = {"anglais|english": "English", "fran[çc]ais|french": "French", "arabe|arabic": "Arabic",
         "espagnol|spanish": "Spanish"}


DISABILITY = re.compile(r"handicap|rqth|disab|travailleur handicap|boeth|situation de handicap|"
                        r"reasonable adjustment|accommodation|am[ée]nagement (de poste|raisonnable)", re.I)
NO_ANSWER = re.compile(r"^\s*(non|no)\b|pas reconnu|not recogni|je ne suis pas|i am not|n.ai pas|aucun|none", re.I)
DECLINE = re.compile(r"ne souhaite pas|pr[ée]f[èe]re ne pas|prefer not|decline|ne pas r[ée]pondre", re.I)


def _disability(kind: str, options: list | None, profile: dict) -> str | None:
    """RQTH / handicap: answered ONLY if profile "sensitive_answers" says so (you: "no")."""
    ans = str((profile.get("sensitive_answers") or {}).get("handicap_rqth", "")).strip().lower()
    if ans not in ("no", "non"):
        return None                                  # nothing stated: the human decides
    if kind in ("radio", "select"):
        return next((o for o in options or [] if NO_ANSWER.search(o) and not DECLINE.search(o)), None)
    return "Non"


def _years(q: str, profile: dict) -> str | None:
    ye = profile.get("years_experience") or {}
    for pat, key in YEARS_KEYS:
        if re.search(pat, q, re.I):
            v = str(ye.get(key, ""))
            m = re.search(r"\d+", v)
            return m.group(0) if m else None
    return None


MOBILITY_Q = re.compile(r"mobilit|mobility|relocat|d[ée]m[ée]nag|zone g[ée]ographique|r[ée]gions? souhait|"
                        r"villes? souhait|preferred (work )?(location|city|cities|region)|o[uù] (souhaitez|aimeriez|voulez)"
                        r"|willing to (move|relocate|work in)|lieu de travail souhait|secteur g[ée]ographique|"
                        r"[êe]tes[- ]vous mobile|are you mobile|mobile g[ée]ographiquement", re.I)
EVERYWHERE = re.compile(r"france enti[èe]re|toute la france|partout|national|nationwide|all (of )?france|"
                        r"whole (of )?france|anywhere|toutes (les )?r[ée]gions|all regions|^france$|^fr$", re.I)
REGION_OF = {"paris": r"[iî]le[- ]de[- ]france|\bidf\b|paris region|r[ée]gion parisienne",
             "marseille": r"paca|provence|sud[- ]est|south[- ]?east|m[ée]diterran", "nice": r"paca|c[ôo]te d.azur|sud[- ]est|south[- ]?east",
             "lille": r"hauts[- ]de[- ]france|\bnord\b|north", "lyon": r"auvergne|rh[ôo]ne", "toulouse": r"occitanie|sud[- ]ouest|south[- ]?west"}


def _mobility(kind: str, options: list | None, profile: dict) -> str | None:
    """Where you can work: "all France / partout" first, else Paris / Île-de-France, else your other cities,
    else their regions (profile "mobility")."""
    cities = [c for c in profile.get("mobility") or [] if c]
    if not cities:
        return None
    if kind in ("radio", "select"):
        opts = [o for o in options or [] if o and not re.match(r"^(s[ée]lectionnez|select|choisissez|--)", o, re.I)]
        if opts and all(re.match(r"^\s*(oui|non|yes|no)\b", o, re.I) for o in opts):
            return next((o for o in opts if YES.match(o.strip())), None)          # "Êtes-vous mobile ?" -> Oui
        for o in opts:
            if EVERYWHERE.search(o.strip()):
                return o
        for city in cities:
            for o in opts:
                if norm(city) in norm(o):
                    return o
        for city in cities:
            pat = REGION_OF.get(norm(city))
            for o in opts:
                if pat and re.search(pat, o, re.I):
                    return o
        return None
    if kind == "search":
        return cities[0]
    return "Toute la France (" + ", ".join(cities) + ")"


def mobility_boxes(question: str, labels: list[str], profile: dict) -> list[str]:
    """Tick-boxes of a mobility question: "partout / toute la France" alone if offered, else your cities and
    their regions."""
    cities = [c for c in profile.get("mobility") or [] if c]
    if not cities or not MOBILITY_Q.search(question or ""):
        return []
    every = [l for l in labels if EVERYWHERE.search(l.strip())]
    if every:
        return every[:1]
    pats = [re.escape(norm(c)) for c in cities] + [REGION_OF[norm(c)] for c in cities if norm(c) in REGION_OF]
    return [l for l in labels if any(re.search(p, norm(l)) or re.search(p, l, re.I) for p in pats)]


def value_for(label: str, kind: str, options: list | None, profile: dict) -> str | None:
    q = question_of(label)
    nq = norm(q)
    if nq and MOBILITY_Q.search(q) and not SENSITIVE.search(q):
        return _mobility(kind, options, profile)
    if kind == "search":
        kind = "text"
    if nq and DISABILITY.search(q):                  # only what you stated in profile "sensitive_answers"
        return _disability(kind, options, profile)
    if not nq or SENSITIVE.search(q):
        return None
    if TALENT.search(q) and profile.get("consent_future_opportunities", True):
        if kind in ("radio", "select"):                  # "contact me about future opportunities": YES
            return next((o for o in options or [] if YES.match(o.strip()) and not NEGATIVE.search(o)), None)
        return None
    learned = {norm(k): v for k, v in (profile.get("form_answers") or {}).items()}
    if nq in learned:
        return str(learned[nq])
    ident = profile.get("identity") or {}
    if re.search(r"pr[ée]fixe|indicatif|country code|dial(ing)? code|code (du )?pays|phone code", q, re.I):
        cc = (re.match(r"\+\d{1,3}", str(ident.get("phone", ""))) or [None])[0]      # "+33 6 18..." -> "+33"
        if not cc:
            return None
        if kind == "select":                             # "France (+33)" among 200 countries
            country = str(ident.get("country", ""))
            hits = [o for o in options or [] if re.search(re.escape(cc) + r"(?!\d)", o)]
            return next((o for o in hits if country and norm(country) in norm(o)), hits[0] if hits else None)
        return cc
    if kind in ("text", "select", "number") and len(q) < 60 and not OTHER_PERSON.search(q):
        for pat, key in IDENTITY:
            if re.search(pat, q, re.I):
                v = ident.get(key)
                if key == "phone" and kind == "text":
                    v = ident.get("phone_national") or v
                if v and "TO FILL" not in str(v):
                    return str(v)
                return None
    if YEARS_Q.search(q):
        return _years(q, profile)
    if re.search(r"disponib|availability|start date|date de d[ée]but|quand pouvez", q, re.I):
        if kind == "select":
            return "Immédiatement"
        return datetime.now().strftime("%d/%m/%Y") if re.search(r"date", q, re.I) else profile.get("notice_period")
    if re.search(r"pr[ée]avis|notice period", q, re.I):
        return profile.get("notice_period")
    for pat, lang in LANGS.items():
        if re.search(pat, q, re.I) and re.search(r"niveau|level|ma[îi]trise|proficien|parlez", q, re.I):
            level = str((profile.get("languages") or {}).get(lang, "")).lower()
            for opt in LANG_LEVEL.get(level, []):
                if not options or any(norm(opt) == norm(o) for o in options):
                    return opt
    if re.search(r"comment (nous )?avez.vous (connu|entendu)|how did you hear", q, re.I):
        return "LinkedIn"
    return None


def learn(profile_path, entries: list[tuple[str, str]], company: str = "") -> int:
    """entries: (label, value) the LLM filled in an application that went through. Returns how many were added."""
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    known = profile.setdefault("form_answers", {})
    added = 0
    for label, value in entries:
        q, v = question_of(label), (value or "").strip()
        if (not q or not v or len(v) > 80 or len(q) < 4 or SENSITIVE.search(q)
                or (company and norm(company) and norm(company) in norm(q))
                or value_for(label, "text", None, {**profile, "form_answers": {}}) is not None):
            continue                                     # identity & co are already known; company-specific skipped
        if norm(q) not in {norm(k) for k in known}:
            known[q] = v
            added += 1
    if added:
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return added
