"""
Agents = one per job board, each with ITS OWN Chrome (own profile = own logins, own debugging port)
and its own sources (browser + alert emails of that board). They can run at the same time:
separate Chromes (no agent closes another one's tabs), one database (writes wait for each other).

config.toml [agents]:  linkedin = { port = 9223, profile = "linkedin", sources = ["linkedin", "linkedin_email"] }
[search] sources stays the on/off switch: an agent only runs the sources that are also listed there.
"""

import os
import sys
from pathlib import Path

from core.config import CONFIG, ROOT


def agents() -> dict:
    """{name: {port, profile, sources, ...}}. No [agents] section: one agent "main" on port 9222 (old setup)."""
    a = CONFIG.get("agents") or {}
    if not a:
        return {"main": {"port": 9222, "profile": "", "sources": list(CONFIG["search"].get("sources") or
                                                                    [CONFIG["search"].get("source", "indeed")])}}
    return a


def active_sources(name: str) -> list[str]:
    """Sources of this agent that are switched on in [search] sources."""
    on = CONFIG["search"].get("sources")
    mine = agents()[name].get("sources", [])
    return [s for s in mine if on is None or s in on]


def cdp_url(name: str) -> str:
    return f"http://localhost:{agents()[name].get('port', 9222)}"


def agent_for_platform(platform: str) -> str:
    """Which agent's Chrome opens an offer of this platform (review / apply_one): the one logged in there."""
    from nodes.sources import get_source
    for name, a in agents().items():
        for s in a.get("sources", []):
            try:
                if get_source(s).PLATFORM == platform:
                    return name
            except ModuleNotFoundError:
                pass
    return next(iter(agents()))


class AgentLock:
    """One run per agent at a time (e.g. the scheduled scan starts while you run one by hand)."""

    def __init__(self, name: str):
        self.path = ROOT / "runs" / f"agent-{name}.lock"
        self.f = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+")
        try:
            import fcntl                                    # WSL / Linux
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:                                 # native Windows Python: msvcrt
            import msvcrt
            try:
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.f.close()
                raise AlreadyRunning(self.path.stem)
        except OSError:
            self.f.close()
            raise AlreadyRunning(self.path.stem)
        self.f.seek(0), self.f.truncate(), self.f.write(str(os.getpid())), self.f.flush()
        return self

    def __exit__(self, *exc):
        self.f.close()                                      # closing releases the lock


class AlreadyRunning(RuntimeError):
    pass
