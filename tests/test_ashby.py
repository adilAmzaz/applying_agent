"""
Ashby (Resilience Care): Yes / No answered with BUTTONS and language levels with radios, each question in a
<label> title. The agent saw 3 identical "No" buttons and "C1"/"C2" without their question and kept switching
answers. Now every choice carries its question, and the buttons show which one is selected.
"""
import re
from common import LINKEDIN, ROOT, Human
from playwright.sync_api import sync_playwright
from core.browser import Session
from core.tools import BrowserTools

PAGE = """<form>
<div class="field"><label class="title">Email</label><input type="email" id="em"></div>
<div class="field"><label class="title">English level</label>
  <div><label><input type="radio" name="en" value="c1"> C1 : Flexible, effective</label>
       <label><input type="radio" name="en" value="c2"> C2 : Near native</label></div></div>
<div class="field"><label class="title">French level</label>
  <div><label><input type="radio" name="fr" value="c1"> C1 : Flexible, effective</label>
       <label><input type="radio" name="fr" value="c2"> C2 : Near native</label></div></div>
<div class="field"><label class="title">Do you need a visa sponsorship?</label>
  <div class="yesno"><button type="button" class="opt">Yes</button><button type="button" class="opt">No</button></div></div>
<div class="field"><label class="title">Are you available to start within 3 months?</label>
  <div class="yesno"><button type="button" class="opt">Yes</button><button type="button" class="opt">No</button></div></div>
<div class="field"><label class="title">Notice period</label><select><option></option><option>None</option><option>1 month</option></select></div>
<button type="submit">Submit Application</button></form>
<script>document.querySelectorAll('.yesno').forEach(g => g.querySelectorAll('button').forEach(b => b.onclick = () => {
  g.querySelectorAll('button').forEach(x => x.classList.remove('_active_x')); b.classList.add('_active_x'); }));</script>"""

with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(PAGE)
    (ROOT / "runs" / "tests" / "ashby").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "ashby", Human([]), {"board_host": "x"})
    state = t.read_page()
    print(state)
    assert re.search(r'radio "C1 : Flexible, effective \[question: English level\]"', state), state
    assert re.search(r'radio "C2 : Near native \[question: French level\]"', state), state
    assert re.search(r'button "No \[question: Do you need a visa sponsorship\?\]" checked=false', state), state
    no2 = re.search(r'\[(e\d+)\] button "No \[question: Are you available', state)
    yes2 = re.search(r'\[(e\d+)\] button "Yes \[question: Are you available', state).group(1)
    assert no2, state
    assert re.search(r'select "Notice period"', state), state                    # unlabelled select: its question
    t.click(yes2)
    state = t.read_page()
    assert re.search(r'button "Yes \[question: Are you available[^"]*" checked=true', state), state
    assert re.search(r'button "Yes \[question: Do you need[^"]*" checked=false', state), state
    assert re.search(r'button "Submit Application"\s', state + "\n"), state           # buttons keep their name
    s.close()
print("\nALL ASHBY CHECKS PASSED")
