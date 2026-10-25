#!/usr/bin/env python3
"""Used by the Submit URL workflow.

    ISSUE_BODY=... ISSUE_NUMBER=12 python scripts/add_submission.py          # queue
    ISSUE_NUMBER=12 python scripts/add_submission.py --report                # markdown reply

The issue body comes from the "Submit a URL" issue form and is treated strictly as data.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import config  # noqa: E402
from pipeline.normalize import is_safe_public_url, stable_id  # noqa: E402


def parse_form(body: str) -> dict:
    fields: dict[str, str] = {}
    for block in re.split(r"^###\s+", body or "", flags=re.M)[1:]:
        title, _, value = block.partition("\n")
        value = value.strip()
        if value in ("_No response_", ""):
            value = ""
        fields[title.strip().lower()] = value
    return fields


def queue() -> int:
    issue = os.environ.get("ISSUE_NUMBER", "?")
    f = parse_form(os.environ.get("ISSUE_BODY", ""))
    url = (f.get("url") or f.get("public url") or "").strip().split()[0] if (f.get("url") or f.get("public url")) else ""
    city = (f.get("city") or "").strip().lower()
    city = {"new york city": "nyc", "cortina d'ampezzo": "cortina"}.get(city, city)
    if city not in config.CITIES:
        city = ""
    note = (f.get("note") or "")[:200]
    if not is_safe_public_url(url):
        print(f"Rejected: not a public http(s) URL: {url!r}")
        return 1
    items = yaml.safe_load(config.SUBMISSIONS_FILE.read_text()) if config.SUBMISSIONS_FILE.exists() else []
    items = items or []
    if any(isinstance(i, dict) and i.get("url") == url for i in items):
        print("Already queued")
        return 0
    items.append({"url": url, "city": city or None, "note": note or None,
                  "submitted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "submitted_by": f"issue #{issue}"})
    header = "".join(line + "\n" for line in config.SUBMISSIONS_FILE.read_text().splitlines() if line.startswith("#")) if config.SUBMISSIONS_FILE.exists() else ""
    config.SUBMISSIONS_FILE.write_text(header + yaml.safe_dump(items, allow_unicode=True, sort_keys=False))
    print(f"Queued {url}")
    return 0


def report() -> int:
    issue = os.environ.get("ISSUE_NUMBER", "?")
    state_path = config.DB / "submissions_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    mine = [s for s in state.values() if s.get("submitted_by") == f"issue #{issue}"]
    if not mine:
        print("The URL could not be queued (it must be a public http(s) address). Nothing was processed.")
        return 0
    s = mine[-1]
    lines = [f"Processed `{s['url']}` — result: **{s['status']}**."]
    if s.get("events"):
        lines.append("Listed as *announced — verification pending*: " + ", ".join(f"“{t}”" for t in s["events"]) + ".")
    elif s.get("status") in ("no_structured_data", "city_unknown"):
        lines.append("No structured event data on the page, so it was kept as a lead for manual entry (Insider Radar → Social signals). "
                     "Add the details to `data/curated/` or `data/overrides.yaml` to list it properly.")
    if s.get("error"):
        lines.append(f"Error: {s['error']}")
    print("\n\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(report() if "--report" in sys.argv else queue())
