"""The fake websites of the offline tests (job board, company site, LinkedIn, WTTJ, HelloWork).

  python tests/fakes.py      # serves them until stopped (run_all.py does this once for the whole run)
A test run alone starts them itself (common.py); when they are already served, it uses them.
"""
import functools
import http.server
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITES = ((8767, "fake_site"), (8771, "fake_company"), (8772, "fake_linkedin"), (8773, "fake_wttj"),
         (8774, "fake_hellowork"), (8775, "fake_freework"))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):                     # the test Chrome profile is persistent: never use a stale page
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_head(self):                       # no 304 "not modified" either
        if "If-Modified-Since" in self.headers:
            del self.headers["If-Modified-Since"]
        return super().send_head()


def start() -> list:
    servers = []
    for port, folder in SITES:
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port),
                                                  functools.partial(Quiet, directory=str(HERE / folder)))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            servers.append(srv)
        except OSError:
            pass                                       # already served (run_all.py, or an earlier test)
    return servers


if __name__ == "__main__":
    import time
    start()
    print("fake sites served", flush=True)
    while True:
        time.sleep(3600)
