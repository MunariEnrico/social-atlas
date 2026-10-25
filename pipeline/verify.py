"""Stage 5 — verification status, past-event handling, link re-checks, conflicts."""
from __future__ import annotations

from datetime import datetime, timedelta

from .normalize import end_bound, to_utc

STATUSES = ["confirmed", "announced_pending", "expected", "needs_review", "postponed", "cancelled", "past"]


def assign_status(ev: dict, now: datetime) -> None:
    flags = ev.setdefault("review_flags", [])
    eb = end_bound(ev)
    if ev.get("event_status") == "cancelled":
        ev["verification_status"] = "cancelled"
    elif ev.get("event_status") == "postponed":
        ev["verification_status"] = "postponed"
    elif eb is not None and eb < now:
        ev["verification_status"] = "past"
    elif ev.get("conflicts"):
        ev["verification_status"] = "needs_review"
    elif ev.get("preset_verification"):
        ev["verification_status"] = ev["preset_verification"]
    elif not ev.get("start") and not ev.get("expected_window"):
        ev["verification_status"] = "needs_review"
        if "missing date" not in flags:
            flags.append("missing date")
    else:
        best = min((s.get("reliability", 4) for s in ev.get("sources", [])), default=4)
        official = any(s.get("official") for s in ev.get("sources", []))
        ev["verification_status"] = "confirmed" if official and best <= 2 else "announced_pending"
    # date status mirrors how solid the date is
    vs = ev["verification_status"]
    if not ev.get("start"):
        ev["date_status"] = "unknown" if not ev.get("expected_window") else "tentative"
    elif vs == "expected":
        ev["date_status"] = "tentative"
    elif vs in ("confirmed", "past", "cancelled", "postponed"):
        ev["date_status"] = "confirmed"
    else:
        ev["date_status"] = "announced"
    ev["confidence"] = {"confirmed": "high", "announced_pending": "medium", "past": "high", "cancelled": "high",
                        "postponed": "medium", "expected": "low", "needs_review": "low"}[vs]
    # stale verification: confirmed facts older than 45 days get a soft flag
    lv = to_utc(ev.get("last_verified_at"))
    stale = vs in ("confirmed", "announced_pending") and lv is not None and (now - lv) > timedelta(days=45)
    msg = "verification older than 45 days"
    if stale and msg not in flags:
        flags.append(msg)
    if not stale and msg in flags:
        flags.remove(msg)


def link_check_due(ev: dict, now: datetime, every_days: int = 7) -> bool:
    if ev.get("verification_status") in ("past", "cancelled") or not ev.get("official_url"):
        return False
    lc = ev.get("link_check") or {}
    last = to_utc(lc.get("checked_at"))
    return last is None or (now - last) > timedelta(days=every_days)


def apply_link_check(ev: dict, result, now_iso: str) -> None:
    ev["link_check"] = {"checked_at": now_iso, "status": result.status, "ok": result.ok, "error": result.error}
    flag = "official page unreachable on last check"
    flags = ev.setdefault("review_flags", [])
    if result.ok:
        if flag in flags:
            flags.remove(flag)
    elif result.status in (404, 410):
        if flag not in flags:
            flags.append(flag)
