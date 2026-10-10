"""Same job, different links/spellings -> same fingerprint. Different jobs -> different."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import fingerprint as fp

same = [
    (("ACME IA SAS", "AI Engineer (H/F) - Paris (75)"), ("Acme IA", "AI Engineer H/F")),
    (("Gestinnov", "AI Agent Engineer (H/F) – CDI – Télétravail"), ("GESTINNOV", "AI Agent Engineer F/H")),
    (("Capgemini France", "Ingénieur IA Générative"), ("Capgemini", "Ingenieur IA generative - 92130")),
]
different = [
    (("ACME IA", "AI Engineer"), ("ACME IA", "Data Engineer")),
    (("ACME IA", "AI Engineer"), ("Beta", "AI Engineer")),
]
for a, b in same:
    assert fp(*a) == fp(*b), (a, b, fp(*a), fp(*b))
for a, b in different:
    assert fp(*a) != fp(*b), (a, b)
assert fp(None, "AI Engineer") is None
print("ALL FINGERPRINT CHECKS PASSED")
