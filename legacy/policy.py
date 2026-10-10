"""
Guardrails. Pure Python, checked BEFORE every action, whatever the LLM decides.
The LLM can be wrong or manipulated by page text: these rules cannot be argued with.

  ALLOW     -> action runs
  ASK       -> the human must say yes in the terminal
  FORBIDDEN -> never runs, the LLM is told why
"""

import re

ALLOW, ASK, FORBIDDEN = "allow", "ask", "forbidden"

# Final submit buttons: the human always clicks these himself.
SUBMIT = re.compile(r"d[ée]poser ma candidature|envoyer (ma|la) candidature|soumettre|submit|send application"
                    r"|^envoyer$|^postuler$|confirmer (ma|la) candidature", re.I)

# Checking these means accepting something legal on the candidate's behalf.
LEGAL = re.compile(r"approuv|accept|consent|confidentialit|conditions|terms|privacy|politique|j'ai lu|rgpd|gdpr", re.I)

# Opt-ins nobody asked for (job alerts, newsletters...).
OPT_IN = re.compile(r"alerte|newsletter|recevoir des|offres similaires|marketing|partenaires", re.I)

# Leaving the flow or destroying the draft.
DANGEROUS_CLICK = re.compile(r"supprimer|delete|retirer|se d[ée]connecter|log ?out|sign ?out", re.I)

# Account side effects seen in a real run: saving the job, "not interested", creating a job alert.
SIDE_EFFECT_CLICK = re.compile(r"activer|cr[ée]er (une )?alerte|alerte|s'abonner|subscribe|pas int[ée]ress|not interested"
                               r"|save job|enregistrer|sauvegarder|partager|share|suivre|follow|signaler|report", re.I)

# Outside the application form (search results, job page) the ONLY allowed clicks are these:
APPLY_START = re.compile(r"postuler maintenant|candidature simplifi[ée]e|apply now|easily apply", re.I)
APPLY_FORM_URL = re.compile(r"smartapply\.indeed\.com|/apply|candidature", re.I)


def check(action: str, el: dict, value=None, url: str = "") -> tuple[str, str]:
    name = el.get("name", "")
    typ = (el.get("type") or "").lower()
    in_form = bool(APPLY_FORM_URL.search(url))

    if typ == "password" or re.search(r"mot de passe|password", name, re.I):
        return FORBIDDEN, "never type into password fields"
    if typ == "file":
        return FORBIDDEN, "file upload is not handled by the agent: the CV is chosen by the human"

    if action == "click":
        if SUBMIT.search(name):
            return FORBIDDEN, "final submit button: the human clicks it himself after review"
        if DANGEROUS_CLICK.search(name):
            return FORBIDDEN, f"dangerous button '{name[:40]}'"
        if SIDE_EFFECT_CLICK.search(name):
            return FORBIDDEN, f"'{name[:40]}' changes the account (save/alert/not interested/share)"
        if not in_form and not APPLY_START.search(name):
            return FORBIDDEN, ("outside the application form the only allowed click is the easy-apply button "
                               "('Postuler maintenant'). 'Continuer pour postuler' = external site: finish(status='external_apply')")
        if LEGAL.search(name) and typ in ("checkbox", "radio"):
            return ASK, "this click would accept a legal notice for you"
        if OPT_IN.search(name) and typ in ("checkbox", "radio"):
            return FORBIDDEN, "use set_checked to turn opt-ins off, never click them blindly"
        return ALLOW, ""

    if action == "check":
        if LEGAL.search(name):
            return ASK, "checking this accepts a legal notice / consent on your behalf"
        if OPT_IN.search(name):
            return FORBIDDEN, "never opt in to alerts or marketing"
        return ALLOW, ""

    if action == "uncheck":
        return ALLOW, ""          # turning things off is always safe here

    if action in ("type", "select"):
        return ALLOW, ""          # answers are logged; the human reviews everything before submitting

    return ASK, f"unknown action '{action}'"
