#!/usr/bin/env python3
"""Probe candidate sources before adding them to the registry.

Usage:
    python scripts/probe_source.py URL [URL ...]
    python scripts/probe_source.py --file urls.txt

For each URL it reports: HTTP status, robots.txt permission for the SOCIAL ATLAS
user agent, content type, whether it looks like RSS/Atom or iCalendar, the number
of schema.org Event objects found in JSON-LD, and any feed links advertised in
the page <head>. Use the result to choose a `method` in data/sources.yaml.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.http import Fetcher  # noqa: E402
from pipeline.extract import extract_jsonld_events  # noqa: E402


def probe(fetcher: Fetcher, url: str) -> dict:
    out: dict = {"url": url}
    res = fetcher.get(url)
    out["status"] = res.status
    out["error"] = res.error
    out["robots_allowed"] = res.robots_allowed
    if not res.ok:
        return out
    text = res.text or ""
    ctype = (res.content_type or "").lower()
    out["content_type"] = ctype
    head = text[:2000].lower()
    out["is_feed"] = ("<rss" in head) or ("<feed" in head and "atom" in head) or "xml" in ctype and "<item" in text[:20000].lower()
    out["is_ical"] = "begin:vcalendar" in head
    try:
        evs = extract_jsonld_events(text, url)
    except Exception as exc:  # pragma: no cover - diagnostics only
        evs = []
        out["jsonld_error"] = str(exc)
    out["jsonld_events"] = len(evs)
    if evs:
        out["sample_event"] = {k: evs[0].get(k) for k in ("name", "startDate", "url")}
    feeds = []
    if "<html" in head or "<!doctype html" in head:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text, "html.parser")
        for link in soup.find_all("link", attrs={"rel": True, "href": True}):
            rel = " ".join(link.get("rel") or []).lower()
            typ = (link.get("type") or "").lower()
            if "alternate" in rel and ("rss" in typ or "atom" in typ or "calendar" in typ):
                feeds.append(urljoin(url, link["href"]))
    out["advertised_feeds"] = feeds[:5]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--json", action="store_true", help="print JSON lines")
    args = ap.parse_args()
    urls = list(args.urls)
    if args.file:
        urls += [u.strip() for u in Path(args.file).read_text().splitlines() if u.strip() and not u.startswith("#")]
    fetcher = Fetcher(min_delay=0.5)
    # group by host so per-host politeness is preserved while hosts run in parallel
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda u: probe(fetcher, u), urls))
    for r in results:
        if args.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            host = urlparse(r["url"]).netloc
            flags = []
            if r.get("is_feed"):
                flags.append("FEED")
            if r.get("is_ical"):
                flags.append("ICAL")
            if r.get("jsonld_events"):
                flags.append(f"JSONLD:{r['jsonld_events']}")
            if r.get("advertised_feeds"):
                flags.append("feeds=" + ",".join(r["advertised_feeds"][:2]))
            print(f"{r.get('status')!s:>4} robots={r.get('robots_allowed')!s:5} {host:38} {' '.join(flags)} {r.get('error') or ''}  {r['url']}")


if __name__ == "__main__":
    main()
