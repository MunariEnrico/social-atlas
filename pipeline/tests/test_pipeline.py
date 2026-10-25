"""Offline tests for the SOCIAL ATLAS pipeline. Run: python -m pytest pipeline/tests -q"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pipeline import config
from pipeline.collectors import Context
from pipeline.collectors import jsonld as jsonld_mod
from pipeline.collectors import rss as rss_mod
from pipeline.dedup import find_match, similarity
from pipeline.extract import detect_date_mentions, extract_jsonld_events
from pipeline.http import FetchResult
from pipeline.merge import merge_into, new_record
from pipeline.normalize import (booking_from_offers, booking_from_text, canonical_url, empty_booking, end_bound,
                                is_safe_public_url, parse_when, primary_action)
from pipeline.score import radar_buckets, score_event, urgency
from pipeline.verify import assign_status

NOW = datetime(2026, 10, 25, 14, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"MusicEvent","name":"Night Concert","startDate":"2026-11-03T20:00","endDate":"2026-11-03T22:00",
  "location":{"@type":"Place","name":"Philharmonie","address":{"@type":"PostalAddress","streetAddress":"1 Place de l'Europe","postalCode":"L-1499","addressLocality":"Luxembourg"}},
  "offers":{"@type":"Offer","price":"35","priceCurrency":"EUR","availability":"https://schema.org/InStock","url":"https://tickets.example/1"},
  "eventStatus":"https://schema.org/EventScheduled"},
 {"@type":"Event","name":"Market","startDate":"2026-11-20","endDate":"2026-11-20","url":"https://ex.lu/market"},
 {"@type":"Event","name":"Market","startDate":"2026-11-21","endDate":"2026-11-21","url":"https://ex.lu/market"},
 {"@type":"Event","name":"Cancelled Talk","startDate":"2026-11-05T18:00:00+01:00","eventStatus":"EventCancelled"},
 {"@type":"Organization","name":"Not an event"}
]}</script></head><body></body></html>"""

RSS_EVENTS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Agenda</title>
<item><title>Workshop</title><link>https://www.vdl.lu/fr/agenda/workshop</link>
<description><![CDATA[<p>Creative workshop.</p><p><strong>FULLY BOOKED - no more spots available</strong></p>]]></description>
<pubDate>Tue, 27 Oct 2026 10:00:00 +0100</pubDate></item>
<item><title>Corrupt date</title><link>https://www.vdl.lu/fr/agenda/x</link><pubDate>Sat, 29 Nov 0206 16:50:39 +0017</pubDate></item>
<item><title>Long-running show</title><link>https://www.vdl.lu/fr/agenda/old</link><pubDate>Thu, 10 Sep 2026 22:00:00 +0200</pubDate></item>
<item><title>Exhibition day</title><link>https://www.vdl.lu/fr/agenda/expo</link><pubDate>Fri, 30 Oct 2026 00:00:00 +0100</pubDate></item>
</channel></rss>"""


class FakeFetcher:
    def __init__(self, pages: dict[str, str | None]):
        self.pages = pages
        self.request_count = 0

    def get(self, url, params=None, accept_json=False):
        self.request_count += 1
        body = self.pages.get(url)
        if body is None:
            return FetchResult(url=url, status=503, error="HTTP 503", attempts=3)
        return FetchResult(url=url, status=200, text=body, content_type="text/html", final_url=url, attempts=1)


def ctx_with(pages):
    return Context(fetcher=FakeFetcher(pages), now_iso=NOW_ISO, today="2026-10-25")


LU_SOURCE = {"id": "t-lu", "name": "Test LU", "city": "luxembourg", "type": "official_venue", "reliability": 1,
             "url": "https://ex.lu/agenda", "method": "jsonld_page"}


# ------------------------------------------------------------------ extraction
def test_jsonld_extraction_groups_occurrences_and_reads_offers():
    res = jsonld_mod.collect_page(LU_SOURCE, ctx_with({"https://ex.lu/agenda": JSONLD_PAGE}))
    by = {e["title"]: e for e in res.events}
    assert set(by) == {"Night Concert", "Market", "Cancelled Talk"}
    concert = by["Night Concert"]
    assert concert["start"] == "2026-11-03T20:00:00+01:00"  # naive time localised to Luxembourg (CET)
    assert concert["booking"]["tickets"] == "available_verified"
    assert concert["booking"]["price"]["display"] == "€35"
    assert concert["booking"]["ticket_url"] == "https://tickets.example/1"
    assert concert["venue_address"].startswith("1 Place de l'Europe")
    market = by["Market"]
    assert market["all_day"] and market["start"] == "2026-11-20" and market["end"] == "2026-11-21"
    assert market["occurrences"] == ["2026-11-20", "2026-11-21"]
    assert by["Cancelled Talk"]["event_status"] == "cancelled"


def test_rss_events_sold_out_bad_dates_and_started_items():
    src = {"id": "lu-vdl-agenda", "name": "VdL", "city": "luxembourg", "type": "official_institution", "reliability": 1,
           "feed": "https://feed", "method": "rss_events"}
    res = rss_mod.collect_events(src, ctx_with({"https://feed": RSS_EVENTS}))
    titles = [e["title"] for e in res.events]
    assert titles == ["Workshop", "Exhibition day"]
    ws = res.events[0]
    assert ws["start"] == "2026-10-27T10:00:00+01:00"
    assert ws["booking"]["tickets"] == "sold_out_verified"
    assert res.events[1]["all_day"] and res.events[1]["start"] == "2026-10-30"
    assert any("invalid date" in n for n in res.notes)
    assert any("already started" in n for n in res.notes)


def test_failed_fetch_is_recorded_not_hidden():
    res = jsonld_mod.collect_page(LU_SOURCE, ctx_with({}))
    assert res.events == [] and res.errors and res.fetches[0]["ok"] is False


def test_date_mentions_are_conservative():
    from datetime import date
    assert detect_date_mentions("Opening on 12 November", date(2026, 10, 25)) == ["2026-11-12"]
    assert detect_date_mentions("dal 3 dicembre", date(2026, 10, 25)) == ["2026-12-03"]
    assert detect_date_mentions("we may go", date(2026, 10, 25)) == []
    # a date a few weeks ago stays in the past (recap articles), not next year
    assert detect_date_mentions("on 1 October", date(2026, 10, 25)) == ["2026-10-01"]


# ------------------------------------------------------------------ normalisation
def test_parse_when_and_timezones():
    assert parse_when("2026-11-20", "Europe/Paris") == ("2026-11-20", True)
    assert parse_when("2026-11-20T19:00", "America/New_York")[0] == "2026-11-20T19:00:00-05:00"
    assert parse_when("2026-07-01T19:00", "Europe/London")[0] == "2026-07-01T19:00:00+01:00"  # BST
    assert parse_when("0206-11-29T16:50:39", "Europe/Paris") == (None, False)


def test_end_bound_for_date_only_events_is_end_of_local_day():
    ev = {"city": "nyc", "start": "2026-11-01", "end": None}
    eb = end_bound(ev)
    assert eb.isoformat() == "2026-11-02T04:59:59+00:00"


def test_url_canonicalisation_and_safety():
    assert canonical_url("https://Example.com/a?utm_source=x&id=3") == "https://example.com/a?id=3"
    bing = "http://www.bing.com/news/apiclick.aspx?ref=FexRss&url=https%3a%2f%2fwww.ilgazzettino.it%2fx.html%3futm_medium%3drss"
    assert canonical_url(bing) == "https://www.ilgazzettino.it/x.html"
    assert not is_safe_public_url("http://127.0.0.1/admin")
    assert not is_safe_public_url("file:///etc/passwd")
    assert not is_safe_public_url("https://user:pw@example.com/")
    assert is_safe_public_url("https://www.mudam.com/events/opening")


def test_booking_free_does_not_imply_walk_in():
    b = booking_from_text(empty_booking(), "Entrée libre", official=True, checked_at=NOW_ISO, source_url=None)
    assert b["free"] is True and b["tickets"] == "free_entry"
    assert b["reservation"] == "unknown" and b["registration"] == "unknown"
    assert "not stated" in b["access_notes"]


def test_sold_out_from_unofficial_text_is_not_trusted():
    b = booking_from_text(empty_booking(), "Sold out!", official=False, checked_at=NOW_ISO, source_url=None)
    assert b["tickets"] == "unknown"


def test_offers_without_availability_do_not_claim_availability():
    b = booking_from_offers(empty_booking(), [{"price": "12", "priceCurrency": "GBP"}], None, official=True,
                            checked_at=NOW_ISO, currency_default="GBP", source_url=None)
    assert b["tickets"] == "ticketed" and b["price"]["display"] == "£12"


# ------------------------------------------------------------------ dedup / merge / verify
def _cand(title, start, src="s1", rel=1, venue=None, city="paris"):
    return {"kind": "event", "source_id": src, "source_name": src, "reliability": rel, "official": rel <= 2,
            "title": title, "city": city, "start": start, "end": None, "all_day": len(start) == 10, "timezone": "Europe/Paris",
            "venue_name": venue, "booking": empty_booking(), "checked_at": NOW_ISO, "source_url": f"https://{src}/x",
            "tags": [], "occurrences": []}


def test_dedup_merges_same_event_from_two_sources():
    a = new_record(_cand("Paris Photo 2026", "2026-11-12", "official"), NOW_ISO)
    match, maybes = find_match(_cand("Paris Photo", "2026-11-12", "press", rel=3), [a])
    assert match is a
    merge_into(a, _cand("Paris Photo", "2026-11-12", "press", rel=3), NOW_ISO)
    assert [s["source_id"] for s in a["sources"]] == ["official", "press"]
    assert a["title"] == "Paris Photo 2026"  # official source keeps precedence


def test_dedup_does_not_merge_different_events_at_same_venue():
    a = new_record(_cand("Jazz Night with Trio A", "2026-11-12T20:00:00+01:00", venue="Le Duc"), NOW_ISO)
    match, _ = find_match(_cand("Poetry Evening", "2026-11-12T20:00:00+01:00", "s2", venue="Le Duc"), [a])
    assert match is None


def test_dedup_flags_ambiguous_pairs_for_review():
    a = new_record(_cand("Design Market Winter Edition", "2026-12-05"), NOW_ISO)
    match, maybes = find_match(_cand("Winter Design Market Night", "2026-12-05", "s2"), [a])
    assert match is None and maybes


def test_conflicting_dates_go_to_review():
    a = new_record(_cand("Salon X", "2026-11-12", "press1", rel=3), NOW_ISO)
    merge_into(a, _cand("Salon X", "2026-11-13", "press2", rel=3), NOW_ISO)
    assign_status(a, NOW)
    assert a["verification_status"] == "needs_review" and a["conflicts"]


def test_status_rules_past_official_and_expected():
    past = new_record(_cand("Old", "2026-10-01"), NOW_ISO)
    assign_status(past, NOW)
    assert past["verification_status"] == "past"
    off = new_record(_cand("Official", "2026-11-01"), NOW_ISO)
    assign_status(off, NOW)
    assert off["verification_status"] == "confirmed"
    press = new_record(_cand("Press", "2026-11-01", rel=3), NOW_ISO)
    assign_status(press, NOW)
    assert press["verification_status"] == "announced_pending"
    exp = new_record({**_cand("Carnival 2027", "2027-02-09"), "preset_verification": "expected"}, NOW_ISO)
    assign_status(exp, NOW)
    assert exp["verification_status"] == "expected" and exp["date_status"] == "tentative"


def test_history_is_kept_when_official_date_changes():
    a = new_record(_cand("Gala", "2026-11-12T19:00:00+01:00"), NOW_ISO)
    merge_into(a, _cand("Gala", "2026-11-14T19:00:00+01:00"), "2026-10-26T06:00:00+00:00")
    assert a["start"].startswith("2026-11-14")
    assert a["history"][-1]["field"] == "start"


# ------------------------------------------------------------------ scoring
def test_urgency_and_radar():
    ev = new_record(_cand("Pop-up dinner", "2026-10-26T20:00:00+01:00"), NOW_ISO)
    ev["booking"]["reservation"] = "required"
    assign_status(ev, NOW)
    score_event(ev, NOW, coverage=1)
    assert ev["urgency"] == "act_now"
    assert "last_minute" in radar_buckets(ev, NOW, 1)
    assert "just_discovered" in radar_buckets(ev, NOW, 1)
    assert ev["scores"]["insider"] >= 45  # new + single source + niche format
    # a long-running show with weeks left is not urgent
    run = new_record({**_cand("Biennale", "2026-05-09", rel=1), "end": "2026-11-22"}, NOW_ISO)
    run["booking"]["tickets"] = "ticketed"
    assign_status(run, NOW)
    score_event(run, NOW, coverage=1)
    assert run["urgency"] == "monitor"
    closing = new_record({**_cand("Show", "2026-09-01", rel=1), "end": "2026-10-30"}, NOW_ISO)
    assign_status(closing, NOW)
    score_event(closing, NOW, coverage=1)
    assert closing["urgency"] == "last_chance" and closing["closing_soon"]


def test_sub_event_does_not_merge_into_umbrella_event():
    umbrella = new_record({**_cand("Luxembourg Art Week 2026", "2026-11-20", city="luxembourg"), "end": "2026-11-22"}, NOW_ISO)
    sub = _cand("Luxembourg Art Week 2026 - Opening Night - The Live Hearth Signal Room", "2026-11-20", "casino", city="luxembourg")
    match, _ = find_match(sub, [umbrella])
    assert match is None


def test_primary_action_prefers_registration_and_never_invents():
    ev = new_record(_cand("Talk", "2026-11-02"), NOW_ISO)
    ev["source_url"] = None
    assert primary_action(ev) is None
    ev["booking"]["registration"] = "required"
    ev["booking"]["registration_url"] = "https://reg"
    assert primary_action(ev)["label"] == "Register"


def test_sources_registry_is_valid():
    from pipeline.store import load_sources
    from pipeline.collectors import get_collector
    sources = load_sources()
    assert len({s["id"] for s in sources}) == len(sources)
    for s in sources:
        assert s["city"] in list(config.CITIES) + ["multi"], s["id"]
        assert s["method"] == "manual" or get_collector(s["method"]), s["id"]
        assert 1 <= int(s["reliability"]) <= 4
        if s["method"] == "manual":
            assert s.get("reason"), f"{s['id']}: manual sources must say why"


def test_curated_file_is_valid():
    from pipeline.collectors.curated import collect
    res = collect({"id": "curated-research", "name": "x", "city": "multi", "reliability": 2}, ctx_with({}))
    assert not res.errors, res.errors
    for e in res.events:
        assert e["evidence_list"], e["title"]
        assert e["preset_verification"] in ("confirmed", "announced_pending", "expected")
        if e["preset_verification"] == "confirmed":
            assert any((x.get("reliability") or 4) <= 2 for x in e["evidence_list"]), e["title"]


def test_submissions_extract_or_preserve(tmp_path, monkeypatch):
    from pipeline import submit
    sub = tmp_path / "submissions.yaml"
    sub.write_text("- url: https://ex.lu/agenda\n  city: luxembourg\n- url: https://ex.lu/plain\n  city: luxembourg\n- url: http://127.0.0.1/x\n")
    monkeypatch.setattr(config, "SUBMISSIONS_FILE", sub)

    class DB:
        submissions_state = {}
    pages = {"https://ex.lu/agenda": JSONLD_PAGE, "https://ex.lu/plain": "<html><head><meta property='og:title' content='A pop-up bar'></head></html>"}
    events, signals, n = submit.process_submissions(DB, ctx_with(pages))
    assert n == 3
    assert {e["title"] for e in events} >= {"Night Concert"}
    assert all(e["source_id"] == "user-submission" and not e["official"] for e in events)
    assert signals and signals[0]["needs_manual_entry"] and signals[0]["title"] == "A pop-up bar"
    states = sorted(s["status"] for s in DB.submissions_state.values())
    assert states == ["extracted", "invalid", "no_structured_data"]
    # processed submissions are not processed twice
    _, _, n2 = submit.process_submissions(DB, ctx_with(pages))
    assert n2 == 0


def test_signal_filters_drop_stale_and_offtopic():
    from pipeline.collectors.common import make_signal
    src = {"id": "x", "name": "X", "reliability": 3}
    c = ctx_with({})
    assert make_signal(src, c, {"url": "https://a/1", "title": "New cocktail bar opens in Venice", "published": "2026-10-20T10:00:00+00:00"}, city="venice")
    assert make_signal(src, c, {"url": "https://a/2", "title": "New cocktail bar opens", "published": "2025-01-20T10:00:00+00:00"}, city="venice") is None
    assert make_signal(src, c, {"url": "https://a/3", "title": "Inaugurato il nuovo asilo nido comunale", "published": "2026-10-20T10:00:00+00:00"}, city="venice") is None


def test_ticketing_platform_keeps_only_local_venues():
    page = """<script type="application/ld+json">[
      {"@type":"Event","name":"Wine Fest","startDate":"2026-11-21","url":"https://eb/1","location":{"@type":"Place","name":"Harborside Atrium","address":{"@type":"PostalAddress","addressLocality":"Jersey City"}}},
      {"@type":"Event","name":"Reissue Party","startDate":"2026-11-02","url":"https://eb/2","location":{"@type":"Place","name":"Meatpacking Collective","address":{"@type":"PostalAddress","addressLocality":"New York"}}}]</script>"""
    src = {"id": "ny-eb", "name": "EB", "city": "nyc", "type": "ticketing_platform", "reliability": 2, "url": "https://eb/list",
           "method": "jsonld_page", "booking_platform": True, "require_locality": ["new york", "brooklyn"]}
    res = jsonld_mod.collect_page(src, ctx_with({"https://eb/list": page}))
    assert [e["title"] for e in res.events] == ["Reissue Party"]
    ev = res.events[0]
    assert ev["booking"]["ticket_url"] == "https://eb/2" and ev["booking"]["tickets"] == "unknown"
    assert "_locality_text" not in ev
