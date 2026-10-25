"""Stage 3/7 — turn a candidate into a stored event, or merge it into an existing one,
keeping a change history and source references."""
from __future__ import annotations

from copy import deepcopy

from .normalize import canonical_url, slugify, stable_id, title_key

TRACKED_FIELDS = ["start", "end", "venue_name", "venue_address", "event_status", "title"]
TRACKED_BOOKING = ["tickets", "reservation", "registration", "access", "booking_deadline"]


def event_id_for(c: dict) -> str:
    if c.get("curated_id"):
        return "ev-" + c["curated_id"]
    day = (c.get("start") or "")[:10]
    return f"{slugify(c['title'], 40)}-{stable_id(c['city'], title_key(c['title']), day)[:8]}"


def source_ref(c: dict) -> dict:
    return {
        "source_id": c["source_id"],
        "name": c["source_name"],
        "url": c.get("source_url"),
        "reliability": c.get("reliability", 4),
        "official": bool(c.get("official")),
        "published_at": c.get("published_at"),
        "seen_at": c["checked_at"],
    }


def new_record(c: dict, now: str) -> dict:
    rec = {
        "id": event_id_for(c),
        "title": c["title"],
        "description": c.get("description"),
        "city": c["city"],
        "neighborhood": c.get("neighborhood"),
        "venue_name": c.get("venue_name"),
        "venue_address": c.get("venue_address"),
        "category": c.get("category") or "culture",
        "subcategory": c.get("subcategory"),
        "start": c.get("start"),
        "end": c.get("end"),
        "all_day": bool(c.get("all_day")),
        "timezone": c.get("timezone"),
        "occurrences": c.get("occurrences") or [],
        "date_basis": c.get("date_basis"),
        "expected_window": c.get("expected_window"),
        "event_status": c.get("event_status", "scheduled"),
        "source_url": c.get("source_url"),
        "official_url": c.get("official_url"),
        "published_at": c.get("published_at"),
        "first_discovered_at": now,
        "last_updated_at": now,
        "last_seen_at": now,
        "last_verified_at": c["checked_at"] if c.get("official") or c.get("preset_verification") else None,
        "verification_status": None,
        "preset_verification": c.get("preset_verification"),
        "verification_evidence": list(c.get("evidence_list") or []),
        "booking": deepcopy(c["booking"]),
        "sources": [source_ref(c)],
        "social_accounts": list(c.get("social_accounts") or []),
        "tags": list(dict.fromkeys(c.get("tags") or [])),
        "trip_suitable": c.get("trip_suitable"),
        "curated": bool(c.get("curated_id")),
        "history": [],
        "conflicts": [],
        "review_flags": [],
        "related_ids": [],
        "duplicate_of": None,
        "hidden": False,
        "field_sources": {f: c["source_id"] for f in TRACKED_FIELDS + ["description"] if c.get(f) not in (None, "", [])},
    }
    if c.get("official") and not rec["verification_evidence"]:
        rec["verification_evidence"].append({
            "url": c.get("source_url"), "publisher": c["source_name"], "reliability": c.get("reliability"),
            "checked_at": c["checked_at"], "note": "Event published by the organiser/venue (structured data or official feed).",
        })
    for note in rec["booking"].get("evidence", []):
        rec["verification_evidence"].append({"url": c.get("source_url"), "publisher": c["source_name"],
                                             "reliability": c.get("reliability"), "checked_at": c["checked_at"], "note": note})
    return rec


def _log(rec: dict, now: str, field: str, old, new, source: str) -> None:
    rec["history"].append({"at": now, "field": field, "old": old, "new": new, "source": source})
    rec["history"] = rec["history"][-40:]


def merge_into(rec: dict, c: dict, now: str) -> bool:
    """Merge candidate c into stored record. Returns True if anything material changed."""
    changed = False
    rec["last_seen_at"] = now
    # source references
    refs = {r["source_id"]: r for r in rec["sources"]}
    ref = source_ref(c)
    refs[c["source_id"]] = {**refs.get(c["source_id"], {}), **ref}
    rec["sources"] = sorted(refs.values(), key=lambda r: (r["reliability"], r["source_id"]))
    best_rel = rec["sources"][0]["reliability"]
    authoritative = c.get("reliability", 4) <= best_rel
    if c.get("official") or c.get("preset_verification"):
        rec["last_verified_at"] = c["checked_at"]
    if c.get("curated_id"):
        rec["curated"] = True
        rec["preset_verification"] = c.get("preset_verification")
        rec["date_basis"] = c.get("date_basis")
        rec["expected_window"] = c.get("expected_window")
        rec["verification_evidence"] = list(c.get("evidence_list") or []) + [
            e for e in rec["verification_evidence"] if e.get("publisher") not in {x.get("publisher") for x in c.get("evidence_list") or []}
        ]
    # field updates. Each tracked field remembers which source set it ("owner"). A source
    # may correct its own value; a strictly more reliable source overrides; anything else
    # only fills gaps. Credible sources disagreeing on dates are preserved as a conflict.
    owners = rec.setdefault("field_sources", {})
    rel_of = {r["source_id"]: r["reliability"] for r in rec["sources"]}
    my_rel = c.get("reliability", 4)
    for f in TRACKED_FIELDS + ["description", "neighborhood", "category", "subcategory", "official_url", "all_day", "timezone"]:
        new = c.get(f)
        if new in (None, "", []):
            continue
        old = rec.get(f)
        owner = owners.get(f)
        if old in (None, "", []):
            rec[f] = new
            owners[f] = c["source_id"]
            continue
        if old == new:
            continue
        owner_rel = rel_of.get(owner, 4) if owner else best_rel
        may_set = owner == c["source_id"] or my_rel < owner_rel or (owner is None and authoritative)
        if f in ("start", "end") and str(old)[:10] != str(new)[:10] and not may_set and my_rel <= 3:
            conflict = {"field": f, "values": {owner or rec["sources"][0]["source_id"]: old, c["source_id"]: new}, "detected_at": now}
            if not any(x.get("field") == f and x.get("values") == conflict["values"] for x in rec["conflicts"]):
                rec["conflicts"].append(conflict)
                changed = True
            continue
        if may_set:
            if f in TRACKED_FIELDS:
                _log(rec, now, f, old, new, c["source_id"])
                changed = True
            rec[f] = new
            owners[f] = c["source_id"]
    if c.get("occurrences") and (authoritative or not rec.get("occurrences")):
        rec["occurrences"] = c["occurrences"]
    if c.get("trip_suitable") is not None and (authoritative or rec.get("trip_suitable") is None):
        rec["trip_suitable"] = c["trip_suitable"]
    # booking: explicit statements beat unknowns; more reliable sources beat less reliable
    nb, ob = c["booking"], rec["booking"]
    for f, new in nb.items():
        if f in ("evidence", "inferred"):
            merged = list(dict.fromkeys((ob.get(f) or []) + (new or [])))
            ob[f] = merged
            continue
        if new in (None, "unknown", "", []):
            continue
        old = ob.get(f)
        if old == new:
            continue
        if authoritative or old in (None, "unknown", ""):
            if f in TRACKED_BOOKING and old not in (None, "unknown"):
                _log(rec, now, f"booking.{f}", old, new, c["source_id"])
                changed = True
            ob[f] = new
    for t in c.get("tags") or []:
        if t not in rec["tags"]:
            rec["tags"].append(t)
    for acc in c.get("social_accounts") or []:
        if acc not in rec["social_accounts"]:
            rec["social_accounts"].append(acc)
    if changed:
        rec["last_updated_at"] = now
    return changed


def canonical_key(url: str | None) -> str | None:
    return canonical_url(url)
