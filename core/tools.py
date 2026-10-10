"""
Browser tools the apply agent (LLM) can call. Each action:
  1. checks core/policy.py BEFORE touching the page
  2. acts on the element tagged data-agent-ref="eN" by the last scan
  3. follows a new tab if the click opened one (company site, application form)
  4. re-scans, VERIFIES the result, saves a screenshot, returns the new page state
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from core import policy
from core.browser import SCAN_JS

# Elements never useful to fill a form: navigation noise
NOISE = {
    "passer au contenu principal", "skip to main content", "logo indeed", "page d'accueil",
    "avis sur les entreprises", "estimation de salaire", "mes emplois", "compte",
    "entreprises / publier une offre d'emploi", "signaler un problème",
}
KEEP_LINK = re.compile(r"postul|apply|candidat|continu|suivant|next|submit|envoyer|soumettre|cv|resume|"
                       r"connexion|connect|log ?in|sign ?in|compte|account|cookies?|refuser|accepter|fermer|close|"
                       r"sign ?up|regist|inscri|cr[ée]er|create|join|new user|nouvel utilisateur|"
                       r"t[ée]l[ée]charg|importer|upload|parcourir|browse|d[ée]pos|joindre|attach|fichier|file", re.I)
SUCCESS_RE = (r"candidature (a (bien )?été |bien )?(envoy[ée]+|transmise|re[çc]ue|enregistr[ée]+|soumise)|"
              r"merci (pour|de) votre (candidature|int[ée]r[êe]t)|votre (candidature|demande) a (bien )?[ée]t[ée] "
              r"(envoy|transmis|re[çc]u|enregistr)|thank(s| you) for (applying|your application|your interest)|"
              r"application (has been |was )?(successfully )?(submitted|received|sent)|successfully (applied|submitted)|"
              r"we.ve received your application|your application (is|has been) (in|submitted|received)|"
              r"(form|application|candidature|formulaire|demande) (was |has been |a (bien )?[ée]t[ée] )?"
              r"(submitted|sent|received|envoy[ée]e?|soumise?|transmise?) (successfully|avec succ[èe]s)|"
              r"submitted successfully|sent successfully|envoy[ée]e? avec succ[èe]s|"
              r"vous avez (bien )?postul[ée]|f[ée]licitations.{0,40}candidature|cv envoy[ée]|"   # Free-Work, HelloWork
              r"candidature .{0,80}va [êe]tre transmise|"
              r"you (have )?applied|already applied|"
              r"(candidature|candidature spontan[ée]e|demande) d[ée]j[àa] envoy[ée]e|"   # Free-Work company page
              r"a d[ée]j[àa] (une candidature|postul[ée])|d[ée]j[àa] candidat[ée]?|"     # Free-Work error toast:
              r"already (have an? |submitted an? )?application")           # "...a déjà une candidature sur cette offre"
# installed once per document: remembers the first success message, even a toast shown for one second
# Counts only once ARMED (the agent filled something in this application, then clicked), and never inside job
# cards / lists ("Candidature envoyée" under an offer you applied to before is not a confirmation).
SUCCESS_WATCH_JS = r"""(armed) => {
  const RE = new RegExp(%r, 'i');
  const CARD = '[data-job-id], [data-occludable-job-id], .job-card-container, .jobs-search-results__list-item, li[class*="job" i]';
  const hit = n => {
    if (!window.__agentArmed || window.__agentSuccess || !n) return;
    const el = n.nodeType === 1 ? n : n.parentElement;
    if (el && el.closest && el.closest(CARD)) return;
    const t = (n.innerText || n.textContent || '').trim();
    if (t && t.length < 400 && RE.test(t)) window.__agentSuccess = t.slice(0, 200);
  };
  if (armed) window.__agentArmed = true;
  if (!window.__agentWatch) {
    window.__agentWatch = true;
    new MutationObserver(ms => { for (const m of ms) for (const n of m.addedNodes) hit(n); })
      .observe(document.documentElement, {childList: true, subtree: true});
  }
  if (armed)                         // a confirmation PAGE (new document after sending): headings / status / toasts
    for (const h of document.querySelectorAll('h1, h2, h3, [role=alert], [role=status], [aria-live], ' +
        '[class*=toast i], [class*=snackbar i], [class*=notif i], [class*=alert i], [class*=success i]')) hit(h);
}""" % SUCCESS_RE
ERRORS_JS = r"""() => {
  const out = [];
  const sel = '[role=alert], [aria-live=assertive], .artdeco-inline-feedback--error, [class*="error" i], [class*="invalid" i], [id*="error" i]';
  const deepAll = (root, acc = []) => {             // web components: errors inside shadow roots too
    root.querySelectorAll(sel).forEach(e => acc.push(e));
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) deepAll(e.shadowRoot, acc); });
    return acc; };
  for (const e of deepAll(document)) {
    if (!e.offsetParent || e.querySelector('input, select, textarea')) continue;
    const t = (e.innerText || '').replace(/\s+/g, ' ').trim();
    if (t && t.length < 200 && /obligatoire|requis|required|invalide|invalid|veuillez|please|incorrect|erreur|error|must|doit/i.test(t)) out.push(t);
  }
  return [...new Set(out)].slice(0, 6);
}"""
CAPTCHA_FRAME = re.compile(r"recaptcha|hcaptcha|challenges\.cloudflare|turnstile|arkoselabs|funcaptcha|captcha", re.I)
# Text of a REAL challenge page (not "protected by reCAPTCHA" footers): checked on short pages only
CAPTCHA_TEXT = re.compile(r"v[ée]rification de s[ée]curit[ée]|security (check|verification)|"
                          r"(prove|confirm|verify) (that )?you.?re (a )?human|je ne suis pas un robot|i.?m not a robot|"
                          r"v[ée]rifiez que vous [êe]tes (un )?humain|unusual traffic|trafic inhabituel|"
                          r"compl[ée]tez le captcha|solve the (captcha|puzzle)|r[ée]solvez", re.I)
# Many sites (LinkedIn...) load INVISIBLE anti-robot frames on every page: only a VISIBLE, big enough one counts
VISIBLE_CAPTCHA_JS = r"""() => [...document.querySelectorAll('iframe')].some(f => {
  const src = f.src || '', t = (f.title || '').toLowerCase();
  if (!/recaptcha|hcaptcha|challenges\.cloudflare|turnstile|arkoselabs|funcaptcha|captcha/i.test(src + ' ' + t)) return false;
  if (/size=invisible|grecaptcha-badge/.test(src) || f.closest('.grecaptcha-badge')) return false;
  const r = f.getBoundingClientRect(), s = getComputedStyle(f);
  return r.width >= 250 && r.height >= 65 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.1
         && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
})"""
FILLED_JS = """() => [...document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea, select')]
                     .filter(e => (e.value || '').trim()).length"""


class BrowserTools:
    def __init__(self, page: Page, run_dir: Path, ask_human, ctx: dict, cv_path: str = ""):
        self.page = page                     # the tab the agent works in (follows new tabs)
        self.run_dir = run_dir
        self.ask_human = ask_human           # function(question) -> answer ("" = no)
        self.ctx = dict(ctx)                 # policy context (see core/policy.py)
        self.cv_path = resolve_cv(cv_path)
        self.elements: dict[str, dict] = {}
        self.n = 0
        self.submitted = False               # set when the final button was clicked (allowed by policy)
        self.auto_sent = False               # the autopilot clicked a send button (no confirmation seen yet)
        self.cv_uploads = 0                  # CV given to the site in this application (never 3 times)
        self.unanswered: list[str] = []      # questions nobody answered (unattended mode)
        self.denied: list[str] = []          # actions refused because nobody approved them
        self.opened: list[Page] = []         # tabs opened during the application
        self.frames: dict = {}               # ref -> frame (forms inside iframes: Workday, SmartRecruiters...)
        self.captcha = False                 # last scan saw a captcha / security check
        self.pending_image = None            # look(): screenshot sent to the LLM with the next message
        self.human_steps: list[str] = []     # what the human did by hand (supervised mode)
        self.no_captcha_hosts: set[str] = set()   # the human answered "none": no captcha warning there anymore
        self.log = (run_dir / "actions.jsonl").open("a", encoding="utf-8")
        self.success = ""                    # "candidature envoyée" message seen on the page
        self.armed = False                   # the agent filled something, then clicked: a success message counts
        self._watched: list = []             # (page, handler) of the file-picker listeners, removed by close()
        self.log_kinds: set = set()
        self.llm_fills: list = []
        self.started = False                 # the apply button of the offer was clicked (by anyone)            # (label, value) the LLM gave: learned at the end (core/autofill.learn)
        self._context = page.context
        page.context.on("page", self._on_new_page)
        self._watch_file_chooser(page)

    def _pause_file_pickers(self) -> list:
        """You act in Chrome (captcha, login, a file to attach): YOUR file picker must open, not be intercepted."""
        paused = list(self._watched)
        for pg, handler in paused:
            try:
                pg.remove_listener("filechooser", handler)
            except Exception:
                pass
        self._watched = []
        return paused

    def _resume_file_pickers(self, paused: list):
        for pg, handler in paused:
            try:
                pg.on("filechooser", handler)
                self._watched.append((pg, handler))
            except Exception:
                pass

    def close(self):
        """End of THIS application: stop intercepting file pickers (your own uploads in Chrome work again)."""
        try:
            self._context.remove_listener("page", self._on_new_page)
        except Exception:
            pass
        for pg, handler in self._watched:
            try:
                pg.remove_listener("filechooser", handler)
            except Exception:
                pass
        self._watched = []
        try:
            self.log.close()
        except Exception:
            pass

    def cv_payload(self) -> dict:
        """The CV by CONTENT, not by path: Chrome on Windows cannot open a WSL path (/mnt/c/..., /home/...).
        A path gave forms the file NAME with an empty / unreadable file."""
        p = Path(self.cv_path)
        mime = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".doc": "application/msword"}.get(p.suffix.lower(), "application/octet-stream")
        return {"name": p.name, "mimeType": mime, "buffer": p.read_bytes()}

    def _on_new_page(self, new: Page):
        self.opened.append(new)
        self._watch_file_chooser(new)

    def _watch_file_chooser(self, page: Page):
        """A click on "téléchargez" / "Importer" opens the OS file picker, which would block Chrome:
        Playwright intercepts it and gives the configured CV instead (nothing else is ever given)."""
        def give_cv(chooser):
            if self.cv_path and Path(self.cv_path).exists():
                chooser.set_files(self.cv_payload())
                self._write("upload_cv", el="file picker", file=Path(self.cv_path).name)
                self.cv_uploads += 1
        try:
            page.on("filechooser", give_cv)
            self._watched.append((page, give_cv))
        except Exception:
            pass

    def _follow_new_tab(self, before: int):
        """If THIS click opened a tab (Indeed smartapply, company site), continue there.
        Popups can arrive a bit after the click: wait up to 3 s."""
        for _ in range(6):
            if len(self.opened) > before:
                break
            self.page.wait_for_timeout(500)          # (time.sleep would not let Playwright receive the event)
        fresh = [p for p in self.opened[before:] if not p.is_closed()]
        if fresh:
            self.page = fresh[-1]
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            self._write("new_tab", url=self.page.url)

    # ---------- observation ----------
    def _scan(self) -> list[dict]:
        p = self.page
        p.wait_for_load_state("domcontentloaded")
        time.sleep(1.2)
        els, self.frames, filled, self.captcha = [], {}, 0, False
        for i, fr in enumerate(p.frames):                 # main page + embedded frames (application forms)
            if i and (fr.is_detached() or not fr.url or fr.url.startswith(("about:", "javascript:"))):
                continue
            if i and CAPTCHA_FRAME.search(fr.url):
                continue                                  # captcha frames: never scanned (visibility checked below)
            try:
                found = fr.evaluate(SCAN_JS, "e" if i == 0 else f"f{i}e")
                filled += fr.evaluate(FILLED_JS)
            except Exception:
                continue
            for e in found:
                e["frame"] = i
                self.frames[e["ref"]] = fr
            els += found
        try:
            visible = p.evaluate(VISIBLE_CAPTCHA_JS)
            body = p.evaluate("() => document.body ? document.body.innerText : ''")
            # a challenge page is short; a job offer mentioning "security check" in its text is not one
            self.captcha = visible or (len(body) < 2500 and bool(CAPTCHA_TEXT.search(body)))
        except Exception:
            pass
        if self.captcha and policy.host(p.url) in self.no_captcha_hosts:
            self.captcha = False                          # the human said there is none on this site
        self.elements = {e["ref"]: e for e in els}
        self.ctx["filled_inputs"] = filled
        self._check_success()
        self.n += 1
        try:                                              # log screenshot only: never blocks the application
            p.screenshot(path=str(self.run_dir / f"{self.n:02d}.png"), timeout=4000)
        except Exception:
            pass                                          # minimized / background window does not paint
        return els

    def _check_success(self):
        """Watches the page for "candidature envoyée" / "application submitted" (also quick toasts)."""
        for fr in [self.page.main_frame] + [f for f in self.frames.values()]:
            try:
                fr.evaluate(SUCCESS_WATCH_JS, self.armed)
                seen = fr.evaluate("() => window.__agentSuccess || ''")
            except Exception:
                continue
            if seen and not self.success:
                self.success = seen
                self._write("success_seen", text=seen, url=self.page.url)

    def read_page(self) -> str:
        """Compact, filtered view of the page: title, headings, form elements."""
        self._alive_page()
        els = self._scan()
        p = self.page
        headings = p.evaluate("() => [...document.querySelectorAll('h1,h2,h3,legend')]"
                              ".map(h => h.innerText.trim()).filter(Boolean).slice(0, 12)")
        where = "JOB BOARD OFFER PAGE" if policy.on_board_offer_page(p.url, self.ctx) else "APPLICATION SITE"
        if any(e.get("in_dialog") for e in els):          # a modal is open (LinkedIn Easy Apply): only its elements
            els = [e for e in els if e.get("in_dialog")]
            where = "APPLICATION FORM in a dialog" if policy.host(p.url) == self.ctx.get("board_host") else "DIALOG"
        elif where == "JOB BOARD OFFER PAGE" and any(e.get("in_apply_form") for e in els):
            where = "APPLICATION FORM on the job board page"         # HelloWork-like form drawn in the page
        lines = [f"TITLE: {p.title()}", f"URL: {p.url[:120]}  ({where})",
                 "HEADINGS: " + " | ".join(h[:80] for h in headings)]
        if self.success:
            lines.append(f"!! THE APPLICATION IS SENT (message seen: \"{self.success[:120]}\"). Do not click anything: "
                         "call finish(status='submitted').")
        errors = self._errors()
        if errors:
            lines.append("!! ERRORS SHOWN ON THE PAGE (fix them before going on): " + " | ".join(errors))
        if self.captcha:
            lines.append("!! A CAPTCHA / SECURITY CHECK seems visible: call wait_for_human('solve the captcha') "
                         "(if look() shows none, ignore this line)")
        if any(e.get("frame") for e in els):
            lines.append("(part of the page is an embedded frame: its elements have refs like f2e5, use them normally)")
        progress = re.compile(r"envoyer|soumettre|submit|suivant|continuer|next|examiner|v[ée]rifier|review|"
                              r"d[ée]poser|terminer|confirmer|valider", re.I)
        if not any(e["role"] in ("input", "select", "textarea") or e.get("type") == "file" for e in els) \
                and not any(progress.search(e["name"]) for e in els if e["role"] != "a") \
                and where != "JOB BOARD OFFER PAGE":
            lines.append("(no form field here: find the apply button with find('postuler|apply|candidater'), "
                         "scroll, or look)")
        # login page of a site where you have NO account yet: go to "Sign up" directly (BairesDev)
        if self.ctx.get("accounts") and any((e.get("type") or "") == "password" for e in els):
            from core import accounts
            site = policy.host(self.page.url)
            known = accounts.known_sites().get(site)
            exists = ACCOUNT_EXISTS.search(self._safe_text()[:20000])
            if exists and not known:                       # LCL: "cette adresse e-mail est déjà utilisée"
                lines.append(f"AN ACCOUNT ALREADY EXISTS here (\"{exists.group(0)[:80]}\") but it is not in "
                             "accounts.json: do NOT create another one, do NOT guess the password. Call "
                             "wait_for_human('log in: an account already exists on this site') -- the human logs in "
                             "(and can save the login for next time).")
            elif known:
                lines.append(f"YOU HAVE AN ACCOUNT on this site (login: {known.get('login') or 'your email'}): sign in "
                             "(type the login, then fill_password(ref) on the password field). If the login fails: "
                             "wait_for_human('log in').")
            else:
                signup = next((e for e in els if policy.ACCOUNT.search(e["name"])
                               and re.search(r"sign ?up|regist|inscri|cr[ée]er|create|join", e["name"], re.I)), None)
                lines.append("NO ACCOUNT on this site yet (not in accounts.json): do NOT try to sign in, create it"
                             + (f": click [{signup['ref']}] \"{signup['name'][:40]}\"" if signup else
                                " (find('sign up|register|créer un compte|inscription'))")
                             + ". If the site answers that this email / account ALREADY EXISTS: "
                               "wait_for_human('log in: an account already exists on this site').")
        lines.append("ELEMENTS:")
        for e in els:
            name = e["name"].lower()
            if name in NOISE or (e["role"] in ("a", "link") and not e["required"] and not KEEP_LINK.search(name)):
                continue
            kind = e["role"] + (f":{e['type']}" if e["type"] and e["role"] in ("input", "switch") else "")
            if e.get("dropdown"):
                kind = "dropdown(use select_option)"
            if e.get("search"):
                kind = "search-field(use search_select)"
            s = f"  [{e['ref']}] {kind} \"{e['name'][:200]}\""
            if e["value"]:
                s += f" value=\"{e['value']}\""
            if e.get("options"):
                s += " options=" + json.dumps(e["options"], ensure_ascii=False)
            if e["checked"] is not None:
                s += f" checked={str(e['checked']).lower()}"
            if e["required"]:
                s += " REQUIRED"
            if e.get("invalid"):
                s += " INVALID"
            if e["disabled"]:
                s += " DISABLED"
            if e["role"] in ("button", "input") and (e.get("in_dialog") or e.get("in_apply_form")) \
                    and (policy.SUBMIT.search(e["name"]) or policy.AMBIGUOUS_SEND.match(e["name"].strip())):
                s += "  <- the SEND button of this form"         # Free-Work "Je postule": the LLM hesitated
            lines.append(s)
        return "\n".join(lines)

    def get_text(self) -> str:
        txt = self.page.evaluate("""() => {
            const d = [...document.querySelectorAll('[role=dialog], dialog, .artdeco-modal')].filter(x => x.offsetParent).pop();
            return (d || document.querySelector('main') || document.body).innerText }""")
        frames = []
        for fr in self.page.frames[1:]:                     # forms inside frames (ATS)
            if not fr.is_detached() and fr.url and not CAPTCHA_FRAME.search(fr.url) and not fr.url.startswith("about:"):
                try:
                    frames.append(fr.evaluate("() => document.body ? document.body.innerText : ''"))
                except Exception:
                    pass
        txt = "\n".join([txt] + [f for f in frames if f.strip()])
        return txt[:4000]

    # ---------- actions ----------
    def _el(self, ref):
        if ref not in self.elements:
            raise ValueError(f"unknown ref {ref}: call read_page first")
        frame = self.frames.get(ref) or self.page.main_frame
        return frame.locator(f'[data-agent-ref="{ref}"]').first, self.elements[ref]

    def _guard(self, action: str, el: dict, value=None) -> str | None:
        verdict, reason = policy.check(action, el, self.page.url, self.ctx, value)
        self._write("policy", action=action, el=el["name"], value=value, verdict=verdict, reason=reason)
        if verdict == policy.FORBIDDEN:
            return f"BLOCKED by policy: {reason}. Do not retry this action."
        if verdict == policy.ASK:
            ans = self.ask_human(f"{reason}\n  -> {action} \"{el['name']}\" {'' if value is None else value}\n  Allow? [y/N] ")
            if ans.strip().lower() not in ("y", "yes", "o", "oui"):
                self.denied.append(f"{action} '{el['name'][:60]}'")
                return "DENIED (nobody approved). Do not retry. If it is required, finish(status='needs_human')."
        if reason == "submit":
            self.submitted = True
        return None

    def _arm(self, name: str = ""):
        """Something was filled in this application, or the button is a send / one-click apply ("Je postule" on
        Free-Work sends at once): from now on a "candidature envoyée" message counts."""
        one_click = bool(policy.AMBIGUOUS_SEND.match(name.strip()) or policy.SUBMIT.search(name)
                         or policy.EASY_START.match(name.strip()))
        if not one_click and not any(k in self.log_kinds for k in ("type", "select", "set_checked", "upload_cv")):
            return
        self.armed = True
        for fr in [self.page.main_frame] + list({id(f): f for f in self.frames.values()}.values()):
            try:
                fr.evaluate(SUCCESS_WATCH_JS, True)
            except Exception:
                pass

    def _errors(self) -> list[str]:
        """Validation messages ("Ce champ est obligatoire"...): without them the agent clicks "Suivant" forever."""
        out = []
        for fr in [self.page.main_frame] + list({id(f): f for f in self.frames.values()}.values()):
            try:
                out += fr.evaluate(ERRORS_JS)
            except Exception:
                pass
        return list(dict.fromkeys(out))[:6]

    def click(self, ref: str) -> str:
        loc, el = self._el(ref)
        self._arm(el.get("name") or "")
        if self.success:
            return (f"ALREADY SENT (\"{self.success[:80]}\"): never click again, it could send it twice. "
                    "finish(status='submitted').")
        if (msg := self._guard("click", el)):
            return msg
        if policy.EASY_START.match(el["name"]) or policy.EXTERNAL_START.match(el["name"]):
            self.started = True
        _scroll(loc)
        before = len(self.opened)
        how = _press(loc)
        self.page.wait_for_timeout(1000)
        if el["role"] in ("a", "link") or "postuler" in el["name"].lower() or "apply" in el["name"].lower():
            self._follow_new_tab(before)                # only links / apply buttons open new tabs
        elif len(self.opened) > before:
            self._follow_new_tab(before)
        self._write("click", ref=ref, el=el["name"], url=self.page.url, **({"how": how} if how != "normal" else {}))
        self.page.wait_for_timeout(800)
        state = self.read_page()
        if self.success and not self.submitted:            # a send button the rules did not know: it IS sent
            self.submitted = True
            self._write("submitted_by_success_message", el=el["name"], text=self.success)
        return "clicked.\n" + state

    def type_text(self, ref: str, text: str) -> str:
        if self.success:                                  # sent: the page now shows OTHER offers (HelloWork)
            return (f"ALREADY SENT (\"{self.success[:80]}\"): the application is done. Do not touch this page "
                    "(other offers / suggestions): finish(status='submitted').")
        loc, el = self._el(ref)
        if el.get("search"):                              # typed text alone is never saved in these fields
            return "(search field: type + Enter + pick in the list)\n" + self.search_select(ref, text, text)
        if (msg := self._guard("type", el, text)):
            return msg
        _scroll(loc)
        try:
            loc.fill(text, timeout=5000)
            actual = loc.input_value()
        except Exception:
            actual = ""
        if _digits(actual) != _digits(text) or (not actual and text):
            # masked field (date JJ/MM/AAAA, phone): type like a person -- digits only first (masks add the "/")
            tries = [re.sub(r"\D", "", text), text] if re.fullmatch(r"[\d/ .+-]+", text) else [text]
            for attempt in tries:
                try:
                    loc.click(timeout=5000)
                except Exception:                          # covered / hidden behind an editor: set it by script
                    actual = _js_set(loc, text)
                    break
                self.page.keyboard.press("Control+A")
                self.page.keyboard.press("Backspace")
                self.page.keyboard.type(attempt, delay=60)
                self.page.wait_for_timeout(300)
                try:
                    actual = loc.input_value()
                except Exception:
                    actual = "(not readable)"
                if _digits(actual) == _digits(text):
                    break
        self._write("type", ref=ref, el=el["name"], text=text, verified=actual == text)
        frame = self.frames.get(ref) or self.page.main_frame
        self.page.wait_for_timeout(500)
        try:
            emptied = bool(text) and not loc.input_value()
        except Exception:
            emptied = False
        if emptied and el["role"] == "input":                # the site erased it: only a value from its list counts
            self.elements[ref]["search"] = True
            return "(the field erased the typed text: picking in its list)\n" + self.search_select(ref, text, text)
        try:
            if actual and el["role"] == "input":
                loc.press("End")                          # a key event: lists opened on keyup (Lever) wake up
        except Exception:
            pass
        listed = self._list_opened(frame, _list_wait(el["name"]))   # a list opened (it may load in ~1 s)
        if listed and el["role"] == "input" and (el.get("type") or "text") in ("text", "search", ""):
            self.elements[ref]["search"] = True
            return "(a suggestion list opened: picking in it)\n" + self.search_select(ref, text, text)
        self.llm_fills.append((el["name"], text))
        return f"typed (field now contains: \"{actual[:80]}\").\n" + self.read_page()

    def select_option(self, ref: str, option: str) -> str:
        if self.success:                                  # sent: the page now shows OTHER offers (HelloWork)
            return (f"ALREADY SENT (\"{self.success[:80]}\"): the application is done. Do not touch this page "
                    "(other offers / suggestions): finish(status='submitted').")
        loc, el = self._el(ref)
        if (msg := self._guard("select", el, option)):
            return msg
        _scroll(loc)
        tag = loc.evaluate("e => e.tagName")
        if tag == "SELECT":
            options = loc.evaluate("e => [...e.options].map(o => o.text.trim())")
            choice = best_option(option, options)
            if choice is None:
                return (f"NO OPTION matches '{option}'. The options are: {json.dumps(options, ensure_ascii=False)}. "
                        "Call select_option again with one of them exactly.")
            loc.select_option(label=choice, timeout=5000)
        else:                                               # custom dropdown (Workday...): open it, click the option
            frame = self.frames.get(ref) or self.page.main_frame
            opts = frame.locator("[role=option]:visible, [role=listbox] li:visible, [role=menuitem]:visible")
            if not opts.count():
                loc.click(timeout=5000)
                self.page.wait_for_timeout(700)
            if not opts.count():                            # the click closed it (it was open): open again
                loc.click(timeout=5000)
                self.page.wait_for_timeout(700)
            texts = [t.strip() for t in opts.all_inner_texts()]
            choice = best_option(option, texts)
            if choice is None:
                self.page.keyboard.press("Escape")
                return (f"NO OPTION matches '{option}'. The options are: {json.dumps(texts[:25], ensure_ascii=False)}. "
                        "Call select_option again with one of them exactly.")
            opts.nth(texts.index(choice)).click(timeout=5000)
        self._write("select", ref=ref, el=el["name"], option=option, chosen=choice)
        self.llm_fills.append((el["name"], choice))
        return f"selected \"{choice}\".\n" + self.read_page()

    def fill_password(self, ref: str) -> str:
        """Types the default account's password (from .env) into a password field. The LLM never sees it."""
        from core import accounts
        loc, el = self._el(ref)
        verdict, reason = policy.check("fill_password", el, self.page.url, self.ctx)
        self._write("policy", action="fill_password", el=el["name"], verdict=verdict, reason=reason)
        if verdict != policy.ALLOW:
            return f"BLOCKED by policy: {reason}"
        pw = accounts.password_for(policy.host(self.page.url))      # this site's own password, else the default
        if not pw:
            return "NO PASSWORD in .env (JOBAGENT_ACCOUNT_PASSWORD): wait_for_human('log in / create the account')."
        # ALL the password fields of this form, in order (Password, then Verify / Confirm), typed like a person:
        # filling "Password" again after "Verify" empties "Verify" on Workday -> "Passwords do not match" loop
        frame = self.frames.get(ref) or self.page.main_frame
        group = frame.locator("form:has([data-agent-ref='%s']) input[type=password]:visible" % ref)
        if not group.count():
            group = frame.locator("input[type=password]:visible")
        fields = group.count() or 1
        boxes = [group.nth(i) for i in range(fields)] if group.count() else [loc]
        short = [b.get_attribute("maxlength") for b in boxes]
        short = [int(m) for m in short if m and m.isdigit() and int(m) < len(pw)]
        if short:
            return (f"THIS SITE LIMITS THE PASSWORD TO {min(short)} characters (the account password is longer): "
                    "wait_for_human('create the account with a shorter password') -- unattended: finish(status='needs_human').")
        for box in boxes:
            box.click(timeout=5000)
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
            self.page.keyboard.type(pw, delay=25)
            if box.input_value() != pw:                      # a key lost / a mask: set it directly, then check
                box.fill(pw)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(300)
        # the same password in every field ("Les mots de passe doivent être identiques"): checked in the page,
        # the value never comes back to the AI
        ok = all(b.evaluate("(e, p) => e.value === p", pw) for b in boxes)
        if not ok:                                           # once more, by script (input + change events)
            for b in boxes:
                b.fill(pw)
                b.dispatch_event("change")
            ok = all(b.evaluate("(e, p) => e.value === p", pw) for b in boxes)
        self._write("fill_password", ref=ref, el=el["name"], fields=fields, verified=ok)   # the value is never logged
        accounts.remember(policy.host(self.page.url), "account created" if fields >= 2 else "password typed (login)",
                          accounts.email(self.profile_for_auto), self.page.url)
        both = f" in the {fields} password fields (password + confirmation)" if fields >= 2 else ""
        return (f"password typed{both} (hidden, verified: {ok}). Do not type it again: next, the button "
                "(Create Account / Sign In).\n" + self.read_page())

    OPTIONS_SEL = ("[role=option]:visible, [data-automation-id=promptOption]:visible, [role=listbox] li:visible, "
                   ".pac-item:visible, [data-automation-id=menuItem]:visible, "
                   ".dropdown-results .dropdown-location:visible, "            # Lever "Current location"
                   "[class*=autocomplete] li:visible, [class*=suggestion] li:visible, "
                   "spl-select-option:visible")                            # SmartRecruiters (web components)

    def _list_opened(self, frame, wait_ms: int = 2000) -> bool:
        """After typing: did a suggestion list open? (Lever's location list loads after ~1 s)"""
        end = time.time() + wait_ms / 1000
        while True:
            self.page.wait_for_timeout(300)
            try:
                if [t for t in frame.locator(self.OPTIONS_SEL).all_inner_texts() if t.strip() and not NO_ITEMS.match(t.strip())]:
                    return True
            except Exception:
                pass
            if time.time() > end:
                return False

    def _suggestions(self, opts, wait_ms: int, stale: list | None = None) -> list[str]:
        """The REAL options of the open list ("Aucun article.", "Résultats de la recherche (2)" are not options),
        once the list is stable (Workday answers late)."""
        last, deadline = None, time.time() + wait_ms / 1000
        while True:
            self.page.wait_for_timeout(300)
            try:
                texts = [t.strip() for t in opts.all_inner_texts()] if opts.count() else []
            except Exception:
                texts = []
            texts = [t for t in texts if t and not NO_ITEMS.match(t)]
            if stale and texts == stale:
                texts = []                                  # the list of the PREVIOUS search, still shown
            if texts and texts == last:
                return texts
            last = texts
            if time.time() > deadline:
                return texts

    def search_select(self, ref: str, query: str, option: str = "") -> str:
        """Search field (Workday "Établissement", city...): type the query, Enter if needed, pick the best option
        in the suggestion list, then CHECK it was selected. Typing alone leaves these fields empty."""
        loc, el = self._el(ref)
        if (msg := self._guard("type", el, query)):
            return msg
        frame = self.frames.get(ref) or self.page.main_frame
        ident = (self.profile_for_auto.get("identity") or {})
        city, postal = str(ident.get("city") or ""), str(ident.get("postal_code") or "")
        address = bool(city) and bool(re.search(r"adresse|address|rue\b|street|domicile|lieu de r[ée]sidence", el["name"], re.I)) \
            and not re.search(r"e-?mail|[ée]lectronique", el["name"], re.I)
        if address and _norm(city) not in _norm(query):   # "Rue de la Paix" alone -> picked Lyon (Lefebvre Dalloz)
            query = f"{query}, {postal} {city}".replace(" ,", ",").strip(", ")
            option = f"{option} {city}".strip() if option else ""
        country = str(ident.get("country") or "")
        if (not address and city and country and _norm(query) == _norm(city)
                and re.search(r"location|localisation|ville|city|lieu|o[uù] habitez", el["name"], re.I)):
            query, option = city, f"{city}, {country}"     # "Paris" -> "Paris, France", not "Paris, Texas"
        wanted = option or query
        words = sorted(set(re.findall(r"\w{4,}", wanted)), key=len, reverse=True)
        tries = [query] + [w for w in words[:2] if w.lower() != query.lower()]   # "Limoges" finds more than the full name
        school = bool(re.search(r"[ée]tablissement|[ée]cole|universit|school|institution|college|formation|dipl[ôo]m",
                                el["name"], re.I))
        if school and not OTHER.match(wanted):
            tries += ["Autre", "Other"]                      # Workday: school not in the list -> "Autre Ecole/Université"
        opts, used, choice, seen = frame.locator(self.OPTIONS_SEL), "", None, []
        for q in tries:
            loc.click(timeout=5000)
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
            before = self._suggestions(opts, 0)             # what is still shown with the field empty = stale
            self.page.keyboard.type(q, delay=40)
            texts = self._suggestions(opts, 900, before)
            if not texts:
                cur = self._suggestions(opts, 0)
                key = max(_norm(q).split() or [""], key=len)
                if cur and key and any(key in _norm(t) for t in cur):
                    texts = cur                             # the same list, and it answers THIS query (Lever)
                else:                                       # Workday searches on Enter ("taper Entrée")
                    self.page.keyboard.press("Enter")
                    texts = self._suggestions(opts, 4000, before)
            if not texts:
                continue
            seen = texts
            if q in ("Autre", "Other"):                     # the value is not in the site's list
                choice = next((t for t in texts if OTHER.match(t)), None)
            elif address:                                   # only a suggestion in the candidate's city
                local = [t for t in texts if _norm(city) in _norm(t) or (postal and postal in t)]
                if not local:
                    self.page.keyboard.press("Escape")
                    return (f"No suggestion in {city} for '{query}' (got: {json.dumps(texts[:6], ensure_ascii=False)})."
                            f" Do NOT pick another city: try search_select(ref, '{postal} {city}') or type the address.")
                choice = best_option(wanted, local) or _best_words(wanted, local) or local[0]
            else:
                choice = best_option(wanted, texts) or _best_words(wanted, texts)
                if choice and not _same_key(wanted, choice):
                    choice = None                           # "Université de Lille" is not "Université de Limoges"
            if choice:
                used = q
                break
        if not choice and not address and not school:      # free text with suggestions (job title...): keep it typed
            loc.click(timeout=5000)
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
            self.page.keyboard.type(query, delay=30)
            self.page.keyboard.press("Escape")
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(500)
            try:
                kept = loc.input_value()
            except Exception:
                kept = ""
            if kept and _norm(kept) == _norm(query):
                self._write("type", ref=ref, el=el["name"], text=query, verified=True, free_text=True)
                self.llm_fills.append((el["name"], query))
                return (f"typed \"{query}\" (no suggestion matched; the field keeps free text).\n"
                        + self.read_page())
        if not choice:
            self.page.keyboard.press("Escape")
            self._write("search_select_failed", ref=ref, el=el["name"], query=query, tries=tries, seen=seen[:8])
            if not seen:
                return (f"NO SUGGESTION for '{query}' (the site answered 'no items'). Try another word "
                        "(a city, an abbreviation), or look().")
            return (f"No suggestion matches '{wanted}'. Suggestions: {json.dumps(seen[:20], ensure_ascii=False)}. "
                    "Call search_select again with option = one of them (or 'Autre' / 'Other' if offered).")
        raw = [t.strip() for t in opts.all_inner_texts()]
        opts.nth(raw.index(choice)).click(timeout=5000)
        self.page.wait_for_timeout(800)
        short = re.split(r"\s*[+(,]", choice)[0].strip() or choice  # "France +33" is shown as "France"
        picked = loc.evaluate("""(e, wants) => { let n = e;
            for (let up = 0; up < 6 && n; up++, n = n.parentElement)
                for (const want of wants)
                    if ((n.innerText || '').includes(want) || (e.value || '').includes(want)) return true;
            return false; }""", [choice[:40], short[:40]])
        self._write("search_select", ref=ref, el=el["name"], query=query, chosen=choice, verified=picked)
        if picked and used not in ("Autre", "Other"):
            self.llm_fills.append((el["name"], choice))
        if picked and used in ("Autre", "Other"):
            return (f"selected \"{choice}\" (verified: True): '{wanted}' is not in this site's list, so the "
                    "site's own rule applies (\"Autre\"). Done for this field.\n") + self.read_page()
        return (f"selected \"{choice}\" (verified: {picked}).\n" if picked else
                f"clicked \"{choice}\" but it does not show as selected: look() to check.\n") + self.read_page()

    def set_checked(self, ref: str, checked: bool) -> str:
        """Checkbox / switch / radio. Reads the REAL state before and after (not the label)."""
        if self.success:                                  # sent: the page now shows OTHER offers (HelloWork)
            return (f"ALREADY SENT (\"{self.success[:80]}\"): the application is done. Do not touch this page "
                    "(other offers / suggestions): finish(status='submitted').")
        loc, el = self._el(ref)
        state = lambda: loc.evaluate("e => e.checked ?? (e.getAttribute('aria-checked') === 'true')", timeout=5000)
        _scroll(loc)
        before = state()
        if before == checked:
            return f"already {checked}: \"{el['name'][:60]}\". Nothing done.\n" + self.read_page()
        if (msg := self._guard("check" if checked else "uncheck", el)):
            return msg
        how = _press(loc)
        time.sleep(0.6)
        after = state()
        self._write("set_checked", ref=ref, el=el["name"], wanted=checked, before=before, after=after)
        if checked and (el.get("type") or "").lower() == "radio" and "[question:" in el["name"]:
            self.llm_fills.append((el["name"], el["name"].split(" [question")[0]))
        if after != checked:
            return f"FAILED: state is still {after}. Look at the page again before retrying."
        return f"verified: \"{el['name'][:60]}\" is now {after}.\n" + self.read_page()

    def upload_cv(self, ref: str) -> str:
        """Put the configured CV file (config [apply] cv_path) in a file input. ref may be the input itself, or the
        drop zone / "téléchargez" button: the file input next to it (often hidden) is used."""
        loc, el = self._el(ref)
        if not self.cv_path or not Path(self.cv_path).exists():
            return (f"NO CV FILE at '{self.cv_path}' (config.toml [apply] cv_path). "
                    "finish(status='needs_human') if a CV is required.")
        if (msg := self._guard("upload_cv", el)):
            return msg
        try:
            have = loc.evaluate("e => e.files && e.files[0] ? e.files[0].size : 0") if (el.get("type") or "") == "file" else 0
        except Exception:
            have = 0
        if have == Path(self.cv_path).stat().st_size or (self.cv_uploads and (el.get("type") or "") != "file"
                                                          and self.cv_uploads >= 2):
            return ("ALREADY ATTACHED: the CV is in the form. Do NOT upload it again (some sites re-analyse it and "
                    "overwrite the fields). Go on with the other fields.\n" + self.read_page())
        if (el.get("type") or "").lower() != "file":
            frame = self.frames.get(ref) or self.page.main_frame
            found = loc.evaluate("""e => {
                const deep = (root, out = []) => {          // also inside web components (shadow roots)
                    root.querySelectorAll('input[type=file]').forEach(f => out.push(f));
                    root.querySelectorAll('*').forEach(x => { if (x.shadowRoot) deep(x.shadowRoot, out); });
                    return out; };
                const up = n => n.parentElement || (n.getRootNode() && n.getRootNode().host) || null;
                document.querySelectorAll('[data-agent-cv]').forEach(x => x.removeAttribute('data-agent-cv'));
                let f = null;
                for (let n = e, i = 0; n && i < 8 && !f; n = up(n), i++) f = deep(n)[0] || null;
                if (!f) { const all = deep(document); f = all.length === 1 ? all[0] : null; }
                if (f) f.setAttribute('data-agent-cv', '1');
                return !!f; }""", timeout=5000)
            if not found:
                return "no file input found near this element: use the ref of the file input (or the drop zone)."
            loc = frame.locator("[data-agent-cv='1']").first
        before = self._form_sig()
        loc.set_input_files(self.cv_payload())
        try:
            size = loc.evaluate("e => e.files && e.files[0] ? e.files[0].size : 0", timeout=3000)
        except Exception:
            size = -1                                       # the site replaced the input after taking the file
        filled = self._settle_after_upload(before)          # SmartRecruiters, Workday...: the CV is read, fields filled
        name = Path(self.cv_path).name
        shown = name.lower() in (self._safe_text() or "").lower()
        if size != Path(self.cv_path).stat().st_size and not filled and not shown:
            return f"UPLOAD FAILED: the file in the form has {size} bytes instead of {Path(self.cv_path).stat().st_size}."
        self._write("upload_cv", ref=ref, el=el["name"], file=name, **({"fields_filled_by_site": filled} if filled else {}))
        self.cv_uploads += 1
        note = ""
        if filled:
            note = (f"THE SITE READ YOUR CV and filled {filled} field(s)/section(s) by itself (experience, education...). "
                    "Keep them: do NOT add or edit experience / education entries (\"Ajouter\", \"Add\"), they are "
                    "done. Only fill what is still EMPTY and required, then go on.\n")
        return f"uploaded {name}.\n{note}" + self.read_page()

    FORM_SIG_JS = r"""() => {
      const vals = [...document.querySelectorAll('input:not([type=hidden]):not([type=file]), textarea, select')]
          .filter(e => (e.value || '').trim()).length;
      return [vals, (document.body.innerText || '').length];
    }"""
    BUSY_JS = r"""() => [...document.querySelectorAll('[aria-busy=true], [role=progressbar], [class*=spinner i], [class*=loader i], [class*=loading i], [class*=parsing i]')]
          .some(e => e.offsetParent !== null)
          || /analyse (de|du) (votre )?cv|parsing (your )?(resume|cv)|lecture (de|du) cv|extracting|chargement en cours/i
               .test((document.body.innerText || '').slice(0, 20000))"""

    def _form_sig(self):
        try:
            return self.page.evaluate(self.FORM_SIG_JS)
        except Exception:
            return [0, 0]

    def _safe_text(self) -> str:
        try:
            return self.page.evaluate("() => document.body.innerText || ''")
        except Exception:
            return ""

    def _settle_after_upload(self, before, max_s: float = 15) -> int:
        """Many sites read the CV right after the upload and fill the form (SmartRecruiters, Workday, Lever...):
        wait until that is finished (no spinner, page stable) before the next step. Returns how many more fields
        were filled + 1 if a big block of text appeared (experience / education cards), 0 if nothing changed."""
        import time as _t
        start, last, stable = _t.time(), None, 0
        self.page.wait_for_timeout(800)
        while _t.time() - start < max_s:
            try:
                busy = self.page.evaluate(self.BUSY_JS)
            except Exception:
                busy = False
            sig = self._form_sig()
            stable = stable + 1 if (sig == last and not busy) else 0
            if stable >= 2:
                break
            last = sig
            self.page.wait_for_timeout(700)
        after = self._form_sig()
        more = max(0, after[0] - before[0]) + (1 if after[1] - before[1] > 300 else 0)
        if more:
            self._write("cv_read_by_site", fields=after[0] - before[0], text_added=after[1] - before[1],
                        waited=round(_t.time() - start, 1))
        return more

    def ask(self, question: str) -> str:
        ans = self.ask_human(question)
        if not ans:
            self.unanswered.append(question)
            return "NO ANSWER (candidate not available). If the field is required: finish(status='needs_human')."
        from core import answers
        answers.remember(question, ans)                     # asked once, never again (answers.json)
        return ans

    # ---------- autopilot: the known steps without the LLM ----------
    NEXT = re.compile(r"^(suivant|next|continuer|continue|v[ée]rifier|review|examiner|enregistrer et continuer|"
                      r"save and continue|[ée]tape suivante|next step)$", re.I)

    NOT_APPLY = re.compile(r"projet|contact|devis|newsletter|rappel|demo|d[ée]mo|abonn|subscribe|search|recherch", re.I)

    def autopilot(self, profile: dict, max_rounds: int = 8) -> list[str]:
        """Fills the EMPTY fields whose value is known (core/autofill.py), unticks opt-ins, attaches the CV if one
        is required, then clicks "Suivant" / "Vérifier" (and "Envoyer" when sending is allowed) as long as no required
        field is missing and no error is shown. Stops at the first thing it does not know: the LLM takes over.
        Returns what it did (empty = nothing)."""
        from core.autofill import mobility_boxes, value_for, question_of
        prof = profile or self.profile_for_auto
        done = []
        for _ in range(max_rounds):
            if self.success or self.submitted or self.auto_sent:
                break                                       # sent: the autopilot never touches anything again
            els = self._scan()
            if self.success or self.captcha or self._errors():
                break
            if policy.PASSKEY_PAGE.search(self.page.url):     # passkey enrolment: always "later", never "continue"
                later = sorted((e for e in els if e["role"] in ("button", "a", "link", "input") and not e["disabled"]
                                and policy.LATER_BTN.search(e["name"])),
                               key=lambda e: 0 if re.search(r"plus tard|later|not now|pas maintenant|skip", e["name"], re.I) else 1)
                if not later or self._auto_click(later[0], done, "auto_passkey_later") is None:
                    break
                continue
            form_open = any(e.get("in_dialog") or e.get("in_apply_form") for e in els)
            if any(e.get("in_dialog") for e in els):
                els = [e for e in els if e.get("in_dialog")]
            board = policy.on_board_offer_page(self.page.url, self.ctx) and not form_open
            if board:                                         # job board page: only the Easy Apply start button
                if self.started:
                    break                                   # started once (by it or by the LLM): never again
                start = [e for e in els if policy.EASY_START.match(e["name"]) and not e["disabled"]
                         and e["role"] in ("button", "input")]
                if not start:
                    break
                if self._auto_click(start[0], done, "auto_start") is None:
                    break
                continue
            missing = False
            radios: dict[str, list] = {}
            boxes: dict[str, list] = {}
            for e in els:
                if e["disabled"]:
                    continue
                typ, role, name = (e.get("type") or "").lower(), e["role"], e["name"]
                if typ == "radio":
                    radios.setdefault(question_of(name), []).append(e)
                    continue
                if typ == "checkbox":
                    if policy.TALENT.search(name) and not policy.NEGATIVE.search(name) \
                            and prof.get("consent_future_opportunities", True):
                        if e["checked"] is False:
                            self._auto_check(e, True, done)     # "contact me about future opportunities": yes
                    elif e["checked"] is True and policy.OPT_IN.search(name):
                        self._auto_check(e, False, done)
                    elif e["checked"] is False and policy.LEGAL.search(name) and not policy.OPT_IN.search(name) \
                            and self.ctx.get("approve_legal"):
                        self._auto_check(e, True, done)     # privacy / conditions: needed even without a "*"
                    elif "[question:" in name:
                        boxes.setdefault(question_of(name), []).append(e)   # "Mobilité *": Toulouse / IDF / ...
                    elif e["checked"] is False and e["required"]:
                        missing = True
                    continue
                if typ == "file":
                    if e["required"] and not e["value"]:
                        if self.cv_path and Path(self.cv_path).exists() and self._auto_upload(e, done):
                            continue
                        missing = True
                    continue
                if e.get("search"):
                    if not e["value"] and not self._near_selection(e):
                        value = value_for(name, "search", None, prof)
                        if value and self._auto_search(e, value, done):
                            continue
                        if e["required"]:
                            missing = True
                    continue
                if role in ("button", "a", "link", "option", "menuitem", "tab") or e.get("dropdown"):
                    if e.get("dropdown") and e["required"] and re.match(r"^(s[ée]lectionnez|select|choisissez)", name, re.I):
                        missing = True                     # custom dropdown: the LLM uses select_option
                    continue
                empty = not e["value"] or (role == "select" and not e["value"])
                if not empty:
                    continue
                kind = "select" if role == "select" else "textarea" if role == "textarea" else \
                    "number" if typ == "number" else "text"
                value = None if kind == "textarea" else value_for(name, kind, e.get("options"), prof)
                if value is None:
                    if e["required"]:
                        missing = True
                    continue
                if not self._auto_fill(e, kind, value, done) and e["required"]:
                    missing = True
            for q, group in radios.items():
                if any(r["checked"] is True for r in group):
                    continue
                value = value_for(group[0]["name"], "radio", [r["name"].split(" [question")[0] for r in group],
                                  prof)
                pick = [r for r in group if value and _norm(r["name"].split(" [question")[0]) == _norm(value)]
                raw_q = group[0]["name"].split("[question:", 1)[-1]          # the question as written (with its "*")
                required = any(r["required"] for r in group) or re.search(r"[*✱∗＊]\s*\]?\s*$|obligatoire|required", raw_q, re.I)
                if pick:
                    self._auto_check(pick[0], True, done)
                elif required:
                    missing = True                          # a required question it does not know: the LLM decides
            for q, group in boxes.items():                  # a required question answered by ticking boxes
                raw_q = group[0]["name"].split("[question:", 1)[-1]
                labels = [b["name"].split(" [question")[0] for b in group]
                wanted = mobility_boxes(q, labels, prof)    # "Mobilité *": partout, else your cities
                if wanted and not any(b["checked"] is True for b in group):
                    for b, lab in zip(group, labels):
                        if lab in wanted:
                            self._auto_check(b, True, done)
                    continue
                if not any(b["checked"] is True for b in group) and \
                        (any(b["required"] for b in group) or re.search(r"[*✱∗＊]\s*\]?\s*$|obligatoire|required", raw_q, re.I)):
                    missing = True                          # which ones (cities...): the LLM decides
            if missing:
                break
            els = self._scan()
            if self._errors():
                break
            # only the buttons of THE application form: in the dialog, else in the form with the fields
            # (Davidson: a footer link "Soumettre un projet" went to the contact page)
            dialog, in_form = any(x.get("in_dialog") for x in els), any(x.get("in_apply_form") for x in els)
            nxt = [e for e in els if not e["disabled"] and e["role"] in ("button", "a", "link", "input")
                   and (e.get("in_dialog") if dialog else e.get("in_apply_form") if in_form else e["role"] != "a")
                   and not self.NOT_APPLY.search(e["name"])
                   and (self.NEXT.match(e["name"].strip())
                        or (policy.SUBMIT.search(e["name"]) and e["role"] not in ("a", "link"))
                        or (in_form and not dialog and policy.AMBIGUOUS_SEND.match(e["name"].strip())))]
            if not nxt:
                break
            before = [(e["role"], e["name"]) for e in els]
            if self._auto_click(nxt[-1], done, "auto_next") is None:
                break                                       # the send button without permission: the LLM decides
            after = [(e["role"], e["name"]) for e in self._scan()]
            if after == before and not self.success:
                break                                       # nothing moved (an error we did not see): the LLM looks
        return done

    @property
    def profile_for_auto(self) -> dict:
        from core import answers
        try:
            return json.loads(answers.PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _auto_click(self, e: dict, done: list, kind: str):
        loc, el = self._el(e["ref"])
        verdict, reason = policy.check("click", el, self.page.url, self.ctx)
        if verdict != policy.ALLOW:
            return None
        self._arm(el.get("name") or "")
        before_pages = len(self.opened)
        try:
            _press(loc)                                     # covered / animated: falls back to a DOM click
        except Exception as ex:                             # gone: the LLM decides what to do
            self._write("autopilot_click_failed", el=el["name"], error=str(ex)[:200])
            return None
        self.page.wait_for_timeout(1200)
        if len(self.opened) > before_pages:
            self._follow_new_tab(before_pages)
        if reason == "submit":
            self.auto_sent = True                           # counts as SENT only when the site confirms it
            self.armed = True
            self.page.wait_for_timeout(800)
            if self._errors():                              # "ne peut pas être vide": NOT sent, the LLM completes it
                self.auto_sent = False
            self._write("auto_send_clicked", el=el["name"], url=self.page.url)
        if policy.EASY_START.match(el["name"]) or policy.EXTERNAL_START.match(el["name"]):
            self.started = True
        self._write(kind, el=el["name"], url=self.page.url, auto=True)
        done.append(f'clicked "{el["name"][:50]}"')
        self._scan()
        if self.success:
            self.submitted = True
        return True

    def _auto_fill(self, e: dict, kind: str, value: str, done: list) -> bool:
        loc, el = self._el(e["ref"])
        try:
            if kind == "select":
                choice = best_option(value, e.get("options") or [])
                if choice is None:
                    return False
                loc.select_option(label=choice, timeout=5000)
                value = choice
                self._write("select", ref=e["ref"], el=el["name"], option=value, chosen=value, auto=True)
            else:
                loc.fill(value, timeout=5000)
                frame = self.frames.get(e["ref"]) or self.page.main_frame
                try:
                    loc.press("End")                        # key event: lists opened on keyup (Lever) wake up
                except Exception:
                    pass
                listed = self._list_opened(frame, _list_wait(el["name"]))
                if kind == "text" and (listed or not loc.input_value()):   # a list opened / emptied itself (Lever)
                    self.elements[e["ref"]]["search"] = True
                    return self._auto_search(e, value, done)
                if _digits(loc.input_value()) != _digits(value):
                    return False
                self._write("type", ref=e["ref"], el=el["name"], text=value, verified=True, auto=True)
        except Exception:
            return False
        done.append(f'{el["name"][:40]} = {value[:40]}')
        return True

    def _near_selection(self, e: dict) -> bool:
        """Workday shows a chosen value as a pill next to the (then empty) search box."""
        loc, _ = self._el(e["ref"])
        try:
            return loc.evaluate("""e => { let n = e.parentElement;
                for (let up = 0; up < 4 && n; up++, n = n.parentElement)
                    if (n.querySelector('[data-automation-id=selectedItem], [class*=pill i], [class*=chip i], [class*=token i]'))
                        return true;
                return false; }""")
        except Exception:
            return False

    def _auto_search(self, e: dict, value: str, done: list) -> bool:
        out = self.search_select(e["ref"], value, value)
        ok = out.startswith("selected") and "(verified: True)" in out
        if ok:
            self.llm_fills.pop()                            # already known: nothing to learn
            done.append(f'{e["name"][:40]} = {value[:40]} (searched)')
        return ok

    def _auto_check(self, e: dict, checked: bool, done: list):
        loc, el = self._el(e["ref"])
        if policy.check("check" if checked else "uncheck", el, self.page.url, self.ctx)[0] != policy.ALLOW:
            return
        try:
            loc.click(timeout=5000)
            self.page.wait_for_timeout(300)
        except Exception:
            return
        self._write("set_checked", ref=e["ref"], el=el["name"], wanted=checked, auto=True)
        done.append(f'{"ticked" if checked else "unticked"} "{el["name"][:50]}"')

    def _auto_upload(self, e: dict, done: list) -> bool:
        loc, el = self._el(e["ref"])
        if self.cv_uploads >= 2:                            # given twice already: the LLM / the human decide
            return False
        before = self._form_sig()
        try:
            loc.set_input_files(self.cv_payload())
        except Exception:
            return False
        self.cv_uploads += 1
        filled = self._settle_after_upload(before)          # the site reads the CV and fills the form: wait for it
        self._write("upload_cv", ref=e["ref"], el=el["name"], file=Path(self.cv_path).name, auto=True,
                    **({"fields_filled_by_site": filled} if filled else {}))
        done.append(f"CV {Path(self.cv_path).name} attached" + (
            " -- the site read it and filled the form (experience / education entries: keep them, do not add more)"
            if filled else ""))
        return True

    # ---------- exploring an unknown page ----------
    def find(self, text: str) -> str:
        """Every clickable element (no filter, all frames) whose name contains one of the words a|b|c."""
        els = self._scan()
        words = [w.strip().lower() for w in text.split("|") if w.strip()]
        hits = [e for e in els if any(w in e["name"].lower() for w in words)]
        if not hits:
            return f"nothing matches '{text}' ({len(els)} elements on the page). Try other words, scroll, or look."
        return "\n".join(f"  [{e['ref']}] {e['role']} \"{e['name'][:200]}\"" + ("" if e["in_viewport"] else " (below, scroll)")
                         for e in hits[:20])

    def scroll(self, direction: str = "down") -> str:
        self.page.mouse.wheel(0, -900 if direction == "up" else 900)
        self.page.wait_for_timeout(700)
        return "scrolled.\n" + self.read_page()

    def look(self) -> str:
        """Screenshot for the LLM (config [apply] vision): to understand a page the element list does not explain."""
        if not self.ctx.get("vision", True):
            return "vision disabled (config [apply] vision = false): use read_page / get_text / find."
        import base64
        try:
            self.page.bring_to_front()                    # a background / minimized tab does not paint
            shot = self.page.screenshot(type="jpeg", quality=55, timeout=8000)
        except Exception as e:
            return (f"no screenshot ({type(e).__name__}: the Chrome window may be minimized). "
                    "Use read_page / get_text / find instead.")
        self.pending_image = base64.b64encode(shot).decode()
        self._write("look", bytes=len(shot))
        return "screenshot taken: it is in the next message."

    def wait_for_human(self, reason: str) -> str:
        """Captcha, security check, login, account: the human does it in the Chrome window (supervised mode)."""
        self._write("wait_for_human", reason=reason, supervised=bool(self.ctx.get("supervised")))
        if not self.ctx.get("supervised"):
            self.unanswered.append(reason)
            return "NOBODY HERE (unattended run): finish(status='needs_human') and say what is needed."
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        paused = self._pause_file_pickers()             # your own "Attach / Joindre" works while you act
        try:
            ans = self._ask_human_needed(reason)
        finally:
            self._resume_file_pickers(paused)
        a = ans.strip().lower()
        if a in ("skip", "s"):
            self.unanswered.append(reason)
            return "the human skipped it: finish(status='needs_human')."
        if a in ("none", "no", "non", "n", "rien", "nothing", "aucun", "pas de captcha"):
            self.no_captcha_hosts.add(policy.host(self.page.url))
            self._write("false_alarm", reason=reason, url=self.page.url)
            return ("the human checked: there is NOTHING to do here (no captcha, no login). Do not call wait_for_human "
                    "again for this; continue the application.\n" + self.read_page())
        self.human_steps.append(reason)
        self._alive_page()
        try:
            self.page.wait_for_timeout(1500)
        except Exception:
            self._alive_page()
        if LOGIN_REASON.search(reason):
            self._save_login_after_human()
        return "the human did it.\n" + self.read_page()

    def _save_login_after_human(self):
        """You logged in by hand: the site goes into accounts.json (next time: "sign in", not "create").
        In a terminal you can also give the email and the password used there (hidden input), so the agent signs
        in alone next time. The password never goes to the AI, the logs or Telegram."""
        from core import accounts
        site = policy.host(self.page.url)
        login, pw = "", ""
        ask_secret = self.ctx.get("ask_secret")
        if ask_secret is None:
            import sys
            if sys.stdin and sys.stdin.isatty():
                import getpass
                ask_secret = lambda q, hidden: (getpass.getpass(q) if hidden else input(q))
        if ask_secret:
            try:
                login = ask_secret(f"    Save the login of {site} for next time? E-mail used (Enter = no): ", False).strip()
                if login:
                    pw = ask_secret("    Password used there (hidden; Enter = the default one from .env): ", True)
            except (EOFError, OSError):
                login, pw = "", ""
        accounts.save_login(site, login, pw)
        self._write("login_saved", site=site, login=login, own_password=bool(pw))   # never the password itself

    def _alive_page(self):
        """The current tab was closed (a CGU / privacy tab, a popup that closed itself...): continue on the most
        recent tab still open (the application form) instead of crashing."""
        try:
            if not self.page.is_closed():
                return
            pages = [pg for pg in self.page.context.pages if not pg.is_closed()]
        except Exception:
            return
        if pages:
            self.page = pages[-1]
            self._write("page_closed_switch", url=self.page.url)

    def _ask_human_needed(self, reason: str) -> str:
        return self.ask_human(f"\a\n>>> HUMAN NEEDED in the Chrome window: {reason}\n"
                             f"    page: {self.page.url[:100]}\n"
                             f"    Do it, then press Enter.  'none' = nothing to do here (false alarm).  'skip' = give up > ")

    # ---------- logging ----------
    def _write(self, kind, **kw):
        self.log_kinds.add(kind)
        self.log.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"),
                                   "kind": kind, "shot": self.n, **kw}, ensure_ascii=False) + "\n")
        self.log.flush()


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "") or (s or "").strip().lower()


# "this email already has an account" (sign-up refused): the human logs in instead
ACCOUNT_EXISTS = re.compile(r"(adresse|e-?mail|courriel|compte|account|identifiant|login|user(name)?)[^.\n]{0,50}"
                            r"(existe d[ée]j[àa]|d[ée]j[àa] (utilis|enregistr|associ|pris|existant|inscrit)|"
                            r"already (exists|in use|registered|taken|associated))|"
                            r"(un|a) (compte|account) (existe d[ée]j[àa]|already exists)|"
                            r"vous avez d[ée]j[àa] un compte|you already have an account", re.I)
LOGIN_REASON = re.compile(r"log ?in|sign ?in|connect|connexion|identifi|compte|account|mot de passe|password", re.I)

NO_ITEMS = re.compile(r"^(aucun (article|r[ée]sultat|[ée]l[ée]ment)|no (items?|results?|matches)|nothing found|"
                      r"pas de r[ée]sultat|0 r[ée]sultats?|aucune correspondance|r[ée]sultats de la recherche|"
                      r"search results)", re.I)
OTHER = re.compile(r"^(autres?|others?)\b", re.I)


GENERIC_WORDS = {"universite", "university", "ecole", "school", "institut", "institute", "college", "faculte",
                 "superieure", "nationale", "national", "centre", "center", "groupe", "group", "france", "paris"}


def _same_key(wanted: str, choice: str) -> bool:
    """The distinctive words of what is wanted ("limoges") are all in the choice."""
    key = {w for w in _norm(wanted).split() if len(w) >= 4} - GENERIC_WORDS
    return not key or key <= set(_norm(choice).split())


def _list_wait(name: str) -> int:
    """How long to watch for a suggestion list after typing: long only where one is likely."""
    return 2000 if re.search(r"location|localisation|ville|city|adresse|address|lieu|pays|country|school|"
                             r"[ée]tablissement|universit|[ée]cole|company|entreprise|soci[ée]t[ée]|titre|title|"
                             r"intitul|poste|position|skill|comp[ée]tence|langue|language", name, re.I) else 500


def _scroll(loc):
    try:
        loc.scroll_into_view_if_needed(timeout=3000)
    except Exception:                                    # hidden / in a closed panel: the action itself will tell
        pass


def _press(loc) -> str:
    """A click that does not give up after 30 s on a covered / animated / hidden button."""
    try:
        loc.click(timeout=6000)
        return "normal"
    except Exception:
        pass
    # covered (transparent overlay, spinner, cookie layer) or animated: the DOM click reaches the button itself
    # (a forced mouse click would land on the overlay). Raises if the element is gone.
    if not loc.is_visible():                           # a HIDDEN element is never clicked (wrong one, Air Liquide)
        raise RuntimeError("element not visible: not clicked")
    loc.evaluate("e => e.click()")
    return "js"


JS_SET = """(e, v) => {
    if (e.isContentEditable) { e.focus(); e.innerText = v; }
    else {
        const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, v);
    }
    for (const t of ['input', 'change', 'blur']) e.dispatchEvent(new Event(t, {bubbles: true}));
    return e.isContentEditable ? e.innerText : e.value; }"""


def _js_set(loc, text: str) -> str:
    try:
        return loc.evaluate(JS_SET, text) or ""
    except Exception:
        return ""


def _best_words(wanted: str, options: list[str]) -> str | None:
    """The option sharing the most words with what is wanted ("Université de Limoges" ~ "Univ. Limoges")."""
    w = set(_norm(wanted).split()) - {"de", "du", "des", "la", "le", "of", "the", "et", "and"}
    scored = sorted(((len(w & set(_norm(o).split())), -len(o), o) for o in options), reverse=True)
    return scored[0][2] if scored and scored[0][0] > 0 else None


def resolve_cv(path: str) -> str:
    """config [apply] cv_path: absolute, or relative to the project ("cv/my_cv.pdf"). A missing leading "/" before
    "mnt/c/..." (WSL) is tolerated."""
    from core.config import ROOT
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        p = Path("/" + path) if path.startswith("mnt/") and Path("/" + path).exists() else ROOT / path
    return str(p)


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9+]+", " ", s).split())


def best_option(wanted: str, options: list[str]) -> str | None:
    """The option the agent meant: exact, same words, contains, then numbers ("5 ans" -> "3 à 5 ans" / "5+")."""
    real = [o for o in options if o and not re.match(r"^(s[ée]lectionnez|select|choisissez|choose|--)", o, re.I)]
    w = _norm(wanted)
    for o in real:
        if o == wanted or _norm(o) == w:
            return o
    hits = [o for o in real if w and (w in _norm(o) or _norm(o) in w)]
    if len(hits) == 1:
        return hits[0]
    n = re.findall(r"\d+", w)
    if n:
        n = int(n[0])
        def fits(o):
            raw = _norm(o)
            t = re.sub(r"\b(d un|un|une|one|a)\b(?= (an|ans|annee|year|years)\b)", "1", raw)   # "moins d'un an"
            nums = [int(x) for x in re.findall(r"\d+", t)]
            if not nums:
                return False
            if len(nums) >= 2:
                return nums[0] <= n <= nums[1]
            if re.search(r"\bmoins\b|less than|under|fewer", raw):
                return n < nums[0]
            if re.search(r"au moins|at least|ou plus|or more", raw) or "+" in o:
                return n >= nums[0]
            if re.search(r"plus de|more than|over|superieur", raw):
                return n > nums[0]
            return nums[0] == n
        fit = [o for o in real if fits(o)]
        if fit:
            return fit[0]
    return None


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": required or list((props or {}).keys())}}}


REF = {"ref": {"type": "string"}}
TOOL_SPECS = [
    _fn("read_page", "Current page: title, headings, form elements with refs (e.g. e12)."),
    _fn("get_text", "Main visible text of the page (questions, job description)."),
    _fn("click", "Click a button or link by ref.", REF),
    _fn("type_text", "Replace the content of a text field by ref.", {**REF, "text": {"type": "string"}}),
    _fn("fill_password", "Type the candidate's default account password into a password field (or its "
        "confirmation). You never see it.", REF),
    _fn("search_select", "Search field (search-field(use search_select): Workday 'Établissement', city, skills): types "
        "query, picks the best suggestion and checks it is selected. query = a distinctive word ('Limoges'), option = "
        "the full answer ('Université de Limoges').",
        {**REF, "query": {"type": "string"}, "option": {"type": "string"}}, ["ref", "query"]),
    _fn("select_option", "Choose an option in a select / dropdown by ref. Use one of the options listed in the page "
        "state (options=[...]); a number like '3' picks the matching range.", {**REF, "option": {"type": "string"}}),
    _fn("set_checked", "Set a checkbox/switch/radio on (true) or off (false). Real state is verified.",
        {**REF, "checked": {"type": "boolean"}}),
    _fn("upload_cv", "Upload the candidate's CV into a file input by ref.", REF),
    _fn("ask_human", "Ask the candidate something the profile does not answer.", {"question": {"type": "string"}}),
    _fn("find", "Find clickable elements whose text contains one of the words (a|b|c), in the whole page and its "
        "frames. Use it when you do not see the apply button / next step.", {"text": {"type": "string"}}),
    _fn("scroll", "Scroll the page (forms often load lower).", {"direction": {"type": "string", "enum": ["down", "up"]}}),
    _fn("look", "Get a screenshot of the page, to understand a page that the element list does not explain."),
    _fn("wait_for_human", "Captcha, security check, login or account creation: the human does it in the browser. "
        "Returns when done.", {"reason": {"type": "string"}}),
    _fn("finish", "Stop. On the final review page (before sending), when stuck, or when a human is needed.",
        {"status": {"type": "string", "enum": ["ready_for_review", "submitted", "needs_human", "stuck"]},
         "summary": {"type": "string", "description": "Every answer given + what the human must check or do."}}),
]
