"""Scripted "LLM" shared by the offline tests: rules that do what a good model should do."""
import json, re, types


def ref(state, pattern):
    line = [l for l in state.splitlines() if re.search(pattern, l, re.I) and "[e" in l][-1]
    return re.search(r"\[(e\d+)\]", line).group(1)

def plan(state, asked, blocked, last=""):
    """What a good LLM should do, as rules."""
    if not state:                                       return "read_page", {}
    if "Postuler maintenant" in state and "Activer" in state and "BLOCKED" not in last:
        return "click", {"ref": ref(state, "Activer")}                                 # must be blocked
    if "Postuler maintenant" in state:                  return "click", {"ref": ref(state, "Postuler maintenant")}
    if "Combien" in state and not asked:                return "ask_human", {"question": "Years of Python?"}
    if "Combien" in state and 'value="3 ans"' not in state:
        return "type_text", {"ref": ref(state, "Combien"), "text": "3 ans"}
    if "Combien" in state and "Courant" not in state:   return "select_option", {"ref": ref(state, "anglais"), "option": "Courant"}
    if "Combien" in state:                              return "click", {"ref": ref(state, "Continuer")}
    if re.search(r"Approuver[^\n]*checked=false", state): return "set_checked", {"ref": ref(state, "Approuver"), "checked": True}
    if re.search(r"alertes[^\n]*checked=true", state):  return "set_checked", {"ref": ref(state, "alertes"), "checked": False}
    if "Examiner" in state:                             return "click", {"ref": ref(state, "Examiner")}
    if "Relisez" in state and not blocked:              return "click", {"ref": ref(state, "Déposer")}  # must be blocked
    return "finish", {"status": "ready_for_review", "summary": "Python: 3 ans, anglais: Courant, privacy approved, alert off."}

def fake_completion(model, messages, **kw):
    if not kw.get("tools"):                              # offer extraction call (no tools, JSON answer)
        prompt = messages[-1]["content"]
        company = next((c for c in ("ACME IA", "BetaCorp", "Gamma") if c in prompt), "ACME IA")
        content = json.dumps({"title": "AI Engineer H/F", "company": company, "location": "Paris",
                              "contract_type": "CDI", "remote": "hybrid", "salary": "50-60 k€",
                              "skills": ["Python", "LangGraph", "Qdrant"], "summary": "RAG and LLM agents.",
                              "contact_name": "Marie Dupont", "contact_email": None, "contact_phone": None})
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content="```json\n" + content + "\n```", tool_calls=None))], usage=None)
    tools_out = [m["content"] for m in messages if m["role"] == "tool"]
    state = next((t for t in reversed(tools_out) if "ELEMENTS:" in t), "")
    asked = any(m["role"] == "assistant" and m.get("tool_calls") and
                m["tool_calls"][0]["function"]["name"] == "ask_human" for m in messages)
    blocked = any(t.startswith("BLOCKED") and "submit" in t for t in tools_out)
    name, args = plan(state, asked, blocked, tools_out[-1] if tools_out else "")
    tc = types.SimpleNamespace(id=f"c{len(messages)}", function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=None, tool_calls=[tc]))], usage=None)

