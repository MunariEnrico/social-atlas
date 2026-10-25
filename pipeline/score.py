"""Stage 6 — transparent, rule-based scoring. Every point comes with a reason string.

Insider Score is a heuristic about *our own coverage* (how early and how narrowly the
monitored sources have seen something). It is not a measure of popularity or exclusivity.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import config
from .normalize import contains_any, end_bound, to_utc

DISTINCT_TAGS = ["opening", "premiere", "pop-up", "popup", "one night", "limited", "residency", "fair", "fashion week", "biennale",
                 "festival", "season opening", "world cup", "grand slam", "vernissage", "launch", "debut", "gala", "closing soon"]
NICHE_WORDS = ["pop-up", "popup", "éphémère", "residency", "guest chef", "supper club", "listening bar", "one night", "limited",
               "independent", "emerging", "showroom", "private view", "vernissage", "takeover", "speakeasy", "apre", "ouvre", "opens", "opening"]

DEFAULT_PREFS = {"categories": {"art": 1.0, "food": 1.0, "nightlife": 0.9, "culture": 0.9, "fashion": 1.0, "business": 1.0,
                                "sports": 0.9, "seasonal": 0.8, "design": 1.0}}


def _days_until(ev: dict, now: datetime) -> float | None:
    s = to_utc(ev.get("start"))
    return None if s is None else (s - now).total_seconds() / 86400


def score_event(ev: dict, now: datetime, coverage: int, prefs: dict | None = None) -> None:
    prefs = prefs or DEFAULT_PREFS
    text = " ".join([ev.get("title") or "", ev.get("description") or "", " ".join(ev.get("tags") or []), ev.get("subcategory") or ""])
    b = ev["booking"]
    days = _days_until(ev, now)
    eb = end_bound(ev)
    upcoming = eb is None or eb >= now
    best_rel = min((s.get("reliability", 4) for s in ev.get("sources", [])), default=4)

    # ---------------- relevance
    rel, why = 30, []
    w = prefs["categories"].get(ev.get("category"), 0.8)
    if w != 1.0:
        rel = int(rel * w)
    cred = {1: 20, 2: 15, 3: 10, 4: 3}.get(best_rel, 0)
    rel += cred
    why.append({1: "official source", 2: "organiser/partner source", 3: "reputable publication", 4: "aggregator lead"}.get(best_rel, "source"))
    hit = contains_any(text, DISTINCT_TAGS)
    if hit:
        rel += 12
        why.append(f"distinctive: {hit}")
    if ev.get("trip_suitable"):
        rel += 8
        why.append("worth a trip")
    if days is not None:
        if -1 <= days <= 14:
            rel += 10
            why.append("happening within two weeks")
        elif days <= 60:
            rel += 5
    elif ev.get("start") and ev.get("end") and upcoming:
        rel += 5
    if ev.get("venue_name"):
        rel += 4
    if len(ev.get("sources", [])) >= 2:
        rel += 6
        why.append(f"seen in {len(ev['sources'])} sources")
    if ev.get("occurrences") and len(ev["occurrences"]) > 20:
        rel -= 8  # recurring guided tours etc. are rarely distinctive
    if ev.get("verification_status") in ("needs_review",):
        rel -= 10
    rel = max(0, min(100, rel))

    # ---------------- insider (heuristic)
    ins, iwhy = 0, []
    first = to_utc(ev.get("first_discovered_at"))
    if first and now - first <= timedelta(days=3):
        ins += 25
        iwhy.append("discovered in the last 3 days")
    elif first and now - first <= timedelta(days=10):
        ins += 12
        iwhy.append("discovered this week")
    if coverage <= 1:
        ins += 20
        iwhy.append("limited coverage detected (1 monitored source)")
    elif coverage == 2:
        ins += 8
    nh = contains_any(text, NICHE_WORDS)
    if nh:
        ins += 25
        iwhy.append(f"niche/limited format: {nh}")
    if ev.get("sources") and ev["sources"][0].get("reliability") in (1, 3) and any(s.get("source_id", "").startswith(("lu-", "ve-", "co-", "pa-", "ny-", "lo-")) for s in ev["sources"]):
        ins += 5
    if first and days is not None and days >= 21 and (now - first) <= timedelta(days=10):
        ins += 15
        iwhy.append("announced well ahead")
    if ev.get("curated"):
        ins = min(ins, 30)  # researched marquee events are by definition widely known
    ins = max(0, min(100, ins))

    # ---------------- actionability
    act, awhy = 0, []
    if ev.get("date_status") == "confirmed":
        act += 25
    elif ev.get("date_status") == "announced":
        act += 12
    else:
        awhy.append("date not confirmed")
    if any(b.get(k) for k in ("ticket_url", "reservation_url", "registration_url")):
        act += 20
    else:
        awhy.append("no booking link")
    if b.get("booking_deadline") or b.get("ticket_release"):
        act += 10
    if b.get("access") != "unknown":
        act += 15
    else:
        awhy.append("access unverified")
    if b.get("tickets") != "unknown":
        act += 10
    if b.get("price"):
        act += 10
    if upcoming:
        act += 10
    act = max(0, min(100, act))

    ev["scores"] = {"relevance": rel, "insider": ins, "actionability": act,
                    "reasons": {"relevance": why, "insider": iwhy, "actionability_gaps": awhy}}
    ev["urgency"] = urgency(ev, now, days, upcoming)
    ev["closing_soon"] = bool(days is not None and days < -0.5 and eb is not None and timedelta(0) <= eb - now <= timedelta(days=14))


def urgency(ev: dict, now: datetime, days: float | None, upcoming: bool) -> str:
    b = ev["booking"]
    if not upcoming or ev.get("verification_status") in ("past", "cancelled"):
        return "none"
    if ev.get("verification_status") in ("expected", "needs_review") or not ev.get("start"):
        return "information_pending"
    needs_booking = b.get("reservation") in ("required", "recommended") or b.get("registration") == "required" or \
        b.get("tickets") in ("ticketed", "available_verified", "paid_reservation", "free_registration")
    deadline = to_utc(b.get("booking_deadline"))
    if deadline and timedelta(0) <= deadline - now <= timedelta(days=7):
        return "act_now"
    if b.get("tickets") == "sold_out_verified":
        return "monitor"
    if days is not None and days < -0.5:
        # already running: what matters is how long is left
        eb = end_bound(ev)
        left = (eb - now).total_seconds() / 86400 if eb else None
        if left is not None and left <= 10:
            return "last_chance"
        return "monitor"
    if days is not None and days <= 3 and needs_booking:
        return "act_now"
    if days is not None and days <= 21 and needs_booking:
        return "book_soon"
    if days is not None and days > 21 and (ev.get("trip_suitable") or needs_booking):
        return "plan_ahead"
    if b.get("access") == "unknown" and b.get("tickets") == "unknown":
        return "information_pending"
    return "monitor"


def radar_buckets(ev: dict, now: datetime, coverage: int) -> list[str]:
    out = []
    if ev.get("hidden") or ev.get("verification_status") in ("past", "cancelled"):
        return out
    first = to_utc(ev.get("first_discovered_at"))
    days = _days_until(ev, now)
    eb = end_bound(ev)
    if first and now - first <= timedelta(days=3) and not ev.get("curated"):
        out.append("just_discovered")
    if ev["scores"]["insider"] >= 45 and coverage <= 1 and not ev.get("curated"):
        out.append("before_everyone_knows")
    starting_soon = days is not None and -0.5 <= days <= 3
    final_days = days is not None and days < -0.5 and eb is not None and timedelta(0) <= eb - now <= timedelta(days=7)
    if (starting_soon or final_days) and ev["booking"].get("tickets") != "sold_out_verified":
        out.append("last_minute")
    if ev.get("trip_suitable") and (days is None or days > 14):
        out.append("worth_planning")
    return out
