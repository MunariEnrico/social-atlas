"""Manual URL submissions (data/submissions.yaml, usually appended by the
'Submit a URL' GitHub issue workflow).

A submitted page is fetched once (robots.txt respected). If it carries schema.org Event
data the events enter the database as 'announced — verification pending' (a submission
is never auto-confirmed). Otherwise the URL is preserved as a signal flagged for manual
entry, with whatever title the page declares.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from . import config
from .collectors.common import make_signal
from .collectors.jsonld import _node_to_event
from .extract import clean_text, extract_jsonld_events
from .normalize import canonical_url, detect_cities, is_safe_public_url, stable_id
from .store import load_yaml

SUBMISSION_SOURCE = {"id": "user-submission", "name": "Submitted URL", "type": "submission", "reliability": 3}


def process_submissions(db, ctx) -> tuple[list[dict], list[dict], int]:
    items = load_yaml(config.SUBMISSIONS_FILE, []) or []
    events, signals, n = [], [], 0
    for item in items:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        url = canonical_url(str(item["url"]))
        key = stable_id(str(item["url"]))
        st = db.submissions_state.get(key)
        if st and st.get("status") not in ("retry",):
            continue
        n += 1
        state = {"url": item["url"], "submitted_at": item.get("submitted_at"), "submitted_by": item.get("submitted_by"),
                 "processed_at": ctx.now_iso, "events": [], "status": None, "error": None}
        db.submissions_state[key] = state
        if not url or not is_safe_public_url(url):
            state["status"] = "invalid"
            state["error"] = "not a public http(s) URL"
            continue
        city = item.get("city") if item.get("city") in config.CITIES else None
        r = ctx.fetcher.get(url)
        if not r.ok:
            state["status"] = "failed"
            state["error"] = r.error or f"HTTP {r.status}"
            signals.append(_manual_signal(url, item, city, ctx, title=None, note=f"could not fetch: {state['error']}"))
            continue
        nodes = extract_jsonld_events(r.text or "", r.final_url or url)
        soup = BeautifulSoup(r.text or "", "html.parser")
        og_title = _meta(soup, "og:title") or (soup.title.string if soup.title else None)
        og_desc = _meta(soup, "og:description") or _meta(soup, "description")
        if not city:
            hits = detect_cities(og_title, og_desc, url)
            city = hits[0] if len(hits) == 1 else None
        if nodes and city:
            src = {**SUBMISSION_SOURCE, "city": city, "categories": []}
            known = _registered_reliability(url)
            if known:
                # the page belongs to a registered official source: keep its reliability
                src["reliability"] = known
                src["name"] = "Submitted URL (registered source)"
            for n_ in nodes[:10]:
                ev = _node_to_event(n_, src, ctx, url)
                if ev:
                    ev["tags"].append("submitted")
                    if item.get("note"):
                        ev["tags"].append(clean_text(item["note"], 60))
                    events.append(ev)
                    state["events"].append(ev["title"])
            state["status"] = "extracted"
        else:
            state["status"] = "no_structured_data" if city else "city_unknown"
            signals.append(_manual_signal(url, item, city, ctx, title=og_title, note=clean_text(og_desc, 200)))
    return events, signals, n


def _registered_reliability(url: str) -> int | None:
    from urllib.parse import urlparse

    from .store import load_sources

    host = urlparse(url).netloc.lower().removeprefix("www.")
    rels = [int(s["reliability"]) for s in load_sources()
            if s.get("url") and urlparse(s["url"]).netloc.lower().removeprefix("www.") == host and s.get("type") not in ("search_aggregator", "research")]
    return min(rels) if rels else None


def _meta(soup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return clean_text(tag.get("content")) if tag and tag.get("content") else None


def _manual_signal(url, item, city, ctx, *, title, note):
    sig = make_signal({**SUBMISSION_SOURCE, "categories": [], "keep_all": True, "max_age_days": 3650}, ctx,
                      {"url": url, "title": clean_text(title) or url, "summary": note, "published": item.get("submitted_at")}, city=city)
    sig["signal_type"] = "submission"
    sig["needs_manual_entry"] = True
    return sig
