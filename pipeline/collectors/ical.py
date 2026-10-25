"""iCalendar (.ics) feeds."""
from __future__ import annotations

from ..extract import parse_ical
from ..normalize import classify_category, parse_when
from . import CollectResult
from .common import apply_text_booking, base_event, city_tz


def collect(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    r = ctx.fetcher.get(source["feed"])
    res.log_fetch(r)
    if not r.ok:
        return res
    try:
        items = parse_ical(r.text or "")
    except Exception as exc:
        res.errors.append(f"ical parse error: {type(exc).__name__}")
        return res
    city = source["city"]
    tz = city_tz(city)
    for it in items:
        ev = base_event(source, ctx, title=it["name"], url=it.get("url") or source["url"], city=city)
        ev["start"], ev["all_day"] = parse_when(it["start"], tz)
        ev["end"], _ = parse_when(it.get("end"), tz)
        if not ev["start"]:
            continue
        ev["venue_name"] = it.get("location")
        ev["description"] = it.get("description")
        if it.get("status") == "CANCELLED":
            ev["event_status"] = "cancelled"
        ev["category"] = classify_category(ev["title"], ev["description"], hint=source.get("categories"))
        apply_text_booking(ev, ev["description"])
        res.events.append(ev)
    return res
