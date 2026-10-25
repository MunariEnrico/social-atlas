"""Stage 8 — Daily Briefing, generated only from what is stored in the database."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import config
from .normalize import end_bound, local_date, to_utc

BRIEFING_TZ = "Europe/Luxembourg"  # the reader's home timezone (Luxembourg / Venice share it)


def _is_today(ev: dict, day) -> bool:
    tz = ev.get("timezone") or "UTC"
    s, e = local_date(ev.get("start"), tz), local_date(ev.get("end"), tz)
    if s is None:
        return False
    if s == day:
        return True
    if ev.get("occurrences"):
        return any(local_date(o, tz) == day for o in ev["occurrences"])
    return False


def _running_and_closing(ev: dict, day, within_days: int = 7) -> bool:
    tz = ev.get("timezone") or "UTC"
    s, e = local_date(ev.get("start"), tz), local_date(ev.get("end"), tz)
    return bool(s and e and s < day <= e and (e - day).days <= within_days)


def _evening(ev: dict) -> bool:
    if ev.get("all_day") or not ev.get("start") or len(ev["start"]) <= 10:
        return False
    tz = ZoneInfo(ev.get("timezone") or "UTC")
    loc = to_utc(ev["start"]).astimezone(tz)
    return loc.time() >= time(17, 0)


def _why(ev: dict) -> str:
    r = ev.get("scores", {}).get("reasons", {})
    bits = list(r.get("relevance", []))[:3]
    b = ev["booking"]
    if b.get("tickets") == "sold_out_verified":
        bits.append("sold out per official listing")
    elif b.get("reservation") == "required":
        bits.append("reservation required")
    elif b.get("registration") == "required":
        bits.append("registration required")
    elif b.get("free"):
        bits.append("free")
    return " · ".join(bits)


def _item(ev: dict, why: str | None = None) -> dict:
    return {"event_id": ev["id"], "title": ev["title"], "city": ev["city"], "start": ev.get("start"), "end": ev.get("end"),
            "category": ev.get("category"), "why": why or _why(ev), "urgency": ev.get("urgency"),
            "verification_status": ev.get("verification_status")}


def build(events: list[dict], signals: list[dict], now: datetime, run_id: str | None) -> dict:
    tz = ZoneInfo(BRIEFING_TZ)
    today = now.astimezone(tz).date()
    live = [e for e in events if not e.get("hidden") and e.get("verification_status") not in ("past", "cancelled")]
    by_rel = sorted(live, key=lambda e: (-e["scores"]["relevance"], e.get("start") or "9999"))
    used: set[str] = set()

    def take(pool, n, why=None, allow_repeat=False):
        out = []
        for e in pool:
            if e["id"] in used and not allow_repeat:
                continue
            out.append(_item(e, why(e) if callable(why) else why))
            used.add(e["id"])
            if len(out) >= n:
                break
        return out

    # local "today" per city: a NYC event "today" uses NYC's date
    def city_today(e):
        return now.astimezone(ZoneInfo(e.get("timezone") or "UTC")).date()

    today_pool = [e for e in by_rel if _is_today(e, city_today(e)) or _running_and_closing(e, city_today(e), 2)]
    tonight_pool = [e for e in by_rel if _is_today(e, city_today(e)) and _evening(e)]
    top5 = take(today_pool, 5)
    tonight = take(tonight_pool, 6)

    week_end = now + timedelta(days=7)
    week_pool = [e for e in by_rel if (s := to_utc(e.get("start"))) and now < s <= week_end]
    this_week = take(week_pool, 10)

    day_ago = now - timedelta(days=1)
    disc_events = [e for e in by_rel if (f := to_utc(e.get("first_discovered_at"))) and f >= day_ago and not e.get("curated")]
    discovered = take(disc_events, 10)
    disc_signals = [s for s in signals if (d := to_utc(s.get("discovered_at"))) and d >= day_ago and s.get("signal_type") in ("opening", "announcement")]

    openings = [s for s in signals if s.get("signal_type") == "opening" and (p := to_utc(s.get("published_at") or s.get("discovered_at"))) and now - p <= timedelta(days=7)]
    openings.sort(key=lambda s: (s.get("reliability", 4), s.get("published_at") or ""), reverse=False)

    deadlines = []
    for e in live:
        d = to_utc(e["booking"].get("booking_deadline")) or to_utc(e["booking"].get("ticket_release"))
        if d and timedelta(0) <= d - now <= timedelta(days=14):
            deadlines.append((d, e))
    deadlines.sort(key=lambda x: x[0])
    deadline_items = [_item(e, f"deadline/ticket release {d.date().isoformat()}") for d, e in deadlines[:8]]

    last_min_pool = [e for e in by_rel if e.get("urgency") == "act_now"]
    last_minute = take(last_min_pool, 6)

    changes = []
    for e in events:
        for h in e.get("history", []):
            at = to_utc(h.get("at"))
            if at and now - at <= timedelta(days=2) and h["field"] in ("start", "end", "event_status", "venue_name", "booking.tickets", "booking.reservation"):
                changes.append({"event_id": e["id"], "title": e["title"], "city": e["city"], "field": h["field"], "old": h["old"], "new": h["new"], "at": h["at"]})
    changes = changes[:12]

    plan_pool = [e for e in by_rel if e.get("trip_suitable") and (((s := to_utc(e.get("start"))) and s - now > timedelta(days=21)) or not e.get("start"))]
    plan = take(plan_pool, 8, allow_repeat=False)

    counts = {c: sum(1 for e in live if e["city"] == c) for c in config.CITY_ORDER}
    return {
        "date": today.isoformat(),
        "timezone": BRIEFING_TZ,
        "generated_at": now.isoformat(),
        "run_id": run_id,
        "sections": {
            "top_today": top5,
            "tonight": tonight,
            "this_week": this_week,
            "new_openings": [{"signal_id": s["id"], "title": s["title"], "city": s["city"], "url": s["url"], "source": s["source_name"],
                              "published_at": s.get("published_at"), "why": "opening reported by " + s["source_name"]} for s in openings[:10]],
            "discovered_24h": discovered,
            "discovered_24h_signals": [{"signal_id": s["id"], "title": s["title"], "city": s["city"], "url": s["url"], "source": s["source_name"]} for s in disc_signals[:10]],
            "booking_deadlines": deadline_items,
            "last_minute": last_minute,
            "changes": changes,
            "plan_a_trip": plan,
        },
        "counts": {"live_events": len(live), "by_city": counts, "signals_24h": len(disc_signals)},
        "empty_note": None if live else "No upcoming events are stored yet — run the pipeline to populate the briefing.",
    }
