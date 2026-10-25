"""Normalisation helpers: dates/timezones, URLs, categories, cities, booking & price."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, time, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from dateutil import parser as dtparser

from . import config

# ------------------------------------------------------------------ time
UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_when(value, tz_name: str) -> tuple[str | None, bool]:
    """Parse a date or datetime into (ISO string, all_day).

    * date-only values stay date-only ("2026-11-20", all_day=True)
    * naive datetimes are interpreted in the city's timezone
    * aware datetimes keep their offset
    * midnight with no explicit time in many feeds means "date only"; we only treat it
      as all-day when the source string itself had no time component.
    """
    if value in (None, "", []):
        return None, False
    tz = ZoneInfo(tz_name)
    if isinstance(value, datetime):
        if not plausible_year(value.year):
            return None, False
        dt = value if value.tzinfo else value.replace(tzinfo=tz)
        return dt.replace(microsecond=0).isoformat(), False
    if isinstance(value, date):
        return (value.isoformat(), True) if plausible_year(value.year) else (None, False)
    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return (s, True) if plausible_year(int(s[:4])) else (None, False)
    try:
        dt = dtparser.isoparse(s)
    except (ValueError, OverflowError):
        try:
            dt = dtparser.parse(s, dayfirst=True)
        except (ValueError, OverflowError):
            return None, False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    if not plausible_year(dt.year):
        return None, False
    return dt.replace(microsecond=0).isoformat(), False


def plausible_year(y: int) -> bool:
    """Feeds occasionally carry corrupt dates (e.g. year 0206). Reject them."""
    return 2000 <= y <= 2100


def to_utc(value: str | None) -> datetime | None:
    """Comparable UTC datetime. Date-only values -> 00:00 UTC of that day (callers that
    need end-of-day semantics use end_bound)."""
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        d = date.fromisoformat(value)
        return datetime.combine(d, time(0, 0), UTC)
    try:
        dt = dtparser.isoparse(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def local_date(value: str | None, tz_name: str) -> date | None:
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    dt = to_utc(value)
    return dt.astimezone(ZoneInfo(tz_name)).date() if dt else None


def end_bound(event: dict) -> datetime | None:
    """The moment after which an event is over, in UTC. Uses end, else start; date-only
    values count until the end of that local day."""
    tz = ZoneInfo(config.CITIES.get(event.get("city"), {}).get("tz", "UTC"))
    for key in ("end", "start"):
        v = event.get(key)
        if not v:
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            d = date.fromisoformat(v)
            return datetime.combine(d, time(23, 59, 59), tz).astimezone(UTC)
        dt = to_utc(v)
        if dt is None:
            continue
        if key == "start":
            # an open-ended timed event: assume it is over at the end of its local day
            loc = dt.astimezone(tz)
            return datetime.combine(loc.date(), time(23, 59, 59), tz).astimezone(UTC)
        return dt
    return None


# ------------------------------------------------------------------ text / ids
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


STOP = {"the", "a", "an", "and", "of", "at", "in", "la", "le", "les", "il", "lo", "di", "da", "de", "des", "du", "et", "e", "y",
        "der", "die", "das", "und", "a", "au", "aux", "for", "with", "con", "per", "par", "pour", "on", "to"}


def title_key(title: str) -> str:
    t = strip_accents((title or "").lower())
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\b(19|20)\d\d\b", " ", t)  # edition years: "Paris Photo 2026" == "Paris Photo"
    t = re.sub(r"\b\d+(st|nd|rd|th|e|eme|a|o)?\s+edi\w*\b", " ", t)  # "12th edition", "12e édition"
    words = [w for w in t.split() if w not in STOP]
    return " ".join(words)


def stable_id(*parts: str) -> str:
    raw = "|".join(p or "" for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def slugify(s: str, limit: int = 48) -> str:
    s = strip_accents(s.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:limit].rstrip("-") or "event"


# ------------------------------------------------------------------ urls
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_cid$|mc_eid$|ref$|ref_src$|igshid$|aff$|_hs)")


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    p = urlparse(url)
    # unwrap Bing News redirect links
    if "bing.com" in p.netloc and "apiclick" in p.path:
        target = parse_qs(p.query).get("url", [None])[0]
        if target:
            return canonical_url(target)
    if p.scheme not in ("http", "https"):
        return None
    q = [(k, v) for k, vs in parse_qs(p.query, keep_blank_values=True).items() for v in vs if not TRACKING.match(k)]
    path = p.path or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", urlencode(q), ""))


def is_safe_public_url(url: str) -> bool:
    """Reject non-http(s), credentials in URL, localhost and private-network hosts."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc or "@" in p.netloc:
        return False
    host = (p.hostname or "").lower()
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return False
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        a, b = (int(x) for x in host.split(".")[:2])
        if a in (10, 127, 0) or (a == 169 and b == 254) or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168):
            return False
    if host.startswith("[") or ":" in host:
        return False
    return len(url) < 2000


# ------------------------------------------------------------------ classification
def _norm_text(*parts: str | None) -> str:
    return " " + strip_accents(" ".join(p for p in parts if p).lower()) + " "


def classify_category(*texts: str | None, hint: list[str] | None = None) -> str:
    text = _norm_text(*texts)
    scores: dict[str, int] = {}
    for cat, kws in config.CATEGORY_KEYWORDS.items():
        for kw in kws:
            if strip_accents(kw) in text:
                scores[cat] = scores.get(cat, 0) + 1
    if hint:
        for h in hint:
            if h in config.CATEGORIES:
                scores[h] = scores.get(h, 0) + 1
    if not scores:
        return (hint or ["culture"])[0] if hint else "culture"
    # design folds into art for navigation but keeps its own label when dominant
    return max(scores.items(), key=lambda kv: (kv[1], -list(config.CATEGORIES).index(kv[0])))[0]


def category_hits(*texts: str | None) -> int:
    text = _norm_text(*texts)
    return sum(1 for kws in config.CATEGORY_KEYWORDS.values() for kw in kws if strip_accents(kw) in text)


def detect_cities(*texts: str | None) -> list[str]:
    text = _norm_text(*texts)
    found = []
    for cid, c in config.CITIES.items():
        for kw in c["keywords"]:
            k = strip_accents(kw.lower())
            if re.search(r"(?<![a-z])" + re.escape(k.strip()) + r"(?![a-z])", text):
                found.append(cid)
                break
    # "chelsea"/"soho" exist in both NYC and London: drop ambiguous-only matches
    return found


def contains_any(text: str | None, patterns: list[str]) -> str | None:
    t = _norm_text(text)
    for p in patterns:
        if strip_accents(p.lower()) in t:
            return p
    return None


# ------------------------------------------------------------------ booking
def empty_booking() -> dict:
    return {
        "reservation": "unknown",
        "registration": "unknown",
        "tickets": "unknown",
        "access": "unknown",
        "price": None,
        "free": None,
        "reservation_url": None,
        "ticket_url": None,
        "registration_url": None,
        "booking_deadline": None,
        "ticket_release": None,
        "access_notes": None,
        "dress_code": None,
        "age_restriction": None,
        "verified_at": None,
        "inferred": [],
        "evidence": [],
    }


def booking_from_text(booking: dict, text: str | None, *, official: bool, checked_at: str, source_url: str | None) -> dict:
    """Read explicit statements in official text. Every field set here records why."""
    if not text:
        return booking
    hit = contains_any(text, config.SOLD_OUT_PATTERNS)
    if hit and official:
        booking["tickets"] = "sold_out_verified"
        booking["evidence"].append(f"Official listing says “{hit}” (checked {checked_at[:16].replace('T', ' ')} UTC)")
    hit = contains_any(text, config.REGISTRATION_REQUIRED_PATTERNS)
    if hit:
        booking["registration"] = "required"
        booking["evidence"].append(f"Listing text: “{hit}”")
    hit = contains_any(text, config.RESERVATION_REQUIRED_PATTERNS)
    if hit:
        booking["reservation"] = "required"
        booking["evidence"].append(f"Listing text: “{hit}”")
    hit = contains_any(text, config.FREE_PATTERNS)
    if hit:
        booking["free"] = True
        if booking["tickets"] == "unknown":
            booking["tickets"] = "free_registration" if booking["registration"] == "required" else "free_entry"
        booking["evidence"].append(f"Listing text: “{hit}”")
    hit = contains_any(text, config.INVITE_PATTERNS)
    if hit:
        booking["access"] = "invitation_only" if "invit" in hit or "invito" in hit else ("members_only" if "member" in hit or "soci" in hit else "industry_only")
        booking["evidence"].append(f"Listing text: “{hit}”")
    if booking["tickets"] == "free_entry" and booking["registration"] == "unknown":
        # free does not mean walk-in: leave registration unknown, note it
        booking["access_notes"] = booking.get("access_notes") or "Free — whether booking is needed is not stated."
    return booking


SCHEMA_AVAIL = {
    "instock": "available_verified",
    "limitedavailability": "available_verified",
    "onlineonly": "available_verified",
    "soldout": "sold_out_verified",
    "outofstock": "sold_out_verified",
    "presale": "not_on_sale_verified",
    "preorder": "not_on_sale_verified",
}


def booking_from_offers(booking: dict, offers: list[dict], accessible_free, *, official: bool,
                        checked_at: str, currency_default: str, source_url: str | None) -> dict:
    prices = []
    currency = None
    for o in offers:
        url = o.get("url")
        if url and not booking.get("ticket_url"):
            booking["ticket_url"] = url
        p = o.get("price") if o.get("price") not in (None, "") else o.get("lowPrice")
        hi = o.get("highPrice")
        try:
            if p not in (None, ""):
                prices.append(float(str(p).replace(",", ".")))
            if hi not in (None, ""):
                prices.append(float(str(hi).replace(",", ".")))
        except ValueError:
            pass
        currency = currency or o.get("priceCurrency")
        avail = str(o.get("availability") or "").split("/")[-1].lower()
        if avail in SCHEMA_AVAIL and official:
            booking["tickets"] = SCHEMA_AVAIL[avail]
            booking["evidence"].append(f"Official structured data: availability {avail} (as of {checked_at[:16].replace('T', ' ')} UTC)")
        vf = o.get("validFrom")
        if vf and not booking.get("ticket_release"):
            booking["ticket_release"] = str(vf)
    if prices:
        lo, hi = min(prices), max(prices)
        cur = currency or currency_default
        if hi == 0:
            booking["free"] = True
            booking["price"] = {"amount": 0, "currency": cur, "display": "Free", "source_url": source_url, "verified_at": checked_at}
            if booking["tickets"] == "unknown":
                booking["tickets"] = "free_registration"
        else:
            booking["free"] = False
            disp = f"{_fmt_money(lo, cur)}" if lo == hi else f"{_fmt_money(lo, cur)}–{_fmt_money(hi, cur)}"
            booking["price"] = {"amount": lo if lo == hi else None, "min": lo, "max": hi, "currency": cur,
                                "display": disp, "source_url": source_url, "verified_at": checked_at,
                                "per_person": None, "fees_included": None}
            if booking["tickets"] == "unknown":
                booking["tickets"] = "ticketed"
    if accessible_free is True or str(accessible_free).lower() == "true":
        booking["free"] = True
        if booking["tickets"] == "unknown":
            booking["tickets"] = "free_entry"
    if offers and booking["access"] == "unknown" and booking["tickets"] in ("ticketed", "available_verified", "sold_out_verified", "not_on_sale_verified"):
        booking["access"] = "public_ticketed"
        booking["inferred"].append("access: public, ticketed — the official page sells tickets to the public")
    return booking


def _fmt_money(v: float, cur: str) -> str:
    sym = {"EUR": "€", "GBP": "£", "USD": "$"}.get(cur, cur + " ")
    return f"{sym}{v:,.2f}".replace(".00", "")


def primary_action(event: dict) -> dict | None:
    b = event["booking"]
    if b.get("tickets") == "sold_out_verified":
        return {"label": "View official page", "url": event.get("official_url") or event.get("source_url"), "kind": "view"}
    if b.get("registration") == "required" and b.get("registration_url"):
        return {"label": "Register", "url": b["registration_url"], "kind": "register"}
    if b.get("reservation") in ("required", "recommended") and b.get("reservation_url"):
        return {"label": "Book a table" if event.get("category") in ("food", "nightlife") else "Reserve", "url": b["reservation_url"], "kind": "reserve"}
    if b.get("ticket_url"):
        label = "Reserve a ticket" if b.get("tickets") in ("ticketed", "available_verified", "paid_reservation") else "Check availability"
        return {"label": label, "url": b["ticket_url"], "kind": "ticket"}
    if b.get("registration_url"):
        return {"label": "Register", "url": b["registration_url"], "kind": "register"}
    url = event.get("official_url") or event.get("source_url")
    if not url:
        return None
    if b.get("access") == "unknown" or b.get("tickets") == "unknown":
        return {"label": "Verify access", "url": url, "kind": "verify"}
    return {"label": "View official event", "url": url, "kind": "view"}
