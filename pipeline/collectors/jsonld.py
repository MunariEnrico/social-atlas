"""schema.org Event JSON-LD collectors."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..extract import clean_text, extract_jsonld_events, jsonld_location, jsonld_offers
from ..normalize import booking_from_offers, canonical_url, classify_category, parse_when
from . import CollectResult
from .common import apply_text_booking, base_event, city_tz

STATUS = {"eventcancelled": "cancelled", "eventpostponed": "postponed", "eventrescheduled": "rescheduled",
          "eventmovedonline": "scheduled", "eventscheduled": "scheduled"}


def _node_to_event(node: dict, source: dict, ctx, page_url: str) -> dict | None:
    city = source["city"]
    url = node.get("url") or page_url
    ev = base_event(source, ctx, title=node.get("name"), url=url, city=city)
    if not ev["title"]:
        return None
    tz = city_tz(city)
    ev["start"], ev["all_day"] = parse_when(node.get("startDate"), tz)
    end, end_all_day = parse_when(node.get("endDate"), tz)
    ev["end"] = end
    if ev["start"] is None:
        return None
    # "2026-11-20T00:00:00+01:00" with no end usually means a date-only listing
    if not ev["all_day"] and re.search(r"T00:00(:00)?", str(node.get("startDate"))) and (not end or re.search(r"T00:00|T23:59", str(node.get("endDate")))):
        ev["all_day"] = True
        ev["start"] = ev["start"][:10]
        ev["end"] = ev["end"][:10] if ev["end"] else None
    loc = jsonld_location(node)
    ev["venue_name"] = loc["venue_name"]
    ev["venue_address"] = loc["venue_address"]
    desc = clean_text(node.get("description"), 280)
    ev["description"] = desc
    status = str(node.get("eventStatus") or "").split("/")[-1].lower()
    ev["event_status"] = STATUS.get(status, "scheduled")
    ev["category"] = classify_category(ev["title"], desc, hint=source.get("categories"))
    booking_from_offers(ev["booking"], jsonld_offers(node), node.get("isAccessibleForFree"),
                        official=ev["official"], checked_at=ctx.now_iso,
                        currency_default=_currency(city), source_url=ev["source_url"])
    apply_text_booking(ev, desc)
    if loc["virtual"]:
        ev["tags"].append("online")
    if source.get("booking_platform") and ev["source_url"] and not ev["booking"].get("ticket_url"):
        # the listing itself is the organiser's sign-up/ticket page on a ticketing platform
        ev["booking"]["ticket_url"] = ev["source_url"]
        ev["booking"]["inferred"].append("booking link: the listing is the organiser's page on a ticketing platform; availability not checked")
    ev["_locality_text"] = " ".join(x for x in (ev["title"], loc["venue_name"], loc["venue_address"], loc["locality"]) if x)
    return ev


def _local_enough(ev: dict, source: dict) -> bool:
    """Ticketing platforms list a whole region under a city; keep only events whose venue
    text names the city (source.require_locality)."""
    words = source.get("require_locality")
    if not words:
        return True
    text = (ev.get("_locality_text") or "").lower()
    return any(w.lower() in text for w in words)


def _currency(city: str) -> str:
    from .. import config

    return config.CITIES.get(city, {}).get("currency", "EUR")


def _merge_occurrences(events: list[dict]) -> list[dict]:
    """Same title + same URL from one source = one event with several dates."""
    groups: dict[tuple, list[dict]] = {}
    for e in events:
        groups.setdefault((e["title"].lower(), e["source_url"]), []).append(e)
    out = []
    for items in groups.values():
        if len(items) == 1:
            out.append(items[0])
            continue
        items.sort(key=lambda e: e["start"])
        first = dict(items[0])
        first["occurrences"] = [e["start"] for e in items][:60]
        last = items[-1]
        first["end"] = last["end"] or last["start"]
        out.append(first)
    return out


def collect_page(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    r = ctx.fetcher.get(source["url"])
    res.log_fetch(r)
    if not r.ok:
        return res
    nodes = extract_jsonld_events(r.text or "", r.final_url or source["url"])
    evs = [e for e in (_node_to_event(n, source, ctx, source["url"]) for n in nodes) if e]
    local = [e for e in evs if _local_enough(e, source)]
    if len(local) < len(evs):
        res.notes.append(f"{len(evs) - len(local)} listing(s) outside the city skipped")
    for e in local:
        e.pop("_locality_text", None)
    res.events = _merge_occurrences(local)
    if not nodes:
        res.notes.append("page fetched but contained no schema.org Event data")
    return res


def collect_detail(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    r = ctx.fetcher.get(source["url"])
    res.log_fetch(r)
    if not r.ok:
        return res
    base = r.final_url or source["url"]
    soup = BeautifulSoup(r.text or "", "html.parser")
    pattern = re.compile(source["link_pattern"])
    host = urlparse(base).netloc.replace("www.", "")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        u = urljoin(base, a["href"]).split("#")[0]
        if urlparse(u).netloc.replace("www.", "") != host:
            continue
        if pattern.search(u) and u.rstrip("/") != base.rstrip("/") and u not in links:
            links.append(u)
    # events listed directly on the listing page count too
    nodes = extract_jsonld_events(r.text or "", base)
    evs = [e for e in (_node_to_event(n, source, ctx, base) for n in nodes) if e]
    max_details = int(source.get("max_details", 20))
    res.notes.append(f"{len(links)} event links found on listing; following up to {max_details}")
    no_data = 0
    for u in links[:max_details]:
        d = ctx.fetcher.get(u)
        res.log_fetch(d)
        if not d.ok:
            continue
        found = extract_jsonld_events(d.text or "", d.final_url or u)
        if not found:
            no_data += 1
            continue
        for n in found:
            if not n.get("url"):
                n["url"] = u
            e = _node_to_event(n, source, ctx, u)
            if e:
                evs.append(e)
    if no_data:
        res.notes.append(f"{no_data} detail pages had no structured event data (skipped, not guessed)")
    local = [e for e in evs if _local_enough(e, source)]
    for e in local:
        e.pop("_locality_text", None)
    res.events = _merge_occurrences(local)
    return res
