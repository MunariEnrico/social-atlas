"""Researched events from data/curated/*.yaml.

These are entered by a person (or by Claude during a maintenance session) from named
sources. The collector does not fetch anything; verification status and evidence come
from the file. The pipeline's re-verification step later checks that the official URL
still resolves and flags it if not.
"""
from __future__ import annotations

import yaml

from .. import config
from ..normalize import canonical_url, empty_booking, parse_when
from . import CollectResult
from .common import base_event, city_tz

BOOKING_KEYS = set(empty_booking())


def collect(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    files = sorted(config.CURATED_DIR.glob("*.yaml"))
    for path in files:
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            res.errors.append(f"{path.name}: YAML error {exc}")
            continue
        default_checked = doc.get("checked_at_default")
        for item in doc.get("events", []):
            try:
                res.events.append(_to_event(item, source, ctx, default_checked, path.name))
            except Exception as exc:  # keep going; report the bad record
                res.errors.append(f"{path.name}:{item.get('id')}: {type(exc).__name__}: {exc}")
    res.notes.append(f"{len(res.events)} researched events from {len(files)} file(s)")
    return res


def _to_event(item: dict, source: dict, ctx, default_checked: str | None, filename: str) -> dict:
    city = item["city"]
    if city not in config.CITIES:
        raise ValueError(f"unknown city {city}")
    evidence = item.get("evidence") or []
    primary = evidence[0] if evidence else {}
    ev = base_event(source, ctx, title=item["title"], url=item.get("official_url") or primary.get("url"), city=city)
    ev["curated_id"] = item["id"]
    ev["reliability"] = min((int(e.get("reliability", 4)) for e in evidence), default=4)
    ev["official"] = ev["reliability"] <= 2
    ev["source_name"] = primary.get("publisher") or source["name"]
    ev["source_url"] = canonical_url(primary.get("url")) or ev["source_url"]
    ev["official_url"] = canonical_url(item.get("official_url"))
    tz = city_tz(city)
    ev["start"], ev["all_day"] = parse_when(item.get("start"), tz)
    ev["end"], _ = parse_when(item.get("end"), tz)
    if item.get("all_day") is True:
        ev["all_day"] = True
    for k in ("neighborhood", "venue_name", "venue_address", "category", "subcategory", "description"):
        ev[k] = item.get(k)
    ev["occurrences"] = [str(o) for o in item.get("occurrences", [])]
    ev["tags"] = list(item.get("tags", []))
    ev["trip_suitable"] = bool(item.get("trip_suitable", False))
    ev["preset_verification"] = item.get("verification_status")
    ev["date_basis"] = item.get("date_basis")
    ev["expected_window"] = item.get("expected_window")
    ev["social_accounts"] = item.get("social_accounts", [])
    checked = item.get("checked_at") or default_checked or ctx.now_iso
    ev["checked_at"] = checked
    ev["curated_file"] = filename
    ev["evidence_list"] = [
        {"url": e.get("url"), "publisher": e.get("publisher"), "reliability": e.get("reliability"),
         "checked_at": e.get("checked_at") or checked, "note": e.get("note")}
        for e in evidence
    ]
    b = empty_booking()
    raw = item.get("booking") or {}
    for k, v in raw.items():
        if k == "inferred":
            b["inferred"] = list(v)
        elif k == "booking_deadline_note":
            b["booking_deadline_note"] = v
        elif k in BOOKING_KEYS:
            b[k] = v
    if b.get("price"):
        b["price"] = dict(b["price"])
        b["price"].setdefault("verified_at", checked)
        if b["price"].get("amount") == 0:
            b["free"] = True
    if b["tickets"] in ("free_entry", "free_registration"):
        b["free"] = True
    b["verified_at"] = checked
    ev["booking"] = b
    return ev
