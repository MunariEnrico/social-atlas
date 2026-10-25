"""Write the public JSON the static frontend reads (site/data/)."""
from __future__ import annotations

from datetime import timedelta

from . import config
from .normalize import now_utc, to_utc
from .store import load_json, load_sources, load_yaml, save_json

PUBLIC_EVENT_DROP = {"preset_verification"}


def export_site(db) -> None:
    out = config.SITE_DATA
    now = now_utc()
    live, past = [], []
    for e in db.events.values():
        if e.get("hidden") or e.get("duplicate_of"):
            continue
        rec = {k: v for k, v in e.items() if k not in PUBLIC_EVENT_DROP}
        rec["history"] = e.get("history", [])[-6:]
        (past if e.get("verification_status") == "past" else live).append(rec)
    live.sort(key=lambda e: (e.get("start") or "9999", e["id"]))
    past.sort(key=lambda e: (e.get("end") or e.get("start") or ""), reverse=True)
    save_json(out / "events.json", live, compact=True)
    save_json(out / "archive.json", [
        {k: e.get(k) for k in ("id", "title", "city", "start", "end", "all_day", "timezone", "category", "venue_name", "source_url", "official_url", "sources", "verification_status")}
        for e in past
    ], compact=True)
    cutoff = now - timedelta(days=45)
    sigs = [s for s in db.signals.values() if (to_utc(s.get("published_at") or s.get("discovered_at")) or now) >= cutoff]
    sigs.sort(key=lambda s: (s.get("published_at") or s.get("discovered_at") or ""), reverse=True)
    save_json(out / "signals.json", sigs, compact=True)

    sources = []
    for s in load_sources():
        st = db.source_state.get(s["id"], {})
        sources.append({
            "id": s["id"], "name": s["name"], "city": s["city"], "type": s.get("type"), "reliability": s.get("reliability"),
            "url": s.get("url"), "method": s["method"], "categories": s.get("categories", []), "language": s.get("language"),
            "probe": s.get("probe"), "reason": s.get("reason"), "frequency_days": s.get("frequency_days", 1),
            "query": s.get("queries") or s.get("query"), "feed": s.get("feed") or s.get("api"),
            "state": {k: st.get(k) for k in ("last_attempt_at", "last_success_at", "last_status", "last_error", "consecutive_failures",
                                             "last_event_found_at", "last_signal_found_at", "last_counts", "totals", "monitorable", "last_duration_ms")},
        })
    accounts = load_yaml(config.ACCOUNTS_FILE, {}) or {}
    save_json(out / "sources.json", {"sources": sources, "accounts": accounts.get("accounts", [])}, compact=True)

    runs = db.runs[-40:]
    save_json(out / "runs.json", list(reversed(runs)), compact=True)
    brief = load_json(config.BRIEFINGS_DIR / "latest.json", None)
    save_json(out / "briefing.json", brief, compact=True)

    finished = [r for r in db.runs if r.get("finished_at") or r.get("status") != "running"]
    last = db.runs[-1] if db.runs else None
    last_ok = next((r for r in reversed(db.runs) if r.get("status") in ("success", "partial") and r.get("mode") == "collect"), None)
    last_sched = next((r for r in reversed(db.runs) if r.get("trigger") == "schedule"), None)
    meta = {
        "generated_at": now.isoformat(),
        "cities": {cid: {k: c[k] for k in ("name", "tz", "currency", "airports", "flight_code")} | {"nearest_airports": c.get("nearest_airports", [])}
                   for cid, c in config.CITIES.items()},
        "city_order": config.CITY_ORDER,
        "categories": config.CATEGORIES,
        "last_run": _run_summary(last),
        "last_successful_run": _run_summary(last_ok),
        "last_scheduled_run": _run_summary(last_sched),
        "runs_recorded": len(finished),
        "counts": {"events_live": len(live), "events_archived": len(past), "signals_45d": len(sigs), "sources": len(sources),
                   "sources_monitorable": sum(1 for s in sources if s["method"] != "manual")},
    }
    save_json(out / "meta.json", meta, compact=True)


def _run_summary(r: dict | None) -> dict | None:
    if not r:
        return None
    keys = ("run_id", "trigger", "runner", "started_at", "finished_at", "status", "mode", "sources_attempted", "sources_ok",
            "sources_failed", "events_new", "events_updated", "signals_new", "github_run_url")
    return {k: r.get(k) for k in keys}
