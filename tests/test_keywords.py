"""Unit tests of the free keyword prefilter."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.keywords import keyword_check

cases = [
    ("AI Agent Engineer, vous construirez des agents IA", {"any_of": ["rag", "ai agent", "ia"]}, True),
    ("Développeur C++ 20 temps réel", {"any_of": ["rag", "ai agent", "ia"]}, False),
    ("Spécialiste réseaux sociaux", {"any_of": ["ia"]}, False),                    # "ia" not inside "sociaux"
    ("Agentic AI developer", {"mandatory": ["ai agent"]}, True),
    ("Agent commercial B2B, automatisation & IA", {"mandatory": ["ai agent"]}, False),
    ("Agents IA et RAG", {"mandatory": ["ai agent", "rag|llm"]}, True),
    ("Stage IA de 6 mois", {"any_of": ["ia"], "excluded": ["stage"]}, False),
    ("machine learning engineer", {"any_of": ["ml"]}, True),
    ("Retrieval-Augmented Generation", {"any_of": ["rag"]}, True),
]
for text, rules, expected in cases:
    got = keyword_check(text, rules)
    assert got[0] == expected, (text, rules, got)
print("ALL KEYWORD CHECKS PASSED")
