"""Runs every offline test (no API key, no real site), 4 at a time.

  python tests/run_all.py                    # all of them (~5-8 min)
  python tests/run_all.py autopilot explore  # only these (test_<name>.py)
  python tests/run_all.py -j 1               # one at a time
"""
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

here = Path(__file__).parent
ALL = ["test_keywords.py", "test_policy.py", "test_scan.py", "test_review.py", "test_reset.py",
       "test_linkedin.py", "test_email.py", "test_wttj.py", "test_hellowork.py",
       "test_parallel.py", "test_explore.py", "test_autopilot.py", "test_accounts.py",
       "test_telegram.py", "test_rescue.py", "test_consent.py", "test_davidson.py", "test_fields.py", "test_llm.py", "test_ashby.py", "test_shadow.py", "test_freework.py", "test_avoid.py", "test_challenge.py"]
args = sys.argv[1:]
jobs = 4
if "-j" in args:
    i = args.index("-j")
    jobs = int(args[i + 1])
    args = args[:i] + args[i + 2:]
wanted = [f"test_{a.removeprefix('test_').removesuffix('.py')}.py" for a in args] or ALL
# the longest first: the 4 lanes finish together
ORDER = ["test_scan.py", "test_explore.py", "test_review.py", "test_linkedin.py", "test_autopilot.py",
         "test_parallel.py", "test_wttj.py", "test_hellowork.py", "test_email.py", "test_accounts.py"]
wanted.sort(key=lambda t: ORDER.index(t) if t in ORDER else 99)


def run(t):
    start = time.time()
    r = subprocess.run([sys.executable, str(here / t)], capture_output=True, text=True)
    return t, r, time.time() - start


# the fake websites, served ONCE for the whole run (a test that served them would take them away when it ends)
server = subprocess.Popen([sys.executable, str(here / "fakes.py")], stdout=subprocess.PIPE, text=True)
server.stdout.readline()
start, failed = time.time(), []
with ThreadPoolExecutor(max_workers=jobs) as pool:
    for t, r, took in pool.map(run, wanted):
        last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
        print(f"{'OK  ' if r.returncode == 0 else 'FAIL'} {t:20} {took:5.0f}s  {last[:90]}", flush=True)
        if r.returncode:
            failed.append(t)
            print(r.stdout[-1500:], r.stderr[-1500:])
server.terminate()
print(f"\n{len(wanted) - len(failed)}/{len(wanted)} passed in {time.time() - start:.0f}s")
sys.exit(1 if failed else 0)
