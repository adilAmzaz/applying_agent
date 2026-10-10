"""STORE node: every database write of the pipeline in one place."""

from datetime import date

from core import db

# apply node status -> database status
APPLY_TO_DB = {"submitted": "applied", "ready_for_review": "ready_for_review",
               "needs_human": "needs_human", "stuck": "stuck",
               "avoided": "avoided"}                        # [avoid] site / company: never applied there
FIELDS = ["title", "company", "location", "contract_type", "remote", "salary", "experience_required",
          "skills", "summary", "contact_name", "contact_email", "contact_phone"]


def save_offer(con, url: str, offer: dict, source: str) -> int:
    """offer = read node output (+ judge fields if any)."""
    fields = {k: offer.get(k) for k in FIELDS}
    for k, v in (offer.get("contacts") or {}).items():         # regex contacts fill what the LLM left empty
        if v and not fields.get(k):
            fields[k] = v
    fields["title"] = fields["title"] or offer.get("title")
    app_id = db.upsert_offer(con, url, fields, offer.get("text", ""))
    db.update(con, app_id, apply_kind=offer.get("apply_kind"), external_url=offer.get("external_url"), source=source)
    if offer.get("listing_title"):                 # the title seen in the results list (used by the dedupe node)
        db.update(con, app_id, listing_title=offer["listing_title"])
    return app_id


def _sent(con, app_id: int) -> bool:
    """Already applied: the scan may refresh its fields but never changes its status back."""
    row = con.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()
    return row is not None and row["status"] in db.APPLIED_STATUSES


def save_prefiltered(con, app_id: int, reason: str):
    if _sent(con, app_id):
        return
    db.update(con, app_id, status="prefiltered", notes=reason)


def save_judgment(con, app_id: int, j: dict):
    if j.get("verdict") and _sent(con, app_id):
        db.update(con, app_id, verdict=j["verdict"], score=j.get("score"))     # keep 'applied'
    elif j.get("verdict"):
        db.save_judgment(con, app_id, j)
        db.update(con, app_id, tokens_in=j["usage"]["in"], tokens_out=j["usage"]["out"], model=j.get("model"))
    elif str(j.get("error", "")).startswith(("LLMDown", "LLM still failing")):   # outage: not the offer's fault
        db.update(con, app_id, notes=f"judge not done (LLM down): {j.get('error')}")
    else:                                          # stays 'new': re-judged next scan, at most 3 times
        con.execute("UPDATE applications SET judge_attempts = COALESCE(judge_attempts, 0) + 1, notes=? WHERE id=?",
                    (f"judge failed: {j.get('error')}", app_id))
        con.commit()


def save_application(con, app_id: int, res: dict, mode: str, run_dir):
    status = APPLY_TO_DB.get(res.get("status"), "stuck")
    row = con.execute("SELECT tokens_in, tokens_out FROM applications WHERE id=?", (app_id,)).fetchone()
    extra = {"applied_at": date.today().isoformat()} if status == "applied" else {}
    notes = res.get("summary") or ""
    if res.get("unanswered"):
        notes += "\nUNANSWERED: " + " | ".join(q[:120] for q in res["unanswered"])
    db.update(con, app_id, status=status, agent_summary=notes, auto=int(mode == "auto"), run_dir=str(run_dir),
              tokens_in=(row["tokens_in"] or 0) + res["usage"]["in"],
              tokens_out=(row["tokens_out"] or 0) + res["usage"]["out"], **extra)
    return status
