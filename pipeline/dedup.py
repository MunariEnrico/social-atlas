"""Stage 4 — deterministic de-duplication.

A candidate merges into an existing event only when all of these hold:
  * same city
  * date ranges overlap (or same start date for single-day events)
  * title similarity >= MERGE_THRESHOLD
  * venues do not clearly disagree
Pairs between REVIEW_THRESHOLD and MERGE_THRESHOLD stay separate and are flagged for
review. Sharing a venue or organiser alone never merges two events.
"""
from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher

from .normalize import local_date, title_key

MERGE_THRESHOLD = 0.86
REVIEW_THRESHOLD = 0.66


def similarity(a: str, b: str) -> float:
    ka, kb = title_key(a), title_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    seq = SequenceMatcher(None, ka, kb).ratio()
    token_sort = SequenceMatcher(None, " ".join(sorted(ka.split())), " ".join(sorted(kb.split()))).ratio()
    seq = max(seq, token_sort * 0.97)
    ta, tb = set(ka.split()), set(kb.split())
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    # containment counts only when the shorter title covers most of the longer one
    # ("Paris Photo" vs "Paris Photo Grand Palais" yes; "Art Week" vs "Art Week — Opening
    # Night, The Live Hearth" no: that is a sub-event, not the same listing)
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    contain = 0.0
    if short and short <= long_:
        # full coverage-ish: same listing; partial ("Fintech Recruits" inside "Fintech Recruits
        # 5 Years Anniversary"): flag for review rather than merge
        contain = 0.9 if len(short) / len(long_) >= 0.75 else (0.7 if len(short) >= 2 else 0.0)
    return max(seq, (seq + jac) / 2, contain)


def _range(ev: dict) -> tuple[date, date] | None:
    tz = ev.get("timezone") or "UTC"
    s = local_date(ev.get("start"), tz)
    if s is None:
        return None
    e = local_date(ev.get("end"), tz) or s
    return (s, max(s, e))


def dates_overlap(a: dict, b: dict) -> bool:
    ra, rb = _range(a), _range(b)
    if ra is None or rb is None:
        # undated items (expected editions) only match on near-identical titles; caller checks
        return ra is None and rb is None
    return ra[0] <= rb[1] and rb[0] <= ra[1]


def venues_disagree(a: dict, b: dict) -> bool:
    va, vb = (a.get("venue_name") or "").strip(), (b.get("venue_name") or "").strip()
    if not va or not vb:
        return False
    return SequenceMatcher(None, title_key(va), title_key(vb)).ratio() < 0.45 and title_key(va) not in title_key(vb) and title_key(vb) not in title_key(va)


def find_match(candidate: dict, pool: list[dict]) -> tuple[dict | None, list[tuple[str, float]]]:
    """Return (event to merge into, [(possible_duplicate_id, score)])."""
    best, best_score = None, 0.0
    maybes: list[tuple[str, float]] = []
    for ev in pool:
        if ev.get("city") != candidate.get("city"):
            continue
        if not dates_overlap(candidate, ev):
            continue
        s = similarity(candidate.get("title", ""), ev.get("title", ""))
        if s < REVIEW_THRESHOLD:
            continue
        # a single date inside a multi-day run is usually a sub-event (opening night, talk)
        ra, rb = _range(candidate), _range(ev)
        if ra and rb and ra[0] != rb[0] and ra[1] != rb[1] and s < 0.95:
            maybes.append((ev["id"], round(s, 2)))
            continue
        if venues_disagree(candidate, ev):
            maybes.append((ev["id"], round(s, 2)))
            continue
        # long-running exhibitions overlap with everything at the same venue: require stronger titles
        if s >= MERGE_THRESHOLD and s > best_score:
            best, best_score = ev, s
        elif s < MERGE_THRESHOLD:
            maybes.append((ev["id"], round(s, 2)))
    return best, maybes
