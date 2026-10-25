"""Collectors turn one configured source into candidate events and/or signals.

Each collector exposes `collect(source: dict, ctx: Context) -> CollectResult`.
Collectors must never invent fields: anything not present in the source stays None.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..http import Fetcher


@dataclass
class Context:
    fetcher: Fetcher
    now_iso: str
    today: str  # YYYY-MM-DD (UTC)


@dataclass
class CollectResult:
    events: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)
    fetches: list[dict] = field(default_factory=list)  # per-request log lines
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def log_fetch(self, res) -> None:
        self.fetches.append({
            "url": res.url, "status": res.status, "ok": res.ok, "error": res.error,
            "attempts": res.attempts, "ms": res.elapsed_ms,
        })
        if not res.ok:
            self.errors.append(f"{res.url}: {res.error or res.status}")


def get_collector(method: str):
    from . import bing_news, curated, ical, jsonld, paris_opendata, rss, tribe

    return {
        "jsonld_detail": jsonld.collect_detail,
        "jsonld_page": jsonld.collect_page,
        "rss_events": rss.collect_events,
        "rss_news": rss.collect_news,
        "bing_news": bing_news.collect,
        "tribe_api": tribe.collect,
        "paris_opendata": paris_opendata.collect,
        "ical": ical.collect,
        "curated": curated.collect,
    }.get(method)
