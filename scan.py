"""
Periodic scan (unattended): search -> read -> prefilter -> judge -> store -> [auto-apply] -> report.
Never asks anything. Schedule it with scan_task.bat (Windows Task Scheduler) or cron.

  python scan.py                  # every agent of config.toml [agents], AT THE SAME TIME (one Chrome each)
  python scan.py linkedin         # one agent
  python scan.py indeed wttj      # these agents, at the same time

  python scan.py linkedin --apply high,maybe --supervised
      scan AND apply at once: every high / maybe offer is applied to right after it is judged, until SENT
      (legal boxes accepted). --supervised: you watch, captchas / logins / unknown questions are asked
      in this terminal (one agent per terminal). Without it: those end as needs_human.
  --max 10                        # at most 10 applications in this run

Each agent: its own Chrome (start_all_chromes.bat), its own log runs/scan-<agent>.log, its own report.
The same agent never runs twice at once (lock file runs/agent-<name>.lock).
"""

import subprocess
import sys
import time
from pathlib import Path

from core.agents import AgentLock, AlreadyRunning, active_sources, agents
from core.config import ROOT


def apply_options(args: list[str]) -> tuple[list[str], list[str]]:
    """--apply high,maybe / --supervised / --max N -> CONFIG[auto_apply]. Returns (agent names, flags to pass on)."""
    from core.config import CONFIG
    names, flags, auto = [], [], CONFIG["auto_apply"]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--apply":
            levels = args[i + 1].split(",") if i + 1 < len(args) and not args[i + 1].startswith("--") else ["high"]
            auto.update(enabled=True, verdicts=levels, submit=True, approve_legal=True, max_per_run=10_000)  # --max to limit
            flags += [a, ",".join(levels)]
            i += 2 if i + 1 < len(args) and not args[i + 1].startswith("--") else 1
            continue
        if a == "--supervised":
            auto["supervised"] = True
            flags.append(a)
        elif a == "--max":
            auto["max_per_run"] = int(args[i + 1])
            flags += [a, args[i + 1]]
            i += 1
        else:
            names.append(a)
        i += 1
    return names, flags


def run_agent(name: str) -> int:
    from playwright.sync_api import sync_playwright
    from core import llm
    from core.browser import Session
    from core.config import CONFIG
    from graphs.scan import run_scan
    from core import telegram
    try:
        with AgentLock(name):
            llm.check_server(CONFIG["llm"]["judge_model"])
            print(f"=== agent {name}: {', '.join(active_sources(name))}")
            with sync_playwright() as p:
                s = Session(p, name)
                run_scan(s, name)
                s.close()
    except AlreadyRunning:
        print(f"agent {name} is already running: not started twice")
        return 3
    except KeyboardInterrupt:
        raise
    except Exception as e:                                  # the whole agent stopped: you are told
        telegram.send(f"💥 agent {name} stopped: {type(e).__name__}: {str(e)[:300]}", "errors")
        raise
    return 0


def run_parallel(names: list[str], flags: list[str] | None = None) -> int:
    """One process per agent (own Chrome, own log), all at once; waits for all of them."""
    logs = ROOT / "runs"
    logs.mkdir(exist_ok=True)
    procs = {}
    for name in names:
        log = open(logs / f"scan-{name}.log", "a", encoding="utf-8")
        log.write(f"\n##### {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.flush()
        from core import telegram                  # one terminal for all agents: a typed line would go to ANY of
        quiet = subprocess.DEVNULL if telegram.enabled("human") else None   # them -> questions on Telegram only
        procs[name] = (subprocess.Popen([sys.executable, str(Path(__file__).resolve()), name] + (flags or []),
                                        stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, stdin=quiet), log)
        print(f"started agent {name:10} -> runs/scan-{name}.log")
    worst = 0
    for name, (proc, log) in procs.items():
        code = proc.wait()
        log.close()
        worst = max(worst, code)
        last = [l for l in (logs / f"scan-{name}.log").read_text(encoding="utf-8").splitlines() if l.strip()][-1:]
        print(f"agent {name:10} {'ok' if code == 0 else f'exit {code}'}   {last[0][:110] if last else ''}")
    return worst


if __name__ == "__main__":
    from core.config import CONFIG
    names, flags = apply_options(sys.argv[1:])
    wanted = names or [n for n in agents() if active_sources(n)]
    if CONFIG["auto_apply"].get("supervised") and len(wanted) > 1:
        sys.exit("--supervised: one agent per terminal (you answer its questions), e.g.\n"
                 "  python scan.py linkedin --apply high,maybe --supervised")
    if CONFIG["auto_apply"].get("enabled"):
        a = CONFIG["auto_apply"]
        print(f"auto-apply ON: levels {a['verdicts']}, send={a.get('submit')}, legal={a.get('approve_legal')}, "
              f"supervised={bool(a.get('supervised'))}, max {a.get('max_per_run')}")
    unknown = [n for n in wanted if n not in agents()]
    if unknown:
        sys.exit(f"unknown agent(s) {unknown}. config.toml [agents]: {', '.join(agents())}")
    sys.exit(run_agent(wanted[0]) if len(wanted) == 1 else run_parallel(wanted, flags))
