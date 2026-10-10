"""
AUTOPILOT: the repeated Easy Apply steps without the LLM.
Same 4-step LinkedIn-like form on 2 offers (contact, CV, questions, review/send):
  offer 1: the autopilot does everything it knows; ONE new question (hybrid work) goes to the LLM; its answer
           is learned into profile "form_answers"
  offer 2: the autopilot does EVERYTHING, the LLM is never called; sent once, "Suivre <company>" unticked
"""
import json
import re
from common import CALLS, CONFIG, LINKEDIN, ROOT, Human, fresh
from playwright.sync_api import sync_playwright
from core import answers
from core.browser import Session
from nodes.apply import apply

PROFILE = {"identity": {"first_name": "Adil", "last_name": "AMZAZ", "email": "adil@example.com",
                        "phone": "+33 6 12 34 56 78", "phone_national": "06 12 34 56 78", "city": "Paris"},
           "years_experience": {"python": "2", "ai_ml": "2", "java_spring": 5, "software_engineering_total": 5},
           "languages": {"English": "fluent"}, "notice_period": "Disponible immédiatement"}
answers.PATH.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")


def run(job_id, company):
    fresh(f"auto-{job_id}", auto_apply={"enabled": True, "submit": True, "approve_legal": True})
    CONFIG["apply"]["autopilot"] = True
    url = f"{LINKEDIN}/jobs/view/{job_id}/"
    CALLS.update(apply=0)
    with sync_playwright() as p:
        s = Session(p)
        page = s.new_tab(url)
        res = apply(page, url, "auto", None, ROOT / "runs" / "tests" / f"auto-{job_id}", title="AI Engineer", company=company)
        sent, follow = page.evaluate("() => [window.sent, window.follow]")
        s.close()
    print(company, res["status"], "| LLM calls:", CALLS["apply"], "|", res["summary"][:160])
    return res, CALLS["apply"], sent, follow


res1, llm1, sent1, follow1 = run(3900000007, "ACME")
assert res1["status"] == "submitted" and sent1 == 1 and follow1 is False, (res1, sent1, follow1)
assert llm1 <= 2, llm1                                         # only the new question needed the LLM
learned = json.loads(answers.PATH.read_text(encoding="utf-8")).get("form_answers", {})
assert learned.get("Êtes-vous à l'aise avec le travail hybride ?") == "Oui", learned
log = (ROOT / "runs" / "tests" / "auto-3900000007" / "actions.jsonl").read_text(encoding="utf-8")
assert '"auto": true' in log and '"text": "2"' in log and "06 12 34 56 78" in log      # years + phone by autopilot

res2, llm2, sent2, follow2 = run(3900000008, "Delta")
assert res2["status"] == "submitted" and sent2 == 1 and follow2 is False, (res2, sent2, follow2)
assert llm2 == 0, llm2                                          # the whole application without the LLM

# the incident: LinkedIn showed a SEARCH page; job cards contain "Candidature simplifiée" -> nothing is started
from core import policy
from core.tools import BrowserTools
from common import Human
offer = "https://www.linkedin.com/jobs/view/4404326409/"
ctx = {"board_host": "www.linkedin.com", "offer_key": ["linkedin", "4404326409"], "external": True}
card = {"name": "AI Engineer Confirmé H/F SEVEN MILE Paris (Hybride) Promu(e) Candidature simplifiée", "type": None}
button = {"name": "Candidature simplifiée pour ce poste", "type": None}
assert policy.check("click", card, offer, ctx)[0] == policy.FORBIDDEN                     # a card, not the button
assert policy.check("click", button, offer, ctx)[0] == policy.ALLOW
other = "https://www.linkedin.com/jobs/view/4465784223/"
assert policy.check("click", button, other, ctx)[0] == policy.FORBIDDEN                     # another offer
same = "https://www.linkedin.com/jobs/search-results/?currentJobId=4404326409&keywords=ai"
assert policy.check("click", button, same, ctx)[0] == policy.ALLOW                         # same offer, search layout
SEARCH = """<h1>Résultats</h1><ul>
 <li class="job-card-container" data-job-id="1"><a href="/jobs/view/111/">AI Engineer Confirmé H/F SEVEN MILE Paris
   Promu(e) Candidature simplifiée</a></li>
 <li class="job-card-container" data-job-id="2"><a href="/jobs/view/222/">AI Engineer eXalt Value Candidature simplifiée</a></li></ul>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(SEARCH)
    (ROOT / "runs" / "tests" / "auto-search").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "auto-search", Human([]),
                     {"board_host": "127.0.0.1:8772", "offer_key": ["127.0.0.1:8772", LINKEDIN + "/jobs/view/3900000007/"]})
    assert t.autopilot(PROFILE) == [], "the autopilot clicked something on a search page"
    s.close()


# Workday "Établissement ou université": a SEARCH field (typing alone leaves it empty): type, Enter, pick, verify
WD = """<label id="l1">Établissement ou université*</label>
<div data-automation-id="multiselectInputContainer"><div id="pill"></div>
  <input data-automation-id="searchBox" aria-labelledby="l1" id="sb" required></div>
<div id="list" role="listbox"></div><button>Suivant</button>
<script>
 const schools = ["Université de Lille", "Université de Limoges", "Université Paris-Saclay", "Autre"];
 const sb = document.getElementById('sb');
 sb.addEventListener('keydown', e => { if (e.key !== 'Enter') return;
   const q = sb.value.toLowerCase();
   document.getElementById('list').innerHTML = schools.filter(s => s.toLowerCase().includes(q) || s === 'Autre')
     .map(s => `<div role="option" data-automation-id="promptOption">${s}</div>`).join('');
   document.querySelectorAll('[data-automation-id=promptOption]').forEach(o => o.onclick = () => {
     document.getElementById('pill').innerHTML = `<div data-automation-id="selectedItem">${o.innerText}</div>`;
     sb.value = ''; sb.required = false; document.getElementById('list').innerHTML = ''; window.school = o.innerText; });
 });
</script>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(WD)
    (ROOT / "runs" / "tests" / "wd").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "wd", Human([]), {"board_host": "x"})
    state = t.read_page()
    ref = re.search(r"\[(e\d+)\] search-field\(use search_select\) \"Établissement", state).group(1)
    out = t.search_select(ref, "Université de Limoges", "Université de Limoges")   # full name: no hit -> "Limoges"
    assert out.startswith('selected "Université de Limoges" (verified: True)'), out[:200]
    assert page.evaluate("() => window.school") == "Université de Limoges"
    assert t.llm_fills[-1] == ("Établissement ou université*", "Université de Limoges")
    # next form: the autopilot does it alone from the learned answer
    page.goto(LINKEDIN + "/jobs/view/3900000008/")              # a fresh page (new window)
    page.set_content(WD)
    t2 = BrowserTools(page, ROOT / "runs" / "tests" / "wd", Human([]), {"board_host": "x"})
    did = t2.autopilot({**PROFILE, "form_answers": {"Établissement ou université": "Université de Limoges"}})
    assert page.evaluate("() => window.school") == "Université de Limoges", did
    assert any("(searched)" in d for d in did), did
    s.close()


# Air Liquide (Workday): a label must point to ONE element. The language selector was labelled "e6" in an earlier
# scan, then hidden: "e6" pointed to it AND to the consent dropdown -> the click went to the hidden one (crash).
STALE = """<button id="lang" aria-haspopup="listbox">Français</button>
<div id="q" style="display:none"><label id="c">Consentement vivier*</label>
  <button id="consent" aria-haspopup="listbox" aria-labelledby="c">Sélectionnez une valeur</button></div>
<button>Suivant</button>"""
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(LINKEDIN + "/jobs/view/3900000007/")
    page.set_content(STALE)
    (ROOT / "runs" / "tests" / "stale").mkdir(parents=True, exist_ok=True)
    t = BrowserTools(page, ROOT / "runs" / "tests" / "stale", Human([]), {"board_host": "x"})
    t.read_page()
    page.evaluate("() => { document.getElementById('lang').style.display = 'none'; document.getElementById('q').style.display = 'block'; }")
    state = t.read_page()
    for ref in re.findall(r"\[(e\d+)\]", state):
        assert page.locator(f'[data-agent-ref="{ref}"]').count() == 1, (ref, state)        # one element per label
    consent = re.search(r"\[(e\d+)\] dropdown\(use select_option\) \"Consentement", state).group(1)
    assert page.locator(f'[data-agent-ref="{consent}"]').get_attribute("id") == "consent"
    # a click the autopilot cannot do (hidden element) returns None instead of crashing the scan
    hidden = {"ref": "zz"}
    page.evaluate("() => document.getElementById('lang').setAttribute('data-agent-ref', 'zz')")
    t.elements["zz"] = {"ref": "zz", "name": "Suivant", "role": "button", "type": None}
    assert t._auto_click(hidden, [], "auto_next") is None
    s.close()

print(f"\nLLM calls: offer 1 = {llm1}, offer 2 = {llm2}")
print("\nALL AUTOPILOT CHECKS PASSED")
