"""RSS/Atom collectors.

rss_news   -> signals (news items are leads, never auto-confirmed events)
rss_events -> events, for official feeds whose items ARE events and whose pubDate is the
              event start (declared per source; e.g. the City of Luxembourg agenda feed).
"""
from __future__ import annotations

from ..extract import parse_feed
from ..normalize import classify_category, parse_when
from . import CollectResult
from .common import apply_text_booking, base_event, city_tz, make_signal, passes_keywords, resolve_city


def _fetch_items(source: dict, ctx, res: CollectResult) -> list[dict]:
    r = ctx.fetcher.get(source["feed"])
    res.log_fetch(r)
    if not r.ok:
        return []
    head = (r.text or "")[:600].lower()
    if not any(tag in head for tag in ("<rss", "<feed", "<rdf", "<?xml")):
        res.errors.append(f"{source['feed']}: response is not a feed (HTML or bot protection page)")
        res.fetches[-1]["ok"] = False
        return []
    try:
        items = parse_feed(r.text or "")
    except Exception as exc:  # malformed feed
        res.errors.append(f"feed parse error: {type(exc).__name__}")
        return []
    if not items:
        res.notes.append("feed fetched but contained no items")
    return items[: int(source.get("max_items", 60))]


def collect_news(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    kept = skipped_kw = skipped_city = 0
    for item in _fetch_items(source, ctx, res):
        if not passes_keywords(source, item["title"], item.get("summary")):
            skipped_kw += 1
            continue
        city = resolve_city(source, item["title"], item.get("summary"))
        if city is None:
            skipped_city += 1
            continue
        sig = make_signal(source, ctx, item, city=city)
        if sig:
            res.signals.append(sig)
            kept += 1
    if skipped_kw or skipped_city:
        res.notes.append(f"kept {kept}; skipped {skipped_kw} off-topic and {skipped_city} without a tracked city")
    return res


def collect_events(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    city = source["city"]
    tz = city_tz(city)
    now = datetime.fromisoformat(ctx.now_iso)
    bad_dates = started = 0
    for item in _fetch_items(source, ctx, res):
        start, _ = parse_when(item.get("published"), tz)
        if not start:
            bad_dates += 1
            continue
        local = datetime.fromisoformat(start).astimezone(ZoneInfo(tz))
        if local < now - timedelta(hours=12):
            # Already started and the feed gives no end date: we cannot tell whether it is
            # still running, so we do not list it as upcoming (and do not invent an end).
            started = started + 1
            continue
        ev = base_event(source, ctx, title=item["title"], url=item["url"], city=city)
        if local.hour == 0 and local.minute == 0:
            ev["start"], ev["all_day"] = local.date().isoformat(), True  # midnight = date-only listing
        else:
            ev["start"] = local.isoformat()
        ev["description"] = item.get("summary")
        ev["category"] = classify_category(item["title"], item.get("summary"), hint=source.get("categories"))
        ev["tags"].append("start time from official feed")
        apply_text_booking(ev, item.get("summary"))
        res.events.append(ev)
    if bad_dates:
        res.notes.append(f"{bad_dates} item(s) skipped: invalid date in feed")
    if started:
        res.notes.append(f"{started} item(s) skipped: already started, end date not published")
    return res
