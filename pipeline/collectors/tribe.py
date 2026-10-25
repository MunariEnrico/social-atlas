"""WordPress 'The Events Calendar' REST API (/wp-json/tribe/events/v1/events)."""
from __future__ import annotations

import json

from ..extract import clean_text
from ..normalize import canonical_url, classify_category, parse_when
from . import CollectResult
from .common import apply_text_booking, base_event, city_tz


def collect(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    url = source["api"] + f"?per_page={int(source.get('max_items', 30))}&start_date={ctx.today}"
    r = ctx.fetcher.get(url, accept_json=True)
    res.log_fetch(r)
    if not r.ok:
        return res
    try:
        data = json.loads(r.text or "{}")
    except json.JSONDecodeError:
        res.errors.append("API did not return JSON")
        return res
    city = source["city"]
    tz = city_tz(city)
    for e in data.get("events", []):
        ev = base_event(source, ctx, title=clean_text(e.get("title")), url=e.get("url"), city=city)
        if e.get("all_day"):
            ev["start"], ev["all_day"] = (e.get("start_date") or "")[:10] or None, True
            ev["end"] = (e.get("end_date") or "")[:10] or None
        else:
            # The Events Calendar returns local wall-clock times plus a timezone name
            etz = e.get("timezone") or tz
            ev["start"], _ = parse_when(e.get("start_date"), etz if "/" in str(etz) else tz)
            ev["end"], _ = parse_when(e.get("end_date"), etz if "/" in str(etz) else tz)
        if not ev["start"]:
            continue
        venue = e.get("venue") if isinstance(e.get("venue"), dict) else {}
        ev["venue_name"] = clean_text(venue.get("venue"))
        parts = [venue.get("address"), venue.get("zip"), venue.get("city")]
        ev["venue_address"] = clean_text(", ".join(p for p in parts if p)) or None
        ev["description"] = clean_text(e.get("excerpt") or e.get("description"), 280)
        ev["category"] = classify_category(ev["title"], ev["description"], hint=source.get("categories"))
        cost = clean_text(e.get("cost"))
        b = ev["booking"]
        if cost:
            if cost.strip().lower() in ("free", "gratuit", "gratis", "0", "€0", "0 €"):
                b["free"] = True
                b["tickets"] = "free_registration" if e.get("website") else "free_entry"
                b["price"] = {"amount": 0, "currency": "EUR", "display": "Free", "source_url": ev["source_url"], "verified_at": ctx.now_iso}
            else:
                b["price"] = {"amount": None, "currency": None, "display": cost, "source_url": ev["source_url"], "verified_at": ctx.now_iso}
                b["free"] = False
        site = canonical_url(e.get("website"))
        if site:
            b["registration_url"] = site
            b["evidence"].append("Organiser lists an external sign-up/website link")
        apply_text_booking(ev, f"{ev['description'] or ''} {cost or ''}")
        res.events.append(ev)
    return res
