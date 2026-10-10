"""
NOTIFY node: tell you what the scan found. Today: terminal + a Markdown report in reports/.
Telegram / email later = another function here, called by the scan graph.
"""

from datetime import datetime

from core.config import CONFIG, ROOT


def _telegram_summary(found: list[dict], stats: dict, agent: str | None):
    from core import telegram
    high = sorted((f for f in found if f["verdict"] == "high"), key=lambda f: -f["score"])
    sent = [f for f in found if f.get("apply_status") == "applied"]
    need = [f for f in found if f.get("apply_status") in ("needs_human", "stuck", "ready_for_review")]
    lines = [f"📋 Scan done{' — ' + agent if agent else ''}: {len(found)} judged, {len(high)} high, "
             f"{sum(f['verdict'] == 'maybe' for f in found)} maybe, {len(sent)} applications sent."]
    if stats.get("blocked_sources"):
        lines.append(f"⛔ stopped: {stats['blocked_sources']} (login wall / security check / mailbox)")
    lines += [f"• {f['score']} {f['title'][:50]} | {f['company'][:30]}" for f in high[:5]]
    if need:
        lines.append(f"To check: " + ", ".join(f"#{f['id']} {f['apply_status']}" for f in need[:8]))
    telegram.send("\n".join(lines), "report")


def report(found: list[dict], stats: dict, agent: str | None = None) -> str:
    """found: [{id, verdict, score, title, company, url, reasons, apply_status}]"""
    folder = ROOT / CONFIG.get("notify", {}).get("reports_dir", "reports")
    folder.mkdir(parents=True, exist_ok=True)
    tag = f"-{agent}" if agent else ""
    path = folder / f"scan-{datetime.now():%Y%m%d-%H%M%S}{tag}.md"
    n = 1
    while path.exists():
        n += 1
        path = folder / f"scan-{datetime.now():%Y%m%d-%H%M%S}{tag}-{n}.md"
    lines = [f"# Scan {datetime.now():%Y-%m-%d %H:%M}" + (f" — agent {agent}" if agent else ""), "", "Stats: " + ", ".join(f"{k}={v}" for k, v in stats.items()), ""]
    if stats.get("blocked_sources"):
        lines += [f"**Stopped this time: {stats['blocked_sources']}** (login wall / security check / mailbox: see the scan log)", ""]
    for v in ("high", "maybe"):
        items = sorted((f for f in found if f["verdict"] == v), key=lambda f: -f["score"])
        lines += [f"## {v.upper()} ({len(items)})", ""]
        for f in items:
            done = f" -> **{f['apply_status']}**" if f.get("apply_status") else ""
            src = f" _({f['source']})_" if f.get("source") else ""
            lines.append(f"- #{f['id']} **{f['score']}** {f['title']} | {f['company']}{src}{done}  ")
            lines.append(f"  {'; '.join(f.get('reasons') or [])}  ")
            lines.append(f"  {f['url']}")
        lines.append("")
    lines.append("Review them: `python review.py`")
    path.write_text("\n".join(lines), encoding="utf-8")
    _telegram_summary(found, stats, agent)
    print("\n" + "\n".join(lines[:3]))
    print(f"high={sum(f['verdict'] == 'high' for f in found)} maybe={sum(f['verdict'] == 'maybe' for f in found)}"
          f"  report -> {path.relative_to(ROOT)}")
    return str(path)
