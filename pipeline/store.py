"""Flat-file database (JSON in git). Atomic writes, stable ordering for readable diffs."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from . import config


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} is not valid JSON ({exc}); refusing to overwrite it") from exc


def save_json(path: Path, data: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        if compact:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def load_sources() -> list[dict]:
    doc = load_yaml(config.SOURCES_FILE, {})
    defaults = doc.get("defaults", {})
    out = []
    ids = set()
    for s in doc.get("sources", []):
        merged = {**defaults, **s}
        if merged["id"] in ids:
            raise ValueError(f"duplicate source id {merged['id']}")
        ids.add(merged["id"])
        merged.setdefault("enabled", True)
        out.append(merged)
    return out


class Database:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {e["id"]: e for e in load_json(config.EVENTS_DB, [])}
        self.signals: dict[str, dict] = {s["id"]: s for s in load_json(config.SIGNALS_DB, [])}
        self.source_state: dict[str, dict] = load_json(config.SOURCE_STATE_DB, {})
        self.runs: list[dict] = load_json(config.RUNS_DB, [])
        self.submissions_state: dict[str, dict] = load_json(config.DB / "submissions_state.json", {})

    def save(self) -> None:
        events = sorted(self.events.values(), key=lambda e: ((e.get("start") or "9999"), e["id"]))
        save_json(config.EVENTS_DB, events)
        signals = sorted(self.signals.values(), key=lambda s: (s.get("discovered_at") or "", s["id"]), reverse=True)
        save_json(config.SIGNALS_DB, signals)
        save_json(config.SOURCE_STATE_DB, self.source_state)
        save_json(config.RUNS_DB, self.runs[-config.MAX_RUNS_KEPT:])
        save_json(config.DB / "submissions_state.json", self.submissions_state)
