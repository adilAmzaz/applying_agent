"""PREFILTER node: free keyword check before the judge (config.toml [prefilter])."""

from core.keywords import keyword_check


def prefilter(text: str, rules: dict) -> tuple[bool, str]:
    if not any(rules.get(k) for k in ("any_of", "mandatory", "excluded")):
        return True, ""
    ok, reason, _ = keyword_check(text, rules)
    return ok, reason
