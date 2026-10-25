#!/usr/bin/env python3
"""Discover the official social accounts of registered sources.

For every source with a website, fetch its homepage (robots.txt respected) and collect
links to Instagram / Facebook / X / Threads / Pinterest / TikTok profiles that the site
itself publishes. Such an account is "verified by link from the official site" — we never
guess handles. Results are merged into data/accounts.yaml without removing manual entries.

    python scripts/discover_social.py            # all sources
    python scripts/discover_social.py lu-mudam   # selected ids
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import config  # noqa: E402
from pipeline.http import Fetcher  # noqa: E402
from pipeline.store import load_sources  # noqa: E402

PLATFORMS = {
    "instagram.com": "instagram", "facebook.com": "facebook", "x.com": "x", "twitter.com": "x",
    "threads.net": "threads", "threads.com": "threads", "pinterest.com": "pinterest", "tiktok.com": "tiktok",
}
SKIP = re.compile(r"^/(share|sharer|intent|p|reel|explore|hashtag|stories|dialog|plugins|tr|events|watch|home|login|search)\b", re.I)


def handle_from(url: str) -> tuple[str, str] | None:
    p = urlparse(url)
    host = re.sub(r"^(www\.|m\.)", "", p.netloc.lower())
    plat = PLATFORMS.get(host)
    if not plat:
        return None
    path = p.path.rstrip("/")
    if not path or SKIP.match(path) or path.count("/") > 1 and plat != "facebook":
        return None
    handle = path.strip("/").split("/")[0]
    if handle.startswith("@"):
        handle = handle[1:]
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{2,60}", handle) or handle.lower() in ("profile.php", "photo.php", "pages", "groups", "people"):
        return None
    return plat, handle


def main() -> None:
    wanted = set(sys.argv[1:])
    sources = [s for s in load_sources() if s.get("url") and s["type"] not in ("search_aggregator", "research", "ticketing_platform")]
    if wanted:
        sources = [s for s in sources if s["id"] in wanted]
    doc = yaml.safe_load(config.ACCOUNTS_FILE.read_text()) if config.ACCOUNTS_FILE.exists() else {}
    accounts = (doc or {}).get("accounts", []) or []
    index = {(a["platform"], a["handle"].lower()): a for a in accounts}
    f = Fetcher(min_delay=1.0)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    homes = {}
    for s in sources:
        p = urlparse(s["url"])
        homes.setdefault(f"{p.scheme}://{p.netloc}/", []).append(s)
    for home, srcs in homes.items():
        r = f.get(home)
        if not r.ok:
            print(f"skip {home}: {r.error}")
            continue
        soup = BeautifulSoup(r.text or "", "html.parser")
        found = set()
        for a in soup.find_all("a", href=True):
            h = handle_from(urljoin(home, a["href"]))
            if h:
                found.add(h)
        for plat, handle in sorted(found):
            key = (plat, handle.lower())
            s = srcs[0]
            acc = index.get(key) or {
                "platform": plat, "handle": handle, "url": _profile_url(plat, handle), "city": s["city"],
                "topics": s.get("categories", []), "linked_source": s["id"], "owner": s["name"],
            }
            acc["verified_by"] = f"linked from {home} ({now[:10]})"
            acc["relevance"] = acc.get("relevance") or f"Official account of {s['name']}"
            acc["monitoring"] = acc.get("monitoring") or _monitoring(plat)
            index[key] = acc
        print(f"{home}: {len(found)} account(s)")
    out = sorted(index.values(), key=lambda a: (config.CITY_ORDER.index(a["city"]) if a["city"] in config.CITY_ORDER else 99, a["platform"], a["handle"].lower()))
    header = ("# Social & insider accounts directory.\n"
              "# Entries with `verified_by: linked from …` were found as links on that organisation's own website.\n"
              "# Entries with `added_by: user` were added by you; `added_by: research` were suggested by a named article\n"
              "# and have not been opened (Instagram needs a login). Audience numbers are deliberately not stored.\n"
              "# monitoring: no free, permitted automated access to these platforms is configured, so accounts\n"
              "# are checked by hand and interesting posts are fed in through the Submit-a-URL form.\n")
    config.ACCOUNTS_FILE.write_text(header + yaml.safe_dump({"accounts": out}, allow_unicode=True, sort_keys=False, width=140))
    print(f"{len(out)} accounts written to {config.ACCOUNTS_FILE}")


def _profile_url(plat: str, handle: str) -> str:
    return {"instagram": f"https://www.instagram.com/{handle}/", "facebook": f"https://www.facebook.com/{handle}",
            "x": f"https://x.com/{handle}", "threads": f"https://www.threads.net/@{handle}",
            "pinterest": f"https://www.pinterest.com/{handle}/", "tiktok": f"https://www.tiktok.com/@{handle}"}[plat]


def _monitoring(plat: str) -> str:
    return {"instagram": "manual — profile pages sit behind a login wall; API access would need a Meta developer app and your own Business account (not configured)",
            "facebook": "manual — reading pages via the Graph API needs a reviewed Meta app (not configured)",
            "x": "manual — API read access is not free",
            "threads": "manual — no permitted free reading method configured",
            "pinterest": "manual", "tiktok": "manual"}[plat]


if __name__ == "__main__":
    main()
