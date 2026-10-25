"""Ville de Paris open data — 'Que faire à Paris ?' (opendata.paris.fr, Explore API v2.1).

The dataset is published by the City under the Open Database Licence. Two queries per
run: the most recently updated upcoming records (discovery) and the next to start.
Times: the API labels date_start with +00:00 but the values are Paris wall-clock times
(cross-checked against `occurrences`), so we read the wall-clock time and localise it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..extract import clean_text
from ..normalize import canonical_url, classify_category
from . import CollectResult
from .common import apply_text_booking, base_event

PARIS = ZoneInfo("Europe/Paris")
TAG_TO_CAT = {
    "expo": "art", "art contemporain": "art", "photographie": "art", "street-art": "art", "design": "design",
    "mode": "fashion", "gastronomie": "food", "concert": "culture", "musique": "culture", "festival": "culture",
    "danse": "culture", "théâtre": "culture", "cinéma": "culture", "littérature": "culture", "conférence": "business",
    "innovation": "business", "salon": "business", "histoire": "culture", "nature": "seasonal",
}


def _wall(value: str | None) -> str | None:
    if not value:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(:\d{2})?", value)
    if not m:
        return None
    dt = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:00").replace(tzinfo=PARIS)
    return dt.isoformat()


def collect(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    queries = [
        {"limit": 100, "order_by": "updated_at desc", "where": "date_end >= now()"},
        {"limit": 100, "order_by": "date_start", "where": "date_start >= now()"},
    ]
    seen: set[str] = set()
    allow = [t.lower() for t in source.get("tag_allowlist", [])]
    kept = filtered = 0
    for q in queries:
        r = ctx.fetcher.get(source["api"] + "?" + urlencode(q), accept_json=True)
        res.log_fetch(r)
        if not r.ok:
            continue
        try:
            rows = json.loads(r.text or "{}").get("results", [])
        except json.JSONDecodeError:
            res.errors.append("API did not return JSON")
            continue
        for row in rows:
            rid = str(row.get("id"))
            if rid in seen:
                continue
            seen.add(rid)
            tags = [t.strip() for t in (row.get("qfap_tags") or "").split(";") if t.strip()]
            if allow and not any(t.lower() in allow for t in tags):
                filtered += 1
                continue
            ev = base_event(source, ctx, title=row.get("title"), url=row.get("url"), city="paris")
            ev["start"] = _wall(row.get("date_start"))
            ev["end"] = _wall(row.get("date_end"))
            if not ev["start"]:
                continue
            occ = []
            for chunk in (row.get("occurrences") or "").split(";"):
                s = _wall(chunk.split("_")[0]) if chunk else None
                if s and s[:10] >= ctx.today:
                    occ.append(s)
            ev["occurrences"] = occ[:20]
            ev["description"] = clean_text(row.get("lead_text"), 280)
            ev["venue_name"] = clean_text(row.get("address_name"))
            addr = [row.get("address_street"), row.get("address_zipcode"), row.get("address_city")]
            ev["venue_address"] = clean_text(", ".join(a for a in addr if a)) or clean_text(row.get("address_text"))
            z = str(row.get("address_zipcode") or "")
            if re.fullmatch(r"750\d\d", z):
                n = int(z[-2:])
                ev["neighborhood"] = f"{n}{'er' if n == 1 else 'e'} arrondissement"
            cat_hint = [TAG_TO_CAT[t.lower()] for t in tags if t.lower() in TAG_TO_CAT]
            ev["category"] = cat_hint[0] if cat_hint else classify_category(ev["title"], ev["description"])
            ev["tags"] = tags[:6]
            b = ev["booking"]
            ptype = (row.get("price_type") or "").lower()
            pdetail = clean_text(row.get("price_detail"), 120)
            if ptype.startswith("gratuit"):
                b["free"] = True
                b["price"] = {"amount": 0, "currency": "EUR", "display": "Free" + (" (conditions apply)" if "condition" in ptype else ""),
                              "source_url": ev["source_url"], "verified_at": ctx.now_iso}
            elif ptype == "payant":
                b["free"] = False
                b["price"] = {"amount": None, "currency": "EUR", "display": pdetail or "Paid — price not published",
                              "source_url": ev["source_url"], "verified_at": ctx.now_iso}
            access = (row.get("access_type") or "").lower()
            link = canonical_url(row.get("access_link"))
            if access == "obligatoire":
                b["reservation"] = "required"
                b["evidence"].append("Ville de Paris listing: réservation obligatoire")
            elif access in ("conseillée", "conseillee", "recommandée", "recommandee"):
                b["reservation"] = "recommended"
                b["evidence"].append("Ville de Paris listing: réservation conseillée")
            elif access == "non":
                b["reservation"] = "not_required"
                b["evidence"].append("Ville de Paris listing: pas de réservation")
            if link:
                if b["free"]:
                    b["registration_url"] = link
                    if b["reservation"] == "required":
                        b["tickets"] = "free_registration"
                else:
                    b["ticket_url"] = link
                    b["tickets"] = "ticketed" if b["free"] is False else b["tickets"]
            if b["free"] and b["tickets"] == "unknown" and b["reservation"] == "not_required":
                b["tickets"] = "free_entry"
            if b["access"] == "unknown" and row.get("audience"):
                b["access_notes"] = clean_text(row.get("audience"), 120)
            apply_text_booking(ev, pdetail)
            res.events.append(ev)
            kept += 1
            if kept >= int(source.get("max_items", 120)):
                break
    res.notes.append(f"kept {kept} records; {filtered} outside the tag allowlist")
    return res
