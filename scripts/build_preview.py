#!/usr/bin/env python3
"""Bundle the site and its current data into ONE self-contained HTML file
(dist/social-atlas-preview.html) — handy for sharing a snapshot or previewing without a
web server. The live site does not need this; it reads site/data/*.json directly."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def main() -> None:
    html = (SITE / "index.html").read_text()
    css = (SITE / "assets" / "styles.css").read_text()
    data = {}
    for name in ("meta", "events", "signals", "sources", "runs", "briefing", "archive"):
        p = SITE / "data" / f"{name}.json"
        data[name] = json.loads(p.read_text()) if p.exists() else None
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    scripts = "\n".join(
        f"<script>\n{(SITE / rel).read_text()}\n</script>" for rel in ("config.js", "assets/logic.js", "assets/app.js")
    )
    html = html.replace('<link rel="stylesheet" href="assets/styles.css">', f"<style>\n{css}\n</style>")
    html = re.sub(r'\s*<script src="config.js"></script>\s*<script src="assets/logic.js"></script>\s*<script src="assets/app.js"></script>',
                  lambda _m: f"\n<script>window.ATLAS_EMBEDDED = {embedded};</script>\n{scripts}", html)
    import sys
    if "--fragment" in sys.argv:
        # for hosts that supply their own <html>/<head>/<body> skeleton
        html = re.sub(r"<!doctype html>\s*", "", html, flags=re.I)
        html = re.sub(r"</?(html|head|body)\b[^>]*>", "", html)
    out = ROOT / "dist" / ("social-atlas-fragment.html" if "--fragment" in sys.argv else "social-atlas-preview.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
