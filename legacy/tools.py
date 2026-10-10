"""
Browser tools the LLM can call. Each action:
  1. checks the policy (policy.py) BEFORE touching the page
  2. acts on the element tagged data-agent-ref="eN" by the last scan
  3. waits, re-scans, VERIFIES the result, saves a screenshot
  4. returns the new page state as text (what the LLM sees next)
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from explore import SCAN_JS, Session
import policy

# Elements that are never useful for filling a form: navigation noise
NOISE = {
    "passer au contenu principal", "skip to main content", "logo indeed", "page d'accueil",
    "avis sur les entreprises", "estimation de salaire", "mes emplois", "compte",
    "entreprises / publier une offre d'emploi", "signaler un problème",
}


class BrowserTools:
    def __init__(self, session: Session, run_dir: Path, ask_human):
        self.s = session
        self.run_dir = run_dir
        self.ask_human = ask_human          # function(question) -> str
        self.elements: dict[str, dict] = {}  # ref -> element from the last scan
        self.n = 0                           # screenshot counter
        self.log = (run_dir / "actions.jsonl").open("a", encoding="utf-8")

    # ---------- observation ----------
    @property
    def page(self) -> Page:
        return self.s.active_page()

    def _scan(self) -> list[dict]:
        p = self.page
        p.wait_for_load_state("domcontentloaded")
        time.sleep(1.2)
        els = p.evaluate(SCAN_JS)
        self.elements = {e["ref"]: e for e in els}
        self.n += 1
        p.screenshot(path=str(self.run_dir / f"{self.n:02d}.png"))
        return els

    def read_page(self) -> str:
        """Compact, filtered view of the page: title, headings, form elements."""
        els = self._scan()
        p = self.page
        headings = p.evaluate(
            "() => [...document.querySelectorAll('h1,h2,h3,legend')]"
            ".map(h => h.innerText.trim()).filter(Boolean).slice(0, 12)")
        lines = [f"TITLE: {p.title()}", f"URL: {p.url[:120]}",
                 "HEADINGS: " + " | ".join(h[:80] for h in headings), "ELEMENTS:"]
        for e in els:
            name = e["name"].lower()
            keep_link = re.search(r"postuler|apply|candidature", name)      # apply buttons are sometimes links
            if name in NOISE or (e["role"] in ("a", "link") and not e["required"] and not keep_link):
                continue
            kind = e["role"] + (f":{e['type']}" if e["type"] and e["role"] in ("input", "switch") else "")
            s = f"  [{e['ref']}] {kind} \"{e['name'][:90]}\""
            if e["value"]:
                s += f" value=\"{e['value']}\""
            if e["checked"] is not None:
                s += f" checked={str(e['checked']).lower()}"
            if e["required"]:
                s += " REQUIRED"
            if e["disabled"]:
                s += " DISABLED"
            lines.append(s)
        return "\n".join(lines)

    def get_text(self) -> str:
        """Main visible text (questions, job description), truncated."""
        txt = self.page.evaluate("() => (document.querySelector('main') || document.body).innerText")
        return txt[:4000]

    # ---------- actions ----------
    def _el(self, ref):
        if ref not in self.elements:
            raise ValueError(f"unknown ref {ref}: call read_page first")
        return self.page.locator(f'[data-agent-ref="{ref}"]').first, self.elements[ref]

    def _guard(self, action: str, el: dict, value=None) -> str | None:
        """Returns None if allowed, else a message for the LLM."""
        verdict, reason = policy.check(action, el, value, url=self.page.url)
        self._write("policy", action=action, el=el["name"], value=value, verdict=verdict, reason=reason)
        if verdict == policy.FORBIDDEN:
            return f"BLOCKED by policy: {reason}. Do not retry this action."
        if verdict == policy.ASK:
            ans = self.ask_human(f"{reason}\n  -> {action} \"{el['name']}\" {'' if value is None else value}\n  Allow? [y/N] ")
            if ans.strip().lower() not in ("y", "yes", "o", "oui"):
                return "DENIED by the human. Do not retry. Continue otherwise or finish."
        return None

    def click(self, ref: str) -> str:
        loc, el = self._el(ref)
        if (msg := self._guard("click", el)):
            return msg
        loc.scroll_into_view_if_needed()
        loc.click()
        self._write("click", ref=ref, el=el["name"])
        return "clicked.\n" + self.read_page()

    def type_text(self, ref: str, text: str) -> str:
        loc, el = self._el(ref)
        if (msg := self._guard("type", el, text)):
            return msg
        loc.scroll_into_view_if_needed()
        loc.fill(text)
        actual = loc.input_value()
        self._write("type", ref=ref, el=el["name"], text=text, verified=actual == text)
        return f"typed (field now contains: \"{actual[:80]}\").\n" + self.read_page()

    def select_option(self, ref: str, option: str) -> str:
        loc, el = self._el(ref)
        if (msg := self._guard("select", el, option)):
            return msg
        loc.scroll_into_view_if_needed()
        loc.select_option(label=option)
        self._write("select", ref=ref, el=el["name"], option=option)
        return "selected.\n" + self.read_page()

    def set_checked(self, ref: str, checked: bool) -> str:
        """Checkbox / switch / radio. Reads the REAL state before and after (not the label)."""
        loc, el = self._el(ref)
        state = lambda: loc.evaluate(
            "e => e.checked ?? (e.getAttribute('aria-checked') === 'true')")
        loc.scroll_into_view_if_needed()
        before = state()
        if before == checked:               # nothing to change: no policy question needed
            return f"already {checked}: \"{el['name'][:60]}\". Nothing done.\n" + self.read_page()
        if (msg := self._guard("check" if checked else "uncheck", el)):
            return msg
        if before != checked:
            loc.click()
            time.sleep(0.6)
        after = state()
        self._write("set_checked", ref=ref, el=el["name"], wanted=checked, before=before, after=after)
        if after != checked:
            return f"FAILED: state is still {after}. Look at the page again before retrying."
        return f"verified: \"{el['name'][:60]}\" is now {after}.\n" + self.read_page()

    # ---------- logging ----------
    def _write(self, kind, **kw):
        self.log.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"),
                                   "kind": kind, "shot": self.n, **kw}, ensure_ascii=False) + "\n")
        self.log.flush()


# JSON schemas given to the LLM (OpenAI/LiteLLM tool format, works with any provider)
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "read_page", "description": "Get the current page: title, headings and the form elements with their refs.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_text", "description": "Read the main visible text of the page (questions, job description).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "click", "description": "Click a button or link by ref (e.g. 'e12').",
        "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}}},
    {"type": "function", "function": {
        "name": "type_text", "description": "Replace the content of a text field by ref.",
        "parameters": {"type": "object", "properties": {"ref": {"type": "string"}, "text": {"type": "string"}},
                       "required": ["ref", "text"]}}},
    {"type": "function", "function": {
        "name": "select_option", "description": "Choose an option (by its visible label) in a select by ref.",
        "parameters": {"type": "object", "properties": {"ref": {"type": "string"}, "option": {"type": "string"}},
                       "required": ["ref", "option"]}}},
    {"type": "function", "function": {
        "name": "set_checked", "description": "Set a checkbox, switch or radio to on (true) or off (false). The real state is verified.",
        "parameters": {"type": "object", "properties": {"ref": {"type": "string"}, "checked": {"type": "boolean"}},
                       "required": ["ref", "checked"]}}},
    {"type": "function", "function": {
        "name": "ask_human", "description": "Ask the candidate a question you cannot answer from the profile. Returns the answer.",
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "finish", "description": "Stop. Call it on the final review page (before any submit button) or if stuck.",
        "parameters": {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["ready_for_review", "external_apply", "stuck"] + (["not_relevant"] if os.environ.get("CHECK_RELEVANCE", "false").lower() == "true" else [])},
            "summary": {"type": "string", "description": "What was filled, what the human must check."}},
            "required": ["status", "summary"]}}},
]
