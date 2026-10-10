# Job application agent

| file | role |
|---|---|
| `explore.py` | step 1: browser session (CDP or Playwright) + page scanner |
| `tools.py` | step 2: the actions the LLM can call (read, click, type, select, set_checked) |
| `policy.py` | step 2: hard guardrails checked before every action |
| `agent.py` | step 2: the LLM tool-calling loop (any model through LiteLLM) |
| `profile.json` | what the agent may answer from: **fill the TO FILL values** |
| `tests/` | offline test with a fake site and a fake LLM |

# Step 1: see the page like an agent

No LLM yet, and the script never clicks. You navigate yourself and it shows you
the element list an LLM would receive at each step.

## Setup (WSL2 Ubuntu)

Project folder: `C:\Users\aamzaz\Documents\applying_jobs_agent`
(in WSL: `~/applying_jobs_agent`, a link to `/mnt/c/Users/aamzaz/Documents/applying_jobs_agent`).

```bash
ln -s /mnt/c/Users/aamzaz/Documents/applying_jobs_agent ~/applying_jobs_agent   # once
cd ~/applying_jobs_agent
python3 -m venv ~/.venvs/jobagent && source ~/.venvs/jobagent/bin/activate     # venv on the Linux disk (faster)
pip install playwright
playwright install --with-deps chromium  # browser + Linux libraries
```

WSL2 on Windows 11 shows the browser window through WSLg automatically.
Check with `echo $DISPLAY` (it should print something like `:0`).

## Run

```bash
python explore.py login      # 1st time only: log in to Indeed by hand in the window
python explore.py inspect "https://fr.indeed.com/jobs?q=AI+engineer&l=France&sc=0kf%3Aattr%28DSQF7%29%3B"
```

Then, in the browser window: click an offer → "Postuler maintenant" → go through
the steps. **After each click, press Enter in the terminal** to rescan.
Close the tab before the final "Déposer ma candidature" if you only want to explore.

Each step is saved in `runs/<date>/`:

| file | content |
|---|---|
| `stepNN.png` | screenshot |
| `stepNN.json` | your element list (ref, role, name, value, checked, required, box) |
| `stepNN.aria.yaml` | Playwright's ARIA tree (the other format you can give an LLM) |

## Things to notice (this prepares step 2)

1. Compare `.json` and `.aria.yaml`: which one is shorter and clearer for an LLM?
2. Count the elements per step: the job page has hundreds, the apply form has few.
   You will need to filter before sending to the LLM.
3. Find the alert switch on the review page and check how `checked` is reported.
4. The `ref` (e12) is written into the page as `data-agent-ref="e12"`, so step 2
   can do `page.click('[data-agent-ref="e12"]')`. That is the agent's `click` tool.

## Use your Windows Chrome (Google login, fewer blocks)

Playwright's Chromium is flagged as "controlled by automation", so Google refuses
sign-in there ("this browser may not be secure"). Fix: start real Chrome yourself,
then let the script ATTACH to it over CDP (Chrome DevTools Protocol).

1. **Once:** let WSL reach Windows `localhost`. Create `C:\Users\aamzaz\.wslconfig`:
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
   then in PowerShell: `wsl --shutdown`, and reopen Ubuntu.
2. **Double-click `start_chrome.bat`** (in this folder, from Windows Explorer).
   A Chrome window opens with its own profile. First time: log in to Google/Indeed by hand.
3. Check from WSL: `curl -s localhost:9222/json/version` should print Chrome's version.
4. Run:
   ```bash
   python explore.py inspect "https://fr.indeed.com/jobs?q=AI+engineer&l=France&sc=0kf%3Aattr%28DSQF7%29%3B"
   ```
   The script opens its own tab. Pressing `q` only disconnects: Chrome stays open.

## If Indeed blocks you (captcha / "verify you are human")

- Solve it by hand in the window. The profile keeps the result.
- Or switch to your Windows Chrome (section above).
- Don't run it in a loop or headless against Indeed.

Tip: if the browser profile is slow on `/mnt/c`, move it to the Linux disk by changing
`PROFILE_DIR` in `explore.py` to `Path.home() / ".jobagent-profile"`.

`browser-profile/` contains your logged-in session: never commit it to git
(add it to `.gitignore` together with `runs/`).


# Step 2: the agent

```bash
pip install -r requirements.txt
python tests/test_fake_llm.py          # offline check, no API key, should print ALL CHECKS PASSED
```

Then with a real model (Chrome started with `start_chrome.bat`, logged in to Indeed):

```bash
export OPENAI_API_KEY=...              # default model: openai/gpt-6-luna
# (free alternative for tests: export GEMINI_API_KEY=... and MODEL=gemini/gemini-3.8-flash)
python agent.py "https://fr.indeed.com/viewjob?jk=<job id>"
# Gemini free tier waits 6 s between calls (MIN_SECONDS_BETWEEN_CALLS)
# Claude later: export ANTHROPIC_API_KEY=... and MODEL=anthropic/claude-sonnet-4-5
```

Change the model with `MODEL=` only (LiteLLM names: `openai/...`, `gemini/...`, `ollama/...`).

What happens:

1. The agent reads the page, clicks "Postuler maintenant", answers questions from `profile.json`.
2. Missing info or a legal checkbox: it **asks you in the terminal**.
3. Pre-checked alerts: turned off. Final "Déposer ma candidature": **blocked by policy.py**.
4. On the review page it calls `finish()` and prints a summary. You check the tab and submit yourself.

Every run is logged in `runs/agent-<date>/`: one screenshot per page state + `actions.jsonl`
(each action, the policy verdict, the state before/after, tokens used).

Limits:

- `MAX_STEPS` (default 25) and loop detection (same call 3 times) stop a lost agent.
- Only the latest page state is sent in full to the LLM (older ones are shortened) to limit cost.
- No CV upload: the agent uses the CV already selected on Indeed.
- Use it on a few offers at a time, by hand. Indeed's terms forbid automating Indeed Apply.

# Step 3: applications database (`jobs.db`, SQLite)

Each run first **reads the offer** (one extra LLM call) and saves it, then applies.

| table / view | content |
|---|---|
| `applications` | one row per offer: title, company, location, contract, remote, salary, experience, skills, summary, full description, **contact name / email / phone**, status, **applied_at**, agent summary, model, tokens, run folder |
| `relances` | one row per follow-up: date, channel (email/phone/linkedin), note |
| `applications_overview` | one line per application with `relance_count` and `last_relance_at` |

- Contacts: the LLM extracts them, and a regex double-checks the text so a written email/phone is never missed.
- The same offer is recognised from any link (Indeed `jk`/`vjk`): already applied -> the agent refuses (`FORCE=1` to override).
- After a run reaching the review page, the agent asks if you clicked "Déposer": `y` -> status `applied` + today's date.

```bash
python jobs.py list                         # everything
python jobs.py show 3                       # one application, full details + relances
python jobs.py applied 3                    # you sent it later
python jobs.py relance 3 email "relance après 1 semaine"
python jobs.py status 3 interview           # interview / rejected / offer / no_answer
python jobs.py due                          # applied 7+ days ago, no relance since: follow up!
python jobs.py export                       # applications.csv (opens in Excel, ; separator)
```

# Step 4: hunt = SEARCH graph + APPLY node (`hunt.py`, LangGraph)

```bash
pip install -r requirements.txt       # adds langgraph
python hunt.py                        # asks: job, location, MANDATORY keywords, EXCLUDED keywords, easy apply only, max pages
python hunt.py --last                 # same criteria as last time (criteria.json)
```

Loop: results page -> next offer opened in a **new tab** (the results tab stays where it is) ->
mandatory/excluded keywords checked on the full description (no LLM, accent/case insensitive, whole words) ->
offer extracted (LLM) and shown -> **you answer a / s / q** -> `a` runs the apply node -> next offer -> next page.

- The search part never clicks: pages are opened by URL (`start=10, 20...`), so no alert / save / "not interested" can be triggered.
- Keywords: **at least one of** (`any_of`), **all of** (`mandatory`, `a|b` = a or b inside one keyword), **none of** (`excluded`).
  Matching ignores case/accents/plurals and word order, and knows FR/EN equivalents:
  `ai agent` matches "agents IA", "AI agents", "agentic AI"; `ia` = `ai`; `rag`, `llm`, `ml`, `genai`, `nlp` have their long forms.
- Every offer seen is stored. A new hunt **never re-shows `applied`** (and interview/rejected/offer/no_answer),
  **re-shows `skipped`/`external_apply` only with `--recheck`**, and **re-checks `filtered` ones with the new keywords**.
- `python jobs.py reset <id|status>` makes offers visible again (e.g. `reset skipped`).
- `agent.py <url>` still works alone for one offer (it uses the same `apply_offer` node).
- Offline test of the whole loop: `python tests/test_hunt.py`
