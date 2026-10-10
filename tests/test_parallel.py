"""
4 agents AT THE SAME TIME (4 processes, 4 browsers, ONE database), like `python scan.py`:
indeed (fake Indeed), linkedin (fake LinkedIn), wttj (fake WTTJ), hellowork (fake HelloWork).
Checks: they really overlap, every offer is stored once, no "database is locked", one report per agent,
the same agent cannot run twice at once.
"""
import subprocess
import sys
import time
from common import CONFIG, ROOT, TMP, fresh

HERE = ROOT / "tests"

# 0) units ------------------------------------------------------------------------------------
from graphs.scan import searches_from_config
s = searches_from_config({"sources": ["indeed", "linkedin_email", "linkedin"], "queries": ["AI"], "max_pages": 2},
                         {}, only=["linkedin", "linkedin_email"])
assert s == [{"source": "linkedin_email", "max_pages": 1}, {"source": "linkedin", "query": "AI", "max_pages": 2}], s
s = searches_from_config({"sources": ["indeed"], "queries": ["AI"]}, {}, only=["linkedin", "linkedin_email"])
assert s == [], s                                     # switched off in [search] sources
CONFIG["agents"] = {"indeed": {"sources": ["indeed", "indeed_email"]}, "linkedin": {"sources": ["linkedin", "linkedin_email"]},
                    "wttj": {"sources": ["wttj"]}, "hellowork": {"sources": ["hellowork"]}}
from core.agents import agent_for_platform
assert [agent_for_platform(p) for p in ("indeed", "linkedin", "wttj", "hellowork")] == ["indeed", "linkedin", "wttj", "hellowork"]

# 1) four agents at once -----------------------------------------------------------------------
con = fresh("parallel")
con.close()
start = time.time()
procs = {a: subprocess.Popen([sys.executable, str(HERE / "agent_proc.py"), a, "parallel"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, cwd=ROOT)
         for a in ("indeed", "linkedin", "wttj", "hellowork")}
out = {a: p.communicate(timeout=400)[0] for a, p in procs.items()}
for a, p in procs.items():
    assert p.returncode == 0, (a, out[a][-2000:])
    assert "database is locked" not in out[a], a
times = {a: [float(l.split()[1]) for l in out[a].splitlines() if l.startswith(("START", "END"))] for a in out}
print({a: (round(t[0] - start, 1), round(t[1] - start, 1)) for a, t in times.items()}, "total", round(time.time() - start, 1))
assert max(t[0] for t in times.values()) < min(t[1] for t in times.values()), "the agents did not overlap"

import sqlite3
con = sqlite3.connect(TMP / "parallel.db")
rows = con.execute("SELECT source, count(*), sum(verdict IS NOT NULL) FROM applications GROUP BY source").fetchall()
print(rows)
assert {r[0]: (r[1], r[2]) for r in rows} == {"indeed": (5, 4), "linkedin": (4, 3), "wttj": (3, 2), "hellowork": (3, 2)}, rows
assert con.execute("SELECT count(*) FROM (SELECT platform, job_key FROM applications GROUP BY 1, 2 HAVING count(*) > 1)").fetchone()[0] == 0
reports = [p.name for p in (TMP / "reports-agent_proc").glob("scan-*.md")]
for a in procs:
    assert any(n.endswith(f"-{a}.md") or f"-{a}-" in n for n in reports), (a, reports)

# 2) the same agent twice at once: the second one does not start ----------------------------------
first = subprocess.Popen([sys.executable, str(HERE / "agent_proc.py"), "linkedin", "parallel"], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(4)
second = subprocess.run([sys.executable, str(HERE / "agent_proc.py"), "linkedin", "parallel"], capture_output=True,
                        text=True, cwd=ROOT, timeout=120)
first_out = first.communicate(timeout=300)[0]
assert second.returncode == 3 and "already running" in second.stdout, (second.returncode, second.stdout[-500:])
assert first.returncode == 0, first_out[-1500:]
print("\nALL PARALLEL CHECKS PASSED")
