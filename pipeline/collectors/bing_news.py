"""Bing News RSS search (public RSS output, permitted by bing.com/robots.txt when this was
written). Results are signals only. Links are unwrapped from Bing's redirect.

Bing's RSS endpoint handles plain phrases far better than boolean syntax, so a source
lists several short `queries` instead of one complex query.
"""
from __future__ import annotations

from urllib.parse import urlencode

from ..extract import parse_feed
from . import CollectResult
from .common import make_signal, passes_keywords, resolve_city

LANG = {"it": ("it-IT", "it"), "fr": ("fr-FR", "fr"), "en": ("en-GB", "en"), "de": ("de-DE", "de"), "en-us": ("en-US", "en")}


def collect(source: dict, ctx) -> CollectResult:
    res = CollectResult()
    mkt, setlang = LANG.get(source.get("lang", "en"), ("en-GB", "en"))
    queries = source.get("queries") or [source["query"]]
    seen: set[str] = set()
    per_query = int(source.get("max_items", 20))
    for q in queries:
        url = "https://www.bing.com/news/search?" + urlencode({"q": q, "format": "rss", "setlang": setlang, "mkt": mkt})
        r = ctx.fetcher.get(url)
        res.log_fetch(r)
        if not r.ok:
            continue
        items = parse_feed(r.text or "")
        if not items:
            res.notes.append(f"no results for “{q}”")
        for item in items[:per_query]:
            if not passes_keywords(source, item["title"], item.get("summary")):
                continue
            city = resolve_city(source, item["title"], item.get("summary"))
            sig = make_signal(source, ctx, item, city=city)
            if sig and sig["id"] not in seen:
                seen.add(sig["id"])
                sig["query"] = q
                res.signals.append(sig)
    return res
