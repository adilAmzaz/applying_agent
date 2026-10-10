# Job application agent

Finds offers, has an LLM **judge** them against what you are looking for, lets you review them
when you have time, and applies (on the job board or on the company site). Can run alone on a schedule.

## First install (after `git clone`)

Your personal files are NOT in the repository (see `.gitignore`): create them from the templates.

```bash
python3 -m venv ~/.venvs/jobagent && source ~/.venvs/jobagent/bin/activate
pip install -r requirements.txt && playwright install chromium   # only if you do not use your own Chrome
cp config.example.toml config.toml           # settings (mailbox, sources, auto-apply...)
cp profile.example.json profile.json         # your identity and answers for the forms
cp judge/profile.example.md judge/profile.md # what you are looking for (read by the judge)
cp judge/examples.example.md judge/examples.md
cp .env.example .env                         # API keys, Gmail app password, account password, Telegram
mkdir -p cv                                  # put your CV there and set [apply] cv_path in config.toml
python tests/run_all.py                      # offline tests: no API key needed
```

## Start: open WSL and activate the environment

Every time, in a new Ubuntu (WSL) terminal:

```bash
cd ~/applying_jobs_agent
source ~/.venvs/jobagent/bin/activate     # the prompt now starts with (jobagent)
python scan.py linkedin                   # or: python scan.py (all agents), python review.py ...
deactivate                                # when you are done (optional)
```

Shortcut (once): add this line to `~/.bashrc`, then just type `jobagent` in a new terminal:

```bash
alias jobagent='cd ~/applying_jobs_agent && source ~/.venvs/jobagent/bin/activate'
```

First install only (new PC):

```bash
ln -s /mnt/c/Users/aamzaz/Documents/applying_jobs_agent ~/applying_jobs_agent
python3 -m venv ~/.venvs/jobagent && source ~/.venvs/jobagent/bin/activate   # venv on the Linux disk (faster)
pip install -r ~/applying_jobs_agent/requirements.txt
playwright install --with-deps chromium
```

Without activating, `~/.venvs/jobagent/bin/python scan.py` works too (that is what `scan_task.bat` does).

## Models and API keys (`[llm]` in config.toml, keys in `.env`)

```toml
model            = "openai/gpt-6-luna"           # apply agent + judge (judge_model = "" -> same)
fallback_model_1 = "anthropic/claude-haiku-4-5"  # when the model keeps failing: 2 tries each, then the next
fallback_model_2 = "gemini/gemini-3.8-flash"     # "" = no fallback
```

- **Every key goes in `.env`** (never in config.toml): `OPENAI_API_KEY=...`, `ANTHROPIC_API_KEY=...`,
  `GEMINI_API_KEY=...`, `MISTRAL_API_KEY=...`. The provider is the start of the model name
  (`openai/...` -> `OPENAI_API_KEY`). A key in `.env` wins over the same variable in `~/.bashrc`.
- A model whose key is missing (or wrong, or removed by the provider) is skipped at once: next model.
- All models down: no LLM call for 5 min; the offers stay `new` and are judged at the next scan
  (an outage never uses up their 3 judge attempts).

## Architecture: small nodes, one job each

```
scan.py  (scheduled, never asks anything)                       review.py  (you, when you have time)
─────────────────────────────────────────                       ──────────────────────────────────
 sources/indeed ─► dedupe ─► read ─► prefilter ─► judge ─► store ─┐         pending high/maybe, best score first
   (results by URL) (text,   (free        (1 LLM   (DB)  │            │  a = apply (interactive)
                     apply    keywords)    call)         │            │  s = skip   l = later  o = open
                     kind)                               ▼            │  disagree with the judge?
                                          auto_gate ─► apply (auto)   │   -> save it as an example
                                              │                       ▼
                                              └──────► notify (report)      apply node (shared)
```

| folder / file | what it does | change it when... |
|---|---|---|
| `config.toml` | **every setting**: model, search, prefilter, judge files, auto-apply switches | always start here |
| `judge/profile.md` | **what you are looking for** (the judge's big prompt) | your search changes |
| `judge/examples.md` | offers you labelled high / maybe / low | the judge is wrong (see below) |
| `nodes/sources/indeed.py`, `linkedin.py`, `wttj.py`, `hellowork.py` | search URLs + reading a results page | the site changes / add `hellowork.py` with the same names |
| `nodes/sources/*_email.py`, `board_email.py`, `mail.py` | job-alert emails -> offers (IMAP, read-only) | the email format changes |
| `nodes/reset.py` | forget offers (by id, status, scan, all) + automatic backup | |
| `nodes/dedupe.py` | already seen? (platform id / link + title) and already applied? | duplicate rules, or `[dedupe] enabled = false` |
| `nodes/read.py` | offer page -> text, apply kind (easy / external) | offer pages change |
| `nodes/prefilter.py` | free keyword filter before the LLM | |
| `nodes/judge.py` | **1 LLM call per new offer** -> verdict, score, reasons + offer fields | judging rules |
| `nodes/apply.py` | the agent that fills one application (board or company site) | apply behaviour |
| `nodes/store.py` | every database write | new columns |
| `nodes/notify.py` | report of each scan (`reports/`) | add Telegram / email |
| `nodes/examples.py` | your decisions -> judge examples | |
| `graphs/scan.py`, `graphs/review.py` | wiring of the nodes (LangGraph / loop) | change the order of steps |
| `core/policy.py` | guardrails checked before every browser action | what the agent may click |
| `core/tools.py` | browser actions of the apply agent | |
| `core/llm.py`, `core/browser.py`, `core/db.py`, `core/keywords.py` | shared plumbing | rarely |

## Agents: one per site, one Chrome each, all at the same time

| agent | Chrome (port, profile) | log in by hand there | sources |
|---|---|---|---|
| `indeed` | 9222, `%USERPROFILE%\.jobagent-chrome` | Indeed | `indeed`, `indeed_email` |
| `linkedin` | 9223, `.jobagent-chrome-linkedin` | LinkedIn | `linkedin`, `linkedin_email` |
| `wttj` | 9224, `.jobagent-chrome-wttj` | Welcome to the Jungle | `wttj`, `wttj_email` |
| `hellowork` | 9225, `.jobagent-chrome-hellowork` | HelloWork | `hellowork`, `hellowork_email` |
| `freework` | 9226, `.jobagent-chrome-freework` | Free-Work (CDI + freelance) | `freework`, `freework_email` |

```bat
start_all_chromes.bat          :: from Windows: the 4 Chromes (those already open are left alone)
start_chrome.bat linkedin      :: just one
```
```bash
python scan.py                 # all agents AT THE SAME TIME -> runs/scan-<agent>.log, reports/scan-...-<agent>.md
python scan.py linkedin        # one agent
python scan.py indeed wttj     # some of them
```
- Each Chrome has its own profile: its own logins, separate from your personal Chrome and from the others.
  First time: log in by hand in each window. An agent never touches another agent's tabs.
- One database for all (writes wait for each other). The same agent never runs twice at once (lock file).
- `review.py` / `apply_one.py` open each offer in the Chrome of its site (a LinkedIn offer in the LinkedIn Chrome).
- Turn a source off in `[search] sources`; an agent with no source left does nothing.
- 4 Chromes ~ 1-2 GB of RAM in total.

## Sources: browser + email, for Indeed, LinkedIn, Welcome to the Jungle and HelloWork

```toml
[search]
sources = ["indeed", "linkedin", "wttj", "hellowork",
           "indeed_email", "linkedin_email", "wttj_email", "hellowork_email"]
```

| source | where the offers come from | file |
|---|---|---|
| `indeed` | Indeed search pages, in the agent Chrome | `nodes/sources/indeed.py` |
| `linkedin` | LinkedIn search pages, in the agent Chrome (you logged in by hand) | `nodes/sources/linkedin.py` |
| `indeed_email` | your Indeed job-alert emails | `nodes/sources/indeed_email.py` |
| `linkedin_email` | your LinkedIn job-alert emails | `nodes/sources/linkedin_email.py` |
| `wttj` | Welcome to the Jungle search pages (public), in the agent Chrome | `nodes/sources/wttj.py` |
| `wttj_email` | your Welcome to the Jungle alert emails (create one on a WTTJ search: "Créer une alerte") | `nodes/sources/wttj_email.py` |
| `hellowork` | HelloWork search pages (public), in the agent Chrome | `nodes/sources/hellowork.py` |
| `hellowork_email` | your HelloWork alert emails | `nodes/sources/hellowork_email.py` |

All of them feed the same chain (dedupe -> read the offer page -> prefilter -> judge -> review).
The id of an offer is the same in the email and on the site (Indeed `jk`, LinkedIn `/jobs/view/<id>`,
WTTJ `<company>/<job-slug>` from `/companies/<company>/jobs/<job-slug>`, HelloWork `/emplois/<id>.html`):
an offer found by the browser AND in an email is opened and judged **once**.

**LinkedIn in the browser** — LinkedIn is stricter than Indeed with automation (your account, your decision):
`[linkedin]` keeps it slow (`pause_seconds = 6`, `max_pages = 1` per query). Watch the first runs.
If LinkedIn shows a login page or a security check, the LinkedIn searches **stop for this scan** (the other
sources go on) and the report starts with *Stopped this time: linkedin*: log in by hand in the agent Chrome.
Easy Apply (the modal) is filled like Indeed's form: "Suivre <company>" is unticked, "Enregistrer" / "Suivre" /
messages are never clicked, the final "Envoyer la candidature" only with `[auto_apply] submit = true`.
Offers you already applied to on LinkedIn ("Candidature envoyée" on the card) are skipped.

**Welcome to the Jungle** — public search, no login needed to find offers. Applying with WTTJ's own form
needs your WTTJ account: log in by hand once in the agent Chrome (otherwise the agent stops at the login,
`needs_human`). Some offers send you to the company site: handled like Indeed's external offers.
**HelloWork** — same as WTTJ: public search; its own application form (drawn in the offer page) needs your
HelloWork account, logged in by hand once; "Postuler sur le site du recruteur" = company site.

The WTTJ and HelloWork alert email formats were not seen yet, so `wttj_email` / `hellowork_email` use one
generic reader (`nodes/sources/board_email.py`): it takes the offer links, and a tracking link is opened only
when an offer (title + company) is written just before it — never a "se désabonner" / settings link.

**Email** — the mailbox in `[email]` is read **read-only** over IMAP (nothing marked read, moved or deleted);
each email is parsed once (`mail_seen` table). Setup, once:
1. Google account of `[email] address` -> Security -> 2-step verification on -> **App passwords** -> create one.
2. Copy `.env.example` to `.env` and put it in `JOBAGENT_MAIL_PASSWORD=`. (`.env` stays on your PC, never in git.)
3. Create the alerts on the sites (one per wording) with that address, or forward them to it.
Without the password the email sources are skipped and the report says so.

### Free-Work (`nodes/sources/freework.py`)
IT jobs **and freelance missions**. Search `free-work.com/fr/tech-it/jobs?query=...`, offers `/job-mission/<category>/<slug>`.
First time: `start_chrome.bat freework`, then **log in to your Free-Work account by hand** in that window
(its "Postuler" form needs it). Filters in `[freework]`: `contracts = ["permanent"]` (CDI) / `["contractor"]`
(freelance), `locations = "fr~~~"`. Run alone: `python scan.py freework`.

## Several searches per scan

Indeed returns different offers for "AI engineer" and "ingénieur IA" (it matches the words, not the meaning).
List every wording in `config.toml`:

```toml
[search]
queries = ["AI engineer", "ingénieur IA", "LLM engineer"]
```
Each query is searched (`max_pages` pages each). An offer found by two queries has the same Indeed id:
it is opened and judged **once** (the second time it is skipped for free, counted as `already_seen_this_run`).
More queries = more results pages to load, but no extra LLM calls for duplicates.

## Token economy

- The judge is **one call per offer, only for offers never judged before** (a second scan re-judges nothing).
- `[prefilter]` removes obvious no-gos (internships, Power BI...) **before** the LLM, for free.
- The judge prompt (rules + profile + examples) is identical for every call: providers cache it
  (automatic on OpenAI, marked for Anthropic). Keep examples short (~10-20).
- The offer is cut at `max_offer_chars`. The judge also extracts company, salary, contacts: no second call.
- The apply agent runs only on offers you (or auto-apply) chose.

## Never twice: the dedupe node (`nodes/dedupe.py`, `[dedupe]` in config.toml)

Every offer seen is stored with its **platform + platform id** (Indeed `jk`; the link when a platform has
no id), its **link** and its **title in the results list**.

| Situation | Result |
|---|---|
| same id/link, same title, already judged / skipped | skipped **before opening the page**: no LLM call |
| same id/link, **title edited** | read and judged again (`rejudge_if_title_changed`) |
| same title, **other link** (another entity of the company...) | a different offer: judged |
| already **applied** | never applied again, even with the dedupe node disabled (guard in the apply paths) |
| judge failed 3 times on it | skipped |
| `[dedupe] enabled = false` | every offer re-read and re-judged at each scan (costs tokens) |
| an offer you want judged again | `python jobs.py reset <id>` |

## Reset (`nodes/reset.py`)

Reset = "forget it": status back to `new`, verdict cleared, so the next scan reads and judges it again.
A backup of the database is made first, every time (`backups/` next to `jobs.db`).

```bash
python jobs.py scans                 # list scans and what each one found
python jobs.py reset last-scan       # everything the last scan processed
python jobs.py reset scan scan-20261008-0900
python jobs.py reset skipped         # any status: skipped, prefiltered, judged, needs_human, stuck...
python jobs.py reset 12              # one offer
python jobs.py reset all
```
Applied offers are protected: the command asks a second time (type `applied`), otherwise they stay applied.
Kept on reset: offer text, contacts, follow-ups (relances), notes.

## Daily use

```bash
python scan.py                 # search + judge + report (also what the schedule runs)
python review.py               # go through high then maybe: apply / skip / later
python review.py high          # only high
python apply_one.py "<url>"    # one offer, directly
python jobs.py list            # database (also: show, applied, relance, status, due, export, reset)
python jobs.py example 12 low "sales job"   # teach the judge
```

## Teaching the judge

1. Write `judge/profile.md` well: roles, stack, level, location, contract, what you refuse.
2. In `review.py`, when you **disagree** with the verdict, it offers to save the offer as an example.
3. Or later: `python jobs.py example <id> high|maybe|low "why"`.
4. Check the reports for a few days before trusting it.

## Scan AND apply at once, until sent (you watching)

```bash
python scan.py linkedin --apply high,maybe --supervised        # one agent per terminal
python scan.py linkedin --apply high --supervised --max 10
python review.py --apply high,maybe                             # offers already judged by earlier scans
```
- `--apply LEVELS`: each offer of these levels is applied to right after it is judged, **until sent**,
  privacy / consent boxes accepted. `maybe` too: the recruiter sees your CV for other roles in the company
  (in a free message field the agent adds one sentence: open to other AI / data / software roles).
- `--supervised`: you are at the PC. Captcha, security check, login, account creation, email/SMS code,
  a question the profile does not answer -> the agent brings the Chrome window to the front, beeps, and
  waits in the terminal: do it in Chrome, press Enter, it continues. Without `--supervised` these end as `needs_human`.
- The agent never types a password or creates an account itself: it waits for you to do it.
- Score floors per level: `[auto_apply] min_score = { high = 70, maybe = 40 }`.

**Unknown pages (company sites)** — the agent explores instead of getting lost: closes the cookie banner
(refuses), `find`s the apply button among ALL links/buttons, scrolls, takes a screenshot (`look`, `[apply] vision`)
when the page is unclear, and fills forms inside embedded frames (Workday, SmartRecruiters, Greenhouse...).
Prefers "postuler sans compte" when offered. After 6 steps without progress: `stuck`, with a description.

## Auto-apply (when you are away), step by step

In `config.toml` `[auto_apply]`:

1. `enabled = true`, `submit = false`: the agent fills the high offers up to the final page and stops
   (`ready_for_review`). You only check and click "send". Anything needing you -> `needs_human`.
2. `approve_legal = true`: it also ticks privacy / consent boxes.
3. `submit = true`: it sends by itself. Only when you trust it. Job boards' terms (e.g. Indeed Apply)
   may forbid automated applications: your account, your decision.

Never automated, whatever the config: passwords, login, account creation, captchas, other buttons on
the job board (save, alerts, "not interested"). Those end as `needs_human`.

## Never apply on some sites / companies (`[avoid]` in config.toml)

```toml
[avoid]
sites = ["3ds.com"]               # the site and its sub-domains (www.3ds.com, careers.3ds.com...)
companies = ["Dassault Systèmes"] # accents / case ignored
```
The offer is still read, judged and saved (you see it in the report) with the status `avoided`; only the
application is skipped. Checked before applying (offer page, its "apply on the company site" link, company name)
and during the application: if a job board sends the agent to an avoided site, it stops there at once.
Edit the lists any time; the next scan uses them.

## Schedule (Windows Task Scheduler)

`scan_task.bat` starts the 4 agent Chromes if needed (`start_all_chromes.bat`), then runs `scan.py` in WSL
(all agents at the same time).
Task Scheduler -> Create Basic Task -> Daily / every N hours -> Start a program -> `scan_task.bat`.
Logs: `runs/scan.log` (summary) and `runs/scan-<agent>.log`. Reports: `reports/scan-*-<agent>.md`.
The PC must be on, and you logged in once in each agent Chrome.

## Captcha / verification pages (Indeed "Vérification supplémentaire requise")

When an offer or results page is a verification page instead of the offer, it is never judged or saved.
You watching (`[auto_apply] supervised = true` or `--supervised`): the agent asks you to solve it in its
Chrome (terminal or Telegram), then goes on. Nobody there: that source stops for this scan; its offers come
back at the next scan. Offers judged on such a page before this fix: `python jobs.py reset blocked-pages`.

## Statuses

`new` -> `prefiltered` | `judged` (verdict + score) -> `skipped` | `ready_for_review` | `needs_human` |
`stuck` | `avoided` ([avoid] list) | `applied` -> `interview` | `rejected` | `offer` | `no_answer`; `closed` = offer page gone / no longer accepting

## Tests (offline: fake job board + fake company site + scripted LLM, no API key)

```bash
python tests/run_all.py
```
Covers: keywords, every guardrail, scan (prefilter, judge once, auto-apply off / legal / submit,
company site with a new tab, account creation blocked, CV upload), review (apply, skip, judge example),
fake LinkedIn (scrolling list, Easy Apply modal, company site, closed offer, login wall), fake WTTJ (list drawn
after load, form in a modal, company site, closed offer, tracking-link email), fake HelloWork (form drawn in
the offer page, "site du recruteur", expired offer, tracking-link email), 4 agents in parallel (4 processes,
one database, lock), unknown company site (cookie banner, hidden apply link, security check
with you watching / without you, form inside a frame, screenshot), apply levels high + maybe, alert emails
(real Indeed / LinkedIn formats, parsed once, browser + email in one scan, no password).
