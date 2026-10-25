"""Shared builders for candidate events and signals."""
from __future__ import annotations

from datetime import date

from .. import config
from ..extract import clean_text, detect_date_mentions
from ..normalize import (booking_from_text, canonical_url, category_hits, classify_category, contains_any,
                         detect_cities, empty_booking, stable_id)


def city_tz(city: str) -> str:
    return config.CITIES.get(city, {}).get("tz", "UTC")


def base_event(source: dict, ctx, *, title: str, url: str | None, city: str) -> dict:
    official = int(source.get("reliability", 4)) <= 2
    return {
        "kind": "event",
        "source_id": source["id"],
        "source_name": source["name"],
        "source_type": source.get("type"),
        "reliability": int(source.get("reliability", 4)),
        "official": official,
        "title": clean_text(title, 160),
        "description": None,
        "city": city,
        "neighborhood": None,
        "venue_name": None,
        "venue_address": None,
        "start": None,
        "end": None,
        "all_day": False,
        "timezone": city_tz(city),
        "occurrences": [],
        "category": None,
        "subcategory": None,
        "published_at": None,
        "event_status": "scheduled",
        "source_url": canonical_url(url),
        "official_url": canonical_url(url) if official else None,
        "booking": empty_booking(),
        "tags": [],
        "social_accounts": [],
        "checked_at": ctx.now_iso,
    }


def signal_type(title: str, summary: str | None) -> str:
    text = f"{title} {summary or ''}"
    if contains_any(text, config.RETROSPECTIVE_KEYWORDS):
        return "retrospective"
    if contains_any(text, config.OPENING_KEYWORDS):
        return "opening"
    if contains_any(text, config.EVENT_ANNOUNCE_KEYWORDS):
        return "announcement"
    return "news"


def make_signal(source: dict, ctx, item: dict, *, city: str | None) -> dict | None:
    url = canonical_url(item.get("url"))
    title = item.get("title")
    if not url or not title:
        return None
    pub = item.get("published")
    if pub:
        from datetime import datetime, timedelta

        try:
            age = datetime.fromisoformat(ctx.now_iso) - datetime.fromisoformat(pub)
        except ValueError:
            age = None
        if age is not None and age > timedelta(days=int(source.get("max_age_days", 45))):
            return None  # old article resurfacing in search/feeds: not a discovery
    summary = item.get("summary")
    if summary and summary.strip().lower().startswith(title.strip().lower()[:40]):
        summary = None  # many feeds repeat the title as the summary
    if not source.get("categories") and not source.get("keep_all") and category_hits(title, summary) == 0:
        return None  # general news with no lifestyle angle (a nursery school opening, a council meeting…)
    stype = signal_type(title, summary)
    ref = date.fromisoformat(ctx.today)
    mentions = [d for d in detect_date_mentions(f"{title}. {summary or ''}", ref) if d >= ctx.today]
    cat = classify_category(title, summary, hint=source.get("categories"))
    return {
        "kind": "signal",
        "id": "sig-" + stable_id(url),
        "source_id": source["id"],
        "source_name": item.get("source_title") or source["name"],
        "via": source["name"] if item.get("source_title") else None,
        "source_type": source.get("type"),
        "reliability": int(source.get("reliability", 4)),
        "url": url,
        "title": clean_text(title, 200),
        "summary": clean_text(summary, 200),
        "published_at": item.get("published"),
        "city": city,
        "category": cat,
        "signal_type": stype,
        "mentioned_dates": mentions[:4],
        "discovered_at": ctx.now_iso,
        "linked_event_id": None,
    }


def resolve_city(source: dict, *texts: str | None) -> str | None:
    """For single-city sources return that city; multi-city feeds need a keyword hit."""
    city = source.get("city")
    if city and city != "multi":
        kws = source.get("city_keywords")
        if kws and not contains_any(" ".join(t or "" for t in texts), kws):
            return None
        return city
    hits = detect_cities(*texts)
    return hits[0] if len(hits) == 1 else None


def passes_keywords(source: dict, *texts: str | None) -> bool:
    kws = source.get("keywords")
    if not kws:
        return True
    return contains_any(" ".join(t or "" for t in texts), kws) is not None


def apply_text_booking(ev: dict, text: str | None) -> None:
    booking_from_text(ev["booking"], text, official=ev["official"], checked_at=ev["checked_at"], source_url=ev["source_url"])
