"""One agent process for test_parallel.py: fake sites + scripted LLM, then the REAL scan.py run_agent().
   python tests/agent_proc.py <agent> <database name>"""
import sys
import time
from common import BOARD, CONFIG, HELLOWORK, LINKEDIN, WTTJ, fresh

agent, dbname = sys.argv[1], sys.argv[2]
fresh(dbname, keep_db=True, search={"sources": ["indeed", "linkedin", "wttj", "hellowork"], "extra_search_urls": []})
CONFIG["agents"] = {
    "indeed": {"port": 9222, "sources": ["indeed"], "extra_search_urls": [BOARD + "/results.html"]},
    "linkedin": {"port": 9223, "sources": ["linkedin"], "extra_search_urls": [LINKEDIN + "/search.html"]},
    "wttj": {"port": 9224, "sources": ["wttj"], "extra_search_urls": [WTTJ + "/search.html"]},
    "hellowork": {"port": 9225, "sources": ["hellowork"], "extra_search_urls": [HELLOWORK + "/search.html"]},
}
import scan                                           # the real entry point
print("START", time.time(), flush=True)
code = scan.run_agent(agent)
print("END", time.time(), flush=True)
sys.exit(code)
