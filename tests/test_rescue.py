"""
Supervised run: the agent must NOT move to the next offer when it wants to give up (needs_human / stuck).
It asks you first: Enter = you fixed it, it continues; skip = next offer. Unattended: it gives up as before.
"""
import litellm
from common import BOARD, ROOT, Human, _msg, fresh
from playwright.sync_api import sync_playwright
from core.browser import Session
from nodes.apply import apply

URL = BOARD + "/job6.html?jk=F6"
PLAN, SEEN = [], []


def scripted(model, messages, **kw):
    SEEN.append(messages[-1]["content"] if isinstance(messages[-1]["content"], str) else "")
    status = PLAN.pop(0) if PLAN else "ready_for_review"
    return _msg(name="finish", args={"status": status, "summary": f"{status}: email verification code"}, n=len(SEEN))


litellm.completion = scripted


class Recorder(Human):
    def __call__(self, prompt=""):
        self.full = getattr(self, "full", []) + [prompt]
        return super().__call__(prompt)


def run(name, supervised, answers, plan):
    fresh(name, auto_apply={"enabled": True, "submit": True, "approve_legal": True, "supervised": supervised})
    PLAN[:] = plan
    SEEN.clear()
    human = Recorder(answers)
    with sync_playwright() as p:
        s = Session(p)
        page = s.new_tab(URL)
        res = apply(page, URL, "auto", human if supervised else None, ROOT / "runs" / "tests" / name, verdict="high")
        s.close()
    print(name, res["status"], len(SEEN), "LLM calls", res["summary"][:150])
    return res, human


# 1) supervised, you fix it (Enter): the agent goes on instead of skipping the offer
res, human = run("rescue1", True, [""], ["needs_human"])
assert any("about to GIVE UP" in q for q in human.full), human.full
assert len(SEEN) == 2 and "do NOT give up" in SEEN[1], SEEN
assert res["status"] == "ready_for_review", res

# 2) supervised, you answer skip: it gives up now (next offer)
res, human = run("rescue2", True, ["skip"], ["stuck"])
assert any("about to GIVE UP" in q for q in human.full) and len(SEEN) == 1, SEEN
assert res["status"] in ("stuck", "needs_human"), res

# 3) supervised, it keeps giving up: asked at most 3 times, then it stops
res, human = run("rescue3", True, ["", "", "", ""], ["stuck"] * 6)
assert sum("about to GIVE UP" in q for q in human.full) == 3 and len(SEEN) == 4, (human.full, SEEN)

# 4) unattended: nobody to ask, it gives up at once (as before)
res, _ = run("rescue4", False, [], ["needs_human"])
assert len(SEEN) == 1 and res["status"] == "needs_human", res

# 5) the LLM keeps changing ONE field (Nextra: "Préfixe téléphonique" 10 times): told to stop at the 4th time
LOOP = [("select_option", {"ref": "e1", "option": "France (+33)"}), ("click", {"ref": "e1"}), ("look", {}),
        ("select_option", {"ref": "e1", "option": "France"}), ("click", {"ref": "e1"}), ("look", {}),
        ("finish", {"status": "stuck", "summary": "loop"})]
TOOL_OUT = []


def looping(model, messages, **kw):
    TOOL_OUT[:] = [m["content"] for m in messages if m["role"] == "tool"]
    name, args = LOOP[min(len(TOOL_OUT), len(LOOP) - 1)]
    return _msg(name=name, args=args, n=len(messages))


litellm.completion = looping
fresh("rescue5", auto_apply={"enabled": True, "submit": True, "approve_legal": True, "supervised": False})
with sync_playwright() as p:
    s = Session(p)
    page = s.new_tab(URL)
    apply(page, URL, "auto", None, ROOT / "runs" / "tests" / "rescue5", verdict="high")
    s.close()
assert sum("STOP touching" in o for o in TOOL_OUT) == 1 and "STOP touching" in TOOL_OUT[4], TOOL_OUT

print("\nALL RESCUE CHECKS PASSED")
