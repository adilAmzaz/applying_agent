"""Browser session: attach to your Windows Chrome (CDP) or launch Playwright's Chromium (tests)."""

import json
import os
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import Page

from core.config import ROOT

PROFILE_DIR = ROOT / "browser-profile"

# JavaScript run inside the page: find interactive elements, tag them, describe them.
# The data-agent-ref attribute lets us target the element later: [data-agent-ref="e12"]
SCAN_JS = r"""
(prefix) => {
  // web components (SmartRecruiters "spl-input"...): the fields live in OPEN SHADOW ROOTS, invisible to
  // document.querySelectorAll -> search the document AND every shadow root inside it
  const deepAll = (s, root = document, out = []) => {
    root.querySelectorAll(s).forEach(e => out.push(e));
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) deepAll(s, e.shadowRoot, out); });
    return out;
  };
  const hostOf = el => { const r = el.getRootNode(); return r && r.host ? r.host : null; };
  const closestDeep = (el, s) => {                  // closest() that also climbs out of shadow roots
    for (let n = el; n; n = hostOf(n)) { const c = n.closest(s); if (c) return c; }
    return null;
  };
  const sel = [
    'a[href]', 'button', 'input', 'select', 'textarea',
    '[role=button]', '[role=link]', '[role=checkbox]', '[role=switch]',
    '[role=radio]', '[role=combobox]', '[role=tab]', '[contenteditable=true]',
    '[role=option]', '[role=menuitem]', '[role=menuitemradio]', '[aria-haspopup=listbox]'
  ].join(',');

  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };

  const nameOf = el => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const by = el.getAttribute('aria-labelledby');
    if (by) return by.split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ');
    if (el.id) {
      const lab = el.getRootNode().querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) return lab.innerText;
    }
    const host = hostOf(el);                          // field inside a web component: its label is on the host
    if (host) {
      const own = el.closest('label') || el.getRootNode().querySelector('label');
      const t = host.getAttribute('label') || host.getAttribute('aria-label') || (own && own.innerText)
                || host.getAttribute('placeholder') || '';
      if (t.trim()) return t;
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText;
    // floating label: <div><input><label>Nom*</label></div>, the label AFTER the field (UIMM, Material...);
    // without this the field took the text written BEFORE it (the previous field's label: one field off)
    const par = el.parentElement;
    const own = par && par.querySelectorAll('input:not([type=hidden]), select, textarea');
    if (el.matches('input, select, textarea') && own && own.length === 1 && own[0] === el) {
      const lab = [...par.children].find(c => c.tagName === 'LABEL' && !c.querySelector('input, select, textarea'));
      const other = lab && lab.htmlFor && document.getElementById(lab.htmlFor);
      if (lab && (!other || other === el) && lab.innerText.trim()) return lab.innerText;
    }
    if (el.tagName === 'SELECT') return el.title || '';     // not the text of all its options
    return el.innerText || el.value || el.placeholder || el.title || el.name || '';
  };

  // short checkbox / radio labels ("Confirmé", "Oui") get the question written just before them
  const questionOf = el => {
    const fs = el.closest('fieldset');
    if (fs && fs.querySelector('legend')) return fs.querySelector('legend').innerText;
    let n = el.closest('label') || el;
    for (let up = 0; up < 4 && n; up++, n = n.parentElement) {
      let prev = n.previousElementSibling;
      // skip empty nodes and the OTHER options of the same question ("C1" before "C2", "Yes" before "No")
      const isOption = p => isChoiceButton(p) || p.matches('input[type=radio], input[type=checkbox]')
                            || (p.matches('label') && !!p.querySelector('input[type=radio], input[type=checkbox]'));
      while (prev && (!(prev.innerText || '').trim() || isOption(prev))) prev = prev.previousElementSibling;
      // a <label> that is not tied to ANOTHER field is the question title (Ashby: "English level", "Are you...")
      if (prev && prev.matches('label') && !prev.querySelector('input, select, textarea')) {
        const target = prev.htmlFor && document.getElementById(prev.htmlFor);
        if (!target || target === el || n.contains(target)) {
          const t = prev.innerText.trim();
          if (t.length > 2 && t.length < 400) return t;
        }
        return '';
      }
      if (prev && (prev.matches('label, input, select, textarea, button') || prev.querySelector('input, select, textarea')))
        return '';                                      // another field (or its label) is not a question
      if (prev && prev.innerText.trim().length > 15
          && prev.innerText.length < 400) return prev.innerText;
    }
    return '';
  };

  // Yes / No answered with BUTTONS (Ashby, Lever...): same question context + their selected state
  const YESNO = /^(yes|no|oui|non|true|false|vrai|faux|maybe|peut-[êe]tre)$/i;
  const isChoiceButton = el => (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button')
                               && YESNO.test((el.innerText || '').trim());
  const pressed = el => {
    const a = el.getAttribute('aria-pressed') ?? el.getAttribute('aria-checked') ?? el.getAttribute('aria-selected');
    if (a !== null) return a === 'true';
    return /(^|[\s_-])(active|selected|checked|is-selected|isActive|_active)/i.test(el.className || '');
  };

  // labels of the previous scan are removed first: a hidden element keeping an old "e6" made "e6" point to
  // two elements (Workday: the consent dropdown AND the hidden language selector)
  deepAll('[data-agent-ref]').forEach(e => e.removeAttribute('data-agent-ref'));
  const out = [];
  let i = 0;
  for (const el of deepAll(sel)) {
    const isFile = el.tagName === 'INPUT' && el.type === 'file';
    if (!visible(el) && !isFile) continue;          // file inputs are often hidden behind a drop zone: keep them
    // helper inputs hidden from people (Greenhouse "requiredInput" next to each dropdown, aria-hidden, tabindex -1):
    // filling them does nothing, and they looked like empty REQUIRED duplicates of the real field -> loops
    if (!isFile && (el.getAttribute('aria-hidden') === 'true' || closestDeep(el, '[aria-hidden=true]'))) continue;
    const ref = (prefix || 'e') + (++i);
    el.setAttribute('data-agent-ref', ref);
    const r = el.getBoundingClientRect();
    out.push({
      ref,
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      // search field: type, then pick in the suggestion list (Workday "Établissement", city fields...)
      search: el.tagName === 'INPUT' && !['checkbox', 'radio', 'file', 'hidden'].includes(el.type)
              && (el.getAttribute('data-automation-id') === 'searchBox'
              || el.getAttribute('aria-autocomplete') === 'list' || el.getAttribute('aria-autocomplete') === 'both'
              || el.getAttribute('role') === 'combobox'
              // Workday (wd1..wd5): "Établissement ou université" = a select-input searched with Enter
              || !!el.closest('[data-uxi-widget-type=selectinput], [data-automation-id*=multiselect i], '
                              + '[data-automation-id*=multiSelect], [data-automation-id=searchBox]')),
      dropdown: el.tagName !== 'SELECT' && el.tagName !== 'INPUT' && (el.getAttribute('role') === 'combobox'
                || ['listbox', 'true', 'menu'].includes(el.getAttribute('aria-haspopup') || '')),
      type: el.type || null,
      name: (() => {
        let n = nameOf(el).replace(/\s+/g, ' ').trim();
        if (isFile) {                                 // hidden input of a drop zone: name it from the zone around it
          // the text around it (a drop zone inside a web component: the text of its shadow root)
          const txt = z => ((z.innerText || '') + ' ' + (z.shadowRoot
                ? [...z.shadowRoot.children].map(c => c.innerText || '').join(' ') : '')).trim();
          let z = el.parentElement || hostOf(el);
          for (let up = 0; up < 4 && z && txt(z).length < 6; up++) z = z.parentElement || hostOf(z);
          const zone = z ? txt(z).replace(/\s+/g, ' ').trim().slice(0, 80) : '';
          n = ((n && n !== el.name) ? n : (zone || 'file')) + ' (file input)';   // its label, else the zone text
        }
        if (!n && ['SELECT', 'INPUT', 'TEXTAREA'].includes(el.tagName) && !isFile) {
          n = questionOf(el).replace(/\s+/g, ' ').trim().slice(0, 160) || el.name || el.placeholder || '';
        }
        if ((['checkbox', 'radio'].includes(el.type) || ['radio', 'checkbox'].includes(el.getAttribute('role'))
             || isChoiceButton(el)) && n.length < 40) {
          const q = questionOf(el).replace(/\s+/g, ' ').trim();
          if (q && !q.includes(n)) n = n + ' [question: ' + q.slice(0, 140) + ']';
        }
        return n.slice(0, 200);
      })(),
      value: el.tagName === 'SELECT' ? ((el.selectedIndex > 0 && el.options[el.selectedIndex]) ? el.options[el.selectedIndex].text.trim().slice(0, 60) : '')
             : ['input', 'textarea'].includes(el.tagName.toLowerCase()) && !['password', 'checkbox', 'radio'].includes(el.type)
             ? (el.value || '').slice(0, 60) : null,
      options: el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).filter(Boolean).slice(0, 25) : null,
      checked: ['checkbox', 'radio'].includes(el.type) ? el.checked
               : isChoiceButton(el) ? pressed(el) : (el.getAttribute('aria-checked') ?? null),
      required: el.required || el.getAttribute('aria-required') === 'true'
                || !!(hostOf(el) && (hostOf(el).hasAttribute('required') || hostOf(el).getAttribute('aria-required') === 'true'))
                || /[*✱∗＊]\s*$|obligatoire|required/i.test(nameOf(el).trim()),     // Lever: "✱"
      invalid: el.getAttribute('aria-invalid') === 'true' || (el.matches && el.matches(':invalid') && !!el.value),
      disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
      in_viewport: r.top < innerHeight && r.bottom > 0,
      in_dialog: !!closestDeep(el, '[role=dialog], dialog, .artdeco-modal'),
      // inside an application form drawn on the offer page itself (has a file / email / long text field)
      in_apply_form: (f => !!f && deepAll('input[type=file], input[type=email], textarea', f).length > 0)
                     (el.form || closestDeep(el, 'form') ||      // a button linked by form="id", or a form
                      (el.closest && el.closest('#postuler, [id*=postul i], [id*=apply i], [class*=apply-form i]'))),
      box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    });
  }
  return out;
}
"""


def find_chrome(url: str | None = None, agent: str = "") -> str | None:
    """Windows Chrome (start_chrome.bat) is the default. BROWSER=chromium -> Playwright Chromium."""
    if os.environ.get("BROWSER", "").lower() == "chromium":
        return None
    url = url or os.environ.get("CDP_URL", "http://localhost:9222")
    port = url.rsplit(":", 1)[-1]
    try:
        urllib.request.urlopen(url + "/json/version", timeout=2)
        return url
    except Exception:
        sys.exit(f"\nWindows Chrome{' of agent ' + agent if agent else ''} not reachable at {url}.\n"
                 f"  1. From Windows: start_all_chromes.bat, or start_chrome.bat {agent if agent and agent != 'main' else ''}"
                 " (project folder)\n"
                 f"  2. Check from WSL: curl -s localhost:{port}/json/version\n"
                 "  3. If curl fails: .wslconfig needs networkingMode=mirrored, then 'wsl --shutdown'")


class Session:
    """CDP: attach to the Chrome you started (Google login works, closing = disconnect only).
    Otherwise: Playwright launches Chromium (HEADLESS=1 for tests)."""

    def __init__(self, p, agent: str | None = None):
        """agent: name in config.toml [agents] -> its own Chrome (port, profile). None: CDP_URL / port 9222."""
        from core.agents import cdp_url
        self.agent = agent
        self.cdp = find_chrome(cdp_url(agent) if agent else None, agent or "")
        if self.cdp:
            try:
                tabs = [t for t in json.load(urllib.request.urlopen(self.cdp + "/json/list", timeout=3))
                        if t.get("type") == "page"]
            except Exception:
                tabs = []
            try:
                # Playwright attaches to EVERY open tab: a frozen/discarded tab can hang this
                self.browser = p.chromium.connect_over_cdp(self.cdp, timeout=30_000)
            except Exception as e:
                sys.exit(f"\nChrome did not answer in 30 s ({type(e).__name__}), {len(tabs)} tabs open.\n"
                         "  Close all windows of the agent Chrome, run start_chrome.bat again, retry.")
            self.ctx = self.browser.contexts[0]
        else:
            profile = Path(os.environ.get("BROWSER_PROFILE") or PROFILE_DIR)
            if agent:
                profile = profile / agent                    # one profile per agent (tests run them in parallel)
            profile.mkdir(parents=True, exist_ok=True)
            self.browser = None
            self.ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=os.environ.get("HEADLESS") == "1",
                locale="fr-FR", viewport={"width": 1400, "height": 900})

    def new_tab(self, url: str | None = None) -> Page:
        page = self.ctx.new_page()
        if url:
            page.goto(url)
            page.wait_for_load_state("domcontentloaded")
        return page

    def close_tabs_except(self, keep: list):
        for pg in list(self.ctx.pages):
            if pg not in keep and pg.url.startswith(("http", "about:blank")):
                try:
                    pg.close()
                except Exception:
                    pass

    def close(self):
        if self.browser:            # CDP: disconnect only, your Chrome stays open
            self.browser.close()
        else:
            self.ctx.close()


class SessionPool:
    """review / apply_one: each offer is opened in the Chrome of the agent logged in to its site
    (a LinkedIn offer in the LinkedIn agent's Chrome...). Chromes are attached only when needed."""

    def __init__(self, p):
        self.p, self.sessions = p, {}

    def for_platform(self, platform: str) -> "Session":
        from core.agents import agent_for_platform
        name = agent_for_platform(platform)
        if name not in self.sessions:
            self.sessions[name] = Session(self.p, name)
        return self.sessions[name]

    @property
    def cdp(self):
        return True

    def close(self):
        for s in self.sessions.values():
            s.close()
