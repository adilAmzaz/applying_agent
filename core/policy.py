"""
Guardrails, checked in Python BEFORE every action, whatever the LLM decides.
Page text can try to manipulate the LLM: these rules cannot be argued with.

  ALLOW -> runs      ASK -> a human must say yes (unattended: refused)      FORBIDDEN -> never runs

Context (ctx) given by the apply node:
  board_host      host of the job board offer page (fr.indeed.com)
  allow_submit    the final "send" button may be clicked (auto_apply.submit = true)
  approve_legal   privacy / consent boxes may be ticked without asking
  external        following the offer to the company site is allowed
  filled_inputs   number of filled fields on the page (tells "open the form" from "send the form")

Job board offer page = host of the offer, outside the board's own form (Indeed smartapply, LinkedIn Easy Apply
modal = an element inside a dialog). There only the apply buttons may be clicked.
"""

import re
from urllib.parse import urlparse

ALLOW, ASK, FORBIDDEN = "allow", "ask", "forbidden"

# Always the final send button
SUBMIT = re.compile(r"d[ée]poser ma candidature|envoyer (ma|la|votre) candidature|soumettre|submit|send application"
                    r"|confirmer (ma|la) candidature|finaliser (ma|la) candidature|pr[ée]senter (une|ma|la|votre) "
                    r"(demande|candidature)|envoyer (ma|la) demande|complete (my |your )?application|"
                    r"terminer (ma|la) candidature|valider (ma|la) candidature|send my application", re.I)
# "Postuler" / "Apply" / "Envoyer" alone: opens a form (empty page) or sends it (filled page)
AMBIGUOUS_SEND = re.compile(r"^(je postule|postuler|apply|envoyer|send|valider|terminer|finish|candidater)$", re.I)

LEGAL = re.compile(r"approuv|accept|consent|confidentialit|conditions|terms|privacy|politique|j'ai lu|rgpd|gdpr", re.I)
OPT_IN = re.compile(r"alerte|newsletter|recevoir des|offres similaires|marketing|partenaires|subscribe"
                    r"|^suivre |^follow ", re.I)                      # LinkedIn: "Suivre <company>" pre-ticked
# "contact me about future opportunities", talent pool, keep my CV: the candidate WANTS it (never an opt-in to untick)
TALENT = re.compile(r"futur\w* (job |career )?(opportunit|offres?|postes?|positions?|roles?|openings?|vacanc)"
                    r"|other (job |career )?(opportunit|positions|roles|openings)|autres? (opportunit|offres|postes)"
                    r"|talent (pool|community|network)|vivier|cvth[eè]que"
                    r"|(contact|recontact)\w* (me|moi)\b|be (re)?contacted|me (re)?contacter|[eê]tre (re)?contact[ée]"
                    r"|(conserv|garder|keep|retain|store)\w* (mon |ma |mes |my )?(cv|resume|candidature|application|profil|profile)", re.I)
NEGATIVE = re.compile(r"^\s*(no|non)\b|do not|don.t|ne pas|ne souhaite pas|refuse", re.I)
# Passkey / security key / Windows Hello enrolment (iCIMS login "mfa-webauthn-platform-enrollment"): NEVER created.
# Only the "later / not now / skip" buttons may be clicked there.
PASSKEY_PAGE = re.compile(r"webauthn|passkey|mfa-[\w-]*enroll|security-?key", re.I)
PASSKEY_BTN = re.compile(r"passkey|cl[ée] d.acc[eè]s|cl[ée] (de s[ée]curit[ée]|d.identification)|security key|"
                         r"windows hello|face id|touch id|empreinte|biom[ée]tri", re.I)
LATER_BTN = re.compile(r"plus tard|later|pas maintenant|not now|skip|ignorer|passer|non merci|no,? thanks|"
                       r"pas sur cet appareil|not on this device|remind me|me rappeler|annuler|cancel", re.I)
LEGAL_LINK = re.compile(r"^(cgu|cgv|privacy( policy| notice)?|politique de (confidentialit[ée]|protection)|"
                        r"conditions g[ée]n[ée]rales|mentions l[ée]gales|terms( of (use|service))?|cookie policy|"
                        r"politique (des )?cookies|rgpd|gdpr|data protection)", re.I)
DANGEROUS = re.compile(r"supprimer|delete|retirer|se d[ée]connecter|log ?out|sign ?out", re.I)
# Needs a password / identity: always handed back to the human
ACCOUNT = re.compile(r"cr[ée]er (un |mon )?compte|create (an )?account|s'inscrire|sign ?up|register|inscription"
                     r"|se connecter|connexion|sign ?in|log ?in|mot de passe oubli", re.I)

# Single sign-on: never (your Google / LinkedIn / Microsoft... account is not for recruitment sites)
SSO = re.compile(r"(continuer|continue|connexion|se connecter|sign ?in|log ?in|s.inscrire|sign ?up|postuler|apply)"
                 r"\s+(avec|with|via|par)\s+(google|linkedin|microsoft|apple|facebook|indeed|github|yahoo)|"
                 r"^(google|linkedin|microsoft|apple|facebook)$", re.I)
FORGOT = re.compile(r"mot de passe oubli|forgot|reset (your )?password|r[ée]initialis", re.I)
# Default account ([accounts] in config.toml): only on recruitment sites, never on these
NO_ACCOUNT_HOSTS = re.compile(r"(^|\.)(google|gmail|linkedin|microsoft|microsoftonline|live|outlook|apple|icloud|"
                              r"facebook|indeed|github|yahoo)\.", re.I)


def accounts_allowed(url: str, ctx: dict) -> bool:
    return bool(ctx.get("accounts")) and not NO_ACCOUNT_HOSTS.search(host(url) + ".")


# Job board offer page: what may be clicked there
BOARD_SIDE_EFFECT = re.compile(r"activer|alerte|s'abonner|pas int[ée]ress|not interested|save job|enregistrer"
                               r"|sauvegarder|partager|share|suivre|follow|signaler|report", re.I)
EASY_START = re.compile(r"postuler maintenant|candidature simplifi[ée]e|apply now|easily apply|easy apply"
                        r"|continuer (ma|la|votre) candidature|continuer pour candidater"   # HelloWork step 1 (not "pour postuler": company site)
                        r"|continue (my |your )?application", re.I)
EXTERNAL_START = re.compile(r"continuer pour postuler|postuler sur le site|apply on company site|candidater sur le site"
                            r"|site (web )?de l.entreprise|site du recruteur|company website|^postuler( [àa] .*)?$"
                            r"|^apply( to .*)?$"
                            r"|^je postule$|^candidater$", re.I)   # Free-Work: "Les candidatures se font directement
                                                                     # sur le site du recruteur" + "Je postule"
BOARD_FORM_URL = re.compile(r"smartapply\.indeed\.com|/apply(/|\?|$)", re.I)    # the board's own application form


def host(url: str) -> str:
    return urlparse(url or "").netloc.lower()


def on_board_offer_page(url: str, ctx: dict, el: dict | None = None) -> bool:
    if (el or {}).get("in_dialog") or (el or {}).get("in_apply_form"):   # modal / form on the offer page
        return False
    return host(url) == ctx.get("board_host") and not BOARD_FORM_URL.search(url or "")


def check(action: str, el: dict, url: str, ctx: dict, value=None) -> tuple[str, str]:
    name = (el.get("name") or "").strip()
    typ = (el.get("type") or "").lower()

    if action == "fill_password":                     # the default account's password, typed by the tool
        if typ != "password":
            return FORBIDDEN, "fill_password only works on a password field"
        if not accounts_allowed(url, ctx):
            return FORBIDDEN, ("no default account on this site (disabled, or a Google / LinkedIn / Microsoft... "
                               "page): wait_for_human('log in') -- unattended: finish(status='needs_human')")
        return ALLOW, ""
    if typ == "password" or (action in ("type", "select") and re.search(r"mot de passe|password", name, re.I)):
        if accounts_allowed(url, ctx):
            return FORBIDDEN, "never type a password yourself: fill_password(ref) types the default account's password"
        return FORBIDDEN, "never type passwords: call wait_for_human('log in') -- unattended: finish(status='needs_human')"
    if typ == "file" and action != "upload_cv":
        return FORBIDDEN, "use upload_cv for file inputs"

    if action == "upload_cv":                          # always the configured CV: the tool finds the file input
        return ALLOW, ""

    if action == "click":
        if PASSKEY_PAGE.search(url) or PASSKEY_BTN.search(name):
            if LATER_BTN.search(name):
                return ALLOW, ""
            return FORBIDDEN, ("never create a passkey / security key (Windows Hello pops up): click 'Me rappeler plus "
                               "tard' / 'Not now' / 'Skip' / 'Pas sur cet appareil'")
        if SSO.search(name):
            return FORBIDDEN, "never log in with Google / LinkedIn / Microsoft...: use the email + password account"
        if FORGOT.search(name):
            return FORBIDDEN, "no password reset: wait_for_human('log in')"
        if ACCOUNT.search(name):
            if accounts_allowed(url, ctx) and not on_board_offer_page(url, ctx, el):
                return ALLOW, "account"
            return FORBIDDEN, ("login / account creation is for the human: call wait_for_human('log in / create the "
                               "account on this site') -- unattended: finish(status='needs_human')")
        if DANGEROUS.search(name):
            return FORBIDDEN, f"dangerous button '{name[:40]}'"
        if (el.get("role") in ("a", "link")) and LEGAL_LINK.search(name):    # opened a CGU / privacy tab, got lost
            return FORBIDDEN, "no need to read the legal pages: tick the consent checkbox and go on"
        board_page = on_board_offer_page(url, ctx, el)
        # on the offer page, "Postuler" opens the form (the search box being filled does not make it a send)
        is_submit = SUBMIT.search(name) or (not board_page and AMBIGUOUS_SEND.search(name)
                                            and ctx.get("filled_inputs", 0) >= 2)
        if is_submit:
            if ctx.get("allow_submit"):
                return ALLOW, "submit"
            return FORBIDDEN, "final send button: stop here and call finish(status='ready_for_review')"

        if board_page:                                    # job board: only the apply buttons
            # the name must START with the apply words: a job card "AI Engineer ... Candidature simplifiée" is
            # another offer, never an apply button
            starts = EASY_START.match(name) or EXTERNAL_START.match(name)
            if (EASY_START.search(name) or EXTERNAL_START.search(name)) and not starts:
                return FORBIDDEN, f"'{name[:50]}' is a link to ANOTHER offer, not the apply button"
            if starts and ctx.get("offer_key"):
                from core.db import job_identity
                if job_identity(url) != tuple(ctx["offer_key"]):
                    return FORBIDDEN, ("this page is not the offer you are applying to (another job / a search "
                                       "page): finish(status='stuck') and say so")
            if EASY_START.match(name):
                return ALLOW, ""
            if EXTERNAL_START.match(name):
                return (ALLOW, "") if ctx.get("external") else \
                    (FORBIDDEN, "external sites disabled: finish(status='needs_human')")
            if BOARD_SIDE_EFFECT.search(name):
                return FORBIDDEN, f"'{name[:40]}' changes the account (save/alert/not interested/share)"
            return FORBIDDEN, "on the job page, only the apply button may be clicked"

        if ((el.get("in_dialog") or el.get("in_apply_form")) and host(url) == ctx.get("board_host") and typ not in ("checkbox", "radio")
                and BOARD_SIDE_EFFECT.search(name)):     # LinkedIn modal: "Enregistrer" (save draft), "Partager"...
            return FORBIDDEN, f"'{name[:40]}' changes the account (save/share/follow)"
        if typ in ("checkbox", "radio") and TALENT.search(name):
            return ALLOW, ""                             # future opportunities: wanted (yes / no picked by the rules)
        if typ in ("checkbox", "radio") and LEGAL.search(name):
            return (ALLOW, "") if ctx.get("approve_legal") else (ASK, "this accepts a legal notice for the candidate")
        if typ in ("checkbox", "radio") and OPT_IN.search(name):
            return FORBIDDEN, "use set_checked(ref, false) for opt-ins"
        if OPT_IN.search(name):
            return FORBIDDEN, f"'{name[:40]}' subscribes to something"
        return ALLOW, ""

    if action == "check":
        if TALENT.search(name):
            return ALLOW, ""
        if LEGAL.search(name):
            return (ALLOW, "") if ctx.get("approve_legal") else (ASK, "this accepts a legal notice for the candidate")
        if OPT_IN.search(name):
            return FORBIDDEN, "never opt in to alerts or marketing"
        return ALLOW, ""

    if action in ("uncheck", "type", "select"):
        return ALLOW, ""

    return ASK, f"unknown action '{action}'"
