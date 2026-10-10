"""
FEEDBACK node: turn your decisions into examples for the judge (judge/examples.md).
The more examples, the better the judge -- but each example costs tokens on every judge call:
keep ~10-20 short ones, the most telling.
"""

import json

from core.config import CONFIG, ROOT


def add_example(row, label: str, why: str = "") -> str:
    """row = applications row. label = high | maybe | low."""
    skills = row["skills"]
    try:
        skills = ", ".join(json.loads(skills)) if skills else ""
    except (ValueError, TypeError):
        pass
    block = (f"\n## Example #{row['id']} -> {label.upper()}\n"
             f"- Title: {row['title']}\n- Company: {row['company']} | {row['location'] or ''} | "
             f"{row['contract_type'] or ''} | {row['remote'] or ''}\n"
             f"- Skills: {skills}\n- Mission: {row['summary'] or (row['description'] or '')[:300]}\n"
             + (f"- Why: {why}\n" if why else ""))
    path = ROOT / CONFIG["judge"]["examples_file"]
    path.parent.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    return str(path)
