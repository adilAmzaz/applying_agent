"""Unit tests of the guardrails (no browser)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.policy import check, ALLOW, ASK, FORBIDDEN

B = "https://fr.indeed.com/viewjob?jk=1"
FORM = "https://smartapply.indeed.com/beta/indeedapply/form/q"
EXT = "https://careers.delta.com/apply"
ctx = {"board_host": "fr.indeed.com", "external": True, "allow_submit": False, "approve_legal": False, "filled_inputs": 0}
btn = lambda n, t="submit": {"name": n, "type": t}

cases = [
    # job board offer page: only apply buttons
    ("click", btn("Postuler maintenant"), B, ctx, ALLOW),
    ("click", btn("Continuer pour postuler"), B, ctx, ALLOW),
    ("click", btn("Je postule"), B, ctx, ALLOW),                 # Free-Work: to the recruiter's site
    ("click", btn("Continuer pour postuler"), B, {**ctx, "external": False}, FORBIDDEN),
    ("click", btn("Activer"), B, ctx, FORBIDDEN),
    ("click", btn("Enregistrer l'offre"), B, ctx, FORBIDDEN),
    ("click", btn("tous les détails sur AI Engineer"), B, ctx, FORBIDDEN),
    # forms (board form or company site)
    ("click", btn("Continuer"), FORM, ctx, ALLOW),
    ("click", btn("Enregistrer et continuer"), EXT, ctx, ALLOW),       # normal on company sites
    ("click", btn("Déposer ma candidature"), FORM, ctx, FORBIDDEN),
    ("click", btn("Déposer ma candidature"), FORM, {**ctx, "allow_submit": True}, ALLOW),
    ("click", btn("Postuler"), EXT, ctx, ALLOW),                         # empty page: opens the form
    ("click", btn("Postuler"), EXT, {**ctx, "filled_inputs": 3}, FORBIDDEN),   # filled page: sends it
    ("click", btn("Créer un compte"), EXT, ctx, FORBIDDEN),
    ("click", btn("Se connecter"), EXT, ctx, FORBIDDEN),
    ("click", btn("S'abonner à la newsletter"), EXT, ctx, FORBIDDEN),
    ("type", {"name": "Mot de passe", "type": "password"}, EXT, ctx, FORBIDDEN),
    ("type", {"name": "Nom", "type": "text"}, EXT, ctx, ALLOW),
    ("check", {"name": "J'accepte la politique de confidentialité", "type": "checkbox"}, EXT, ctx, ASK),
    ("check", {"name": "J'accepte la politique de confidentialité", "type": "checkbox"}, EXT, {**ctx, "approve_legal": True}, ALLOW),
    ("check", {"name": "Recevoir des alertes", "type": "checkbox"}, EXT, ctx, FORBIDDEN),
    ("uncheck", {"name": "Recevoir des alertes", "type": "checkbox"}, EXT, ctx, ALLOW),
    ("upload_cv", {"name": "CV", "type": "file"}, EXT, ctx, ALLOW),
    ("type", {"name": "CV", "type": "file"}, EXT, ctx, FORBIDDEN),
]
bad = 0
for action, el, url, c, expected in cases:
    got, reason = check(action, el, url, c)
    ok = got == expected
    bad += not ok
    print(("ok  " if ok else "FAIL"), f"{action:9} {el['name'][:38]:38} -> {got:9} {reason[:50]}")
assert not bad, f"{bad} policy cases failed"
print("\nALL POLICY CHECKS PASSED")
