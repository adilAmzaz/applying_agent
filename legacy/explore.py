"""
Step 1 of the job agent: see a web page the way an LLM agent will see it.

No LLM and no automatic clicking yet. The script:
  1. opens Chromium with a PERSISTENT profile (you log in once, the session stays)
  2. scans the page and gives every interactive element a short ref (e1, e2...)
  3. prints that list + saves JSON, a screenshot and the ARIA tree in runs/
  4. waits: you click around yourself in the window, press Enter to rescan

Usage:
  python explore.py login                 # first time: log in to Indeed by hand
  python explore.py inspect <url>         # scan a page, rescan on each Enter

  Default browser = your Windows Chrome: run start_chrome.bat first.
  BROWSER=chromium python explore.py ...   -> Playwright's Linux Chromium instead
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

PROFILE_DIR = Path("./browser-profile")   # cookies + login live here
RUNS_DIR = Path("./runs")

# JavaScript run inside the page: find interactive elements, tag them, describe them.
# The data-agent-ref attribute lets us target the element later: [data-agent-ref="e12"]
SCAN_JS = r"""
() => {
  const sel = [
    'a[href]', 'button', 'input', 'select', 'textarea',
    '[role=button]', '[role=link]', '[role=checkbox]', '[role=switch]',
    '[role=radio]', '[role=combobox]', '[role=tab]', '[contenteditable=true]'
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
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) return lab.innerText;
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText;
    return el.innerText || el.value || el.placeholder || el.title || el.name || '';
  };

  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el)) continue;
    const ref = 'e' + (++i);
    el.setAttribute('data-agent-ref', ref);
    const r = el.getBoundingClientRect();
    out.push({
      ref,
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      type: el.type || null,
      name: nameOf(el).replace(/\s+/g, ' ').trim().slice(0, 90),
      value: ['input', 'textarea', 'select'].includes(el.tagName.toLowerCase()) && !['password', 'checkbox', 'radio'].includes(el.type)
             ? (el.value || '').slice(0, 60) : null,
      checked: el.checked ?? (el.getAttribute('aria-checked') ?? null),
      required: el.required || el.getAttribute('aria-required') === 'true',
      disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
      in_viewport: r.top < innerHeight && r.bottom > 0,
      box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    });
  }
  return out;
}
"""


def _find_chrome() -> str | None:
    """Windows Chrome (start_chrome.bat) is the DEFAULT browser.
    - CDP_URL=...      use that address
    - BROWSER=chromium use Playwright's own Linux Chromium instead (Google login blocked there)
    - otherwise        auto-detect Chrome on localhost:9222, and stop with a clear message if absent
    """
    import urllib.request
    if os.environ.get("BROWSER", "").lower() == "chromium":
        return None
    url = os.environ.get("CDP_URL", "http://localhost:9222")
    try:
        urllib.request.urlopen(url + "/json/version", timeout=2)
        return url
    except Exception:
        sys.exit(f"\nWindows Chrome not reachable at {url}.\n"
                 "  1. Double-click start_chrome.bat (in the project folder, from Windows)\n"
                 "  2. Check from WSL: curl -s localhost:9222/json/version\n"
                 "  3. If curl fails: .wslconfig needs networkingMode=mirrored, then 'wsl --shutdown'\n"
                 "  (or run with BROWSER=chromium to use the Linux browser instead)")


CDP_URL = _find_chrome()                 # attach to Windows Chrome over CDP


class Session:
    """Two ways to get a browser:
    - CDP_URL set: ATTACH to a Chrome you started yourself (start_chrome.bat).
      Chrome is not launched by Playwright, so Google login works normally.
      Closing the script only disconnects; your Chrome window stays open.
    - otherwise: Playwright LAUNCHES its own Chromium with a persistent profile.
      Google sign-in is blocked there ("browser may not be secure").
    """

    def __init__(self, p):
        if CDP_URL:
            import urllib.request
            try:
                targets = json.load(urllib.request.urlopen(CDP_URL + "/json/list", timeout=3))
                pages = [t for t in targets if t.get("type") == "page"]
                print(f"Chrome has {len(pages)} tab(s) open")
            except Exception:
                pages = []
            try:
                # Playwright attaches to EVERY open tab: a frozen/discarded tab can hang this forever
                self.browser = p.chromium.connect_over_cdp(CDP_URL, timeout=30_000)
            except Exception as e:
                sys.exit(f"\nConnected to Chrome but it did not answer in 30 s ({type(e).__name__}).\n"
                         f"  Usual cause: old/sleeping tabs ({len(pages)} open). Fix:\n"
                         "  1. Close ALL windows of the agent Chrome (the one from start_chrome.bat)\n"
                         "  2. Double-click start_chrome.bat again (1 fresh tab)\n"
                         "  3. Re-run the command")
            self.ctx = self.browser.contexts[0]          # the default Chrome profile window
            print(f"Attached to Chrome at {CDP_URL}")
        else:
            PROFILE_DIR.mkdir(exist_ok=True)
            self.browser = None
            self.ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                locale="fr-FR",
                viewport={"width": 1400, "height": 900},
            )

    def page(self) -> Page:
        return self.ctx.pages[-1] if self.ctx.pages else self.ctx.new_page()

    def active_page(self) -> Page:
        """The tab YOU are looking at: the visible one (prefer the one with focus).
        Over CDP, ctx.pages order is not reliable, so we ask each tab."""
        best, best_score = None, -1
        for pg in self.ctx.pages:
            if pg.url.startswith(("chrome://", "devtools://", "chrome-extension://")):
                continue
            try:
                vis, focus = pg.evaluate("[document.visibilityState, document.hasFocus()]")
            except Exception:
                continue
            score = (vis == "visible") * 2 + bool(focus)
            if score >= best_score:          # ties -> later tab wins
                best, best_score = pg, score
        return best or self.page()

    def close(self):
        if self.browser:      # CDP: just disconnect, leave your Chrome running
            self.browser.close()
        else:
            self.ctx.close()


def scan(page: Page, step: int) -> list[dict]:
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)  # let JS-heavy pages settle

    elements = page.evaluate(SCAN_JS)

    # Save everything for this step
    run = RUNS_DIR / datetime.now().strftime("%Y%m%d")
    run.mkdir(parents=True, exist_ok=True)
    stem = run / f"step{step:02d}"
    page.screenshot(path=f"{stem}.png")
    (stem.with_suffix(".json")).write_text(
        json.dumps({"url": page.url, "title": page.title(), "elements": elements},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    # Playwright's own accessibility (ARIA) tree, as YAML: another view the LLM could get
    (Path(f"{stem}.aria.yaml")).write_text(page.locator("body").aria_snapshot(), encoding="utf-8")

    # Print a compact table: this is roughly what the LLM will receive
    print(f"\n=== STEP {step} | {page.title()[:70]}")
    print(f"    {page.url[:110]}")
    print(f"    {len(elements)} interactive elements  (* = required, ! = disabled, ~ = off-screen)\n")
    for e in elements:
        flags = ("*" if e["required"] else " ") + ("!" if e["disabled"] else " ") \
                + (" " if e["in_viewport"] else "~")
        extra = ""
        if e["value"]:
            extra += f'  value="{e["value"]}"'
        if e["checked"] not in (None, False, "false"):
            extra += f"  checked={e['checked']}"
        kind = e["role"] + (f":{e['type']}" if e["type"] and e["role"] == "input" else "")
        print(f"  [{e['ref']:>4}] {flags} {kind:<16} {e['name'][:70]}{extra}")
    print(f"\n  saved -> {stem}.png / .json / .aria.yaml")
    return elements


def cmd_login():
    with sync_playwright() as p:
        s = Session(p)
        s.page().goto("https://secure.indeed.com/auth?hl=fr_FR&co=FR")
        input("\nLog in to Indeed in the browser window, then press Enter here...")
        s.close()
        print("Session saved (in the Chrome profile)." if CDP_URL else f"Session saved in {PROFILE_DIR.resolve()}")


def cmd_inspect(url: str):
    with sync_playwright() as p:
        s = Session(p)
        page = s.ctx.new_page() if CDP_URL else s.page()   # CDP: own tab, don't hijack yours
        # Indeed Apply opens in a NEW TAB: always follow the most recent tab
        s.ctx.on("page", lambda new: print(f"\n  (new tab opened: {new.url[:80]})"))
        page.goto(url)

        step = 1
        while True:
            page = s.active_page()          # follow you, never steal focus
            tabs = [pg for pg in s.ctx.pages if pg.url.startswith("http")]
            print(f"\n  {len(tabs)} tab(s) open, scanning the active one")
            scan(page, step)
            cmd = input("\n[Enter] rescan after you click in the browser   [q] quit > ").strip().lower()
            if cmd == "q":
                break
            step += 1
        s.close()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "login":
        cmd_login()
    elif len(sys.argv) >= 3 and sys.argv[1] == "inspect":
        cmd_inspect(sys.argv[2])
    else:
        print(__doc__)
