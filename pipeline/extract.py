"""Deterministic extraction: schema.org JSON-LD events, RSS/Atom items, iCalendar events,
and conservative date-mention detection in short texts. No LLM calls."""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

EVENT_TYPES = {
    "event", "businessevent", "childrensevent", "comedyevent", "courseinstance", "danceevent",
    "deliveryevent", "educationevent", "eventseries", "exhibitionevent", "festival", "foodevent",
    "hackathon", "literaryevent", "musicevent", "publicationevent", "saleevent", "screeningevent",
    "socialevent", "sportsevent", "theaterevent", "visualartsevent", "theatreevent",
}


def clean_text(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = " ".join(str(v) for v in value if v)
    text = html.unescape(str(value))
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip(",.;:") + "…"
    return text


# ---------------------------------------------------------------- JSON-LD
def _iter_nodes(obj: Any) -> Iterable[dict]:
    if isinstance(obj, list):
        for item in obj:
            yield from _iter_nodes(item)
    elif isinstance(obj, dict):
        yield obj
        for key in ("@graph", "itemListElement", "subEvent", "event", "events", "item"):
            if key in obj:
                yield from _iter_nodes(obj[key])


def _types(node: dict) -> set[str]:
    t = node.get("@type")
    if isinstance(t, str):
        t = [t]
    return {str(x).split("/")[-1].lower() for x in (t or [])}


def extract_jsonld_events(page_html: str, base_url: str) -> list[dict]:
    """Return schema.org Event-like dicts found in <script type="application/ld+json">."""
    soup = BeautifulSoup(page_html, "html.parser")
    found: list[dict] = []
    seen = set()
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # tolerate trailing commas / control characters seen in the wild
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw.replace("\n", " ")))
            except json.JSONDecodeError:
                continue
        for node in _iter_nodes(data):
            if not (_types(node) & EVENT_TYPES):
                continue
            if not node.get("startDate") or not node.get("name"):
                continue
            key = (str(node.get("name")), str(node.get("startDate")), str(node.get("url")))
            if key in seen:
                continue
            seen.add(key)
            node = dict(node)
            if node.get("url"):
                node["url"] = urljoin(base_url, str(node["url"]))
            found.append(node)
    return found


def jsonld_location(node: dict) -> dict:
    loc = node.get("location")
    if isinstance(loc, list):
        loc = next((x for x in loc if isinstance(x, dict) and _types(x) & {"place", "eventvenue", "museum"}), loc[0] if loc else None)
    out = {"venue_name": None, "venue_address": None, "locality": None, "virtual": False}
    if isinstance(loc, str):
        out["venue_name"] = clean_text(loc, 140)
        return out
    if not isinstance(loc, dict):
        return out
    if "virtuallocation" in _types(loc):
        out["virtual"] = True
        return out
    out["venue_name"] = clean_text(loc.get("name"), 140)
    addr = loc.get("address")
    if isinstance(addr, dict):
        parts = [addr.get("streetAddress"), addr.get("postalCode"), addr.get("addressLocality")]
        out["venue_address"] = clean_text(", ".join(str(p) for p in parts if p), 200)
        out["locality"] = clean_text(addr.get("addressLocality"))
    elif isinstance(addr, str):
        out["venue_address"] = clean_text(addr, 200)
    return out


def jsonld_offers(node: dict) -> list[dict]:
    offers = node.get("offers")
    if offers is None:
        return []
    if isinstance(offers, dict):
        if "aggregateoffer" in _types(offers) and isinstance(offers.get("offers"), list):
            return [o for o in offers["offers"] if isinstance(o, dict)] or [offers]
        return [offers]
    if isinstance(offers, list):
        return [o for o in offers if isinstance(o, dict)]
    return []


# ---------------------------------------------------------------- RSS / Atom
def parse_feed(text: str) -> list[dict]:
    import feedparser

    parsed = feedparser.parse(text)
    items = []
    for e in parsed.entries:
        published = None
        for key in ("published_parsed", "updated_parsed"):
            st = e.get(key)
            if st:
                published = datetime(*st[:6]).isoformat() + "+00:00"
                break
        summary = e.get("summary") or e.get("description") or ""
        items.append({
            "title": clean_text(e.get("title"), 220),
            "url": e.get("link"),
            "published": published,
            "summary": clean_text(summary, 220),
            "author": clean_text(e.get("author")),
            "tags": [clean_text(t.get("term")) for t in e.get("tags", []) if t.get("term")],
            "source_title": clean_text((e.get("source") or {}).get("title")) if isinstance(e.get("source"), dict) else None,
        })
    return [i for i in items if i["title"] and i["url"]]


# ---------------------------------------------------------------- iCalendar
def parse_ical(text: str) -> list[dict]:
    from icalendar import Calendar

    cal = Calendar.from_ical(text)
    out = []
    for comp in cal.walk("VEVENT"):
        start = comp.get("dtstart")
        if start is None:
            continue
        end = comp.get("dtend")
        out.append({
            "name": clean_text(str(comp.get("summary") or "")),
            "start": start.dt,
            "end": end.dt if end is not None else None,
            "location": clean_text(str(comp.get("location") or "")) or None,
            "description": clean_text(str(comp.get("description") or ""), 300),
            "url": str(comp.get("url")) if comp.get("url") else None,
            "uid": str(comp.get("uid") or ""),
            "status": str(comp.get("status") or "").upper() or None,
        })
    return [e for e in out if e["name"]]


# ---------------------------------------------------------------- date mentions
MONTHS = {
    # en
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    # fr
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # it
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "agosto": 8, "settembre": 9, "ottobre": 10, "dicembre": 12,
    # de / lb
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "juni": 6, "juli": 7,
    "oktober": 10, "dezember": 12,
}
_MONTH_RE = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
_DAY_FIRST = re.compile(rf"\b(\d{{1,2}})(?:er|st|nd|rd|th|°)?\s+(?:de\s+)?({_MONTH_RE})\.?(?:\s+(20\d\d))?\b", re.I)
_MONTH_FIRST = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d\d))?\b", re.I)


def detect_date_mentions(text: str, reference: date) -> list[str]:
    """Find explicit day+month mentions. Year is inferred only as the next occurrence after
    the reference date and the result is always labelled 'mentioned', never 'confirmed'."""
    if not text:
        return []
    found: set[str] = set()
    for m in _DAY_FIRST.finditer(text):
        found.add(_mk(int(m.group(1)), m.group(2), m.group(3), reference))
    for m in _MONTH_FIRST.finditer(text):
        # avoid "may" as a verb: require capitalised May in month-first form
        if m.group(1).lower() == "may" and m.group(1) != "May":
            continue
        found.add(_mk(int(m.group(2)), m.group(1), m.group(3), reference))
    return sorted(d for d in found if d)


def _mk(day: int, month_name: str, year: str | None, ref: date) -> str | None:
    month = MONTHS.get(month_name.lower().rstrip("."))
    if not month or not 1 <= day <= 31:
        return None
    y = int(year) if year else ref.year
    try:
        d = date(y, month, day)
    except ValueError:
        return None
    # Without an explicit year, a date up to ~2 months in the past most likely refers to the
    # past (e.g. a recap article); anything earlier is assumed to be next year's date.
    if not year and (ref - d).days > 60:
        try:
            d = date(y + 1, month, day)
        except ValueError:
            return None
    return d.isoformat()
