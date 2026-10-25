"""SOCIAL ATLAS pipeline — one run = collect → extract → normalise → dedupe → verify →
enrich → persist → brief → monitor.

    python -m pipeline.run                       # scheduled/daily behaviour
    python -m pipeline.run --sources lu-vdl-agenda,ny-whitney --force
    python -m pipeline.run --retry-failed        # only sources whose last attempt failed
    python -m pipeline.run --reprocess           # no network: recompute statuses, scores, briefing
    python -m pipeline.run --trigger manual      # label the run (schedule|manual|local)

Exit code is 0 for success or partial success, 1 if every attempted source failed or the
pipeline crashed (so the scheduler shows a red run), 2 for configuration errors.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import yaml

from . import briefing as briefing_mod
from . import config, export
from .collectors import CollectResult, Context, get_collector
from .dedup import find_match, similarity
from .http import Fetcher
from .merge import event_id_for, merge_into, new_record
from .normalize import canonical_url, contains_any, now_utc, primary_action, stable_id, to_utc
from .score import radar_buckets, score_event
from .store import Database, load_sources, load_yaml, save_json
from .submit import process_submissions
from .verify import apply_link_check, assign_status, link_check_due

TRIP_WORDS = ["festival", "fair", "fashion week", "biennale", "world cup", "marathon", "grand slam", "art week", "design week", "carnival", "carnevale"]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def due(source: dict, state: dict, now) -> bool:
    last = to_utc(state.get("last_success_at"))
    if last is None:
        return True
    freq = float(source.get("frequency_days", 1))
    return (now - last) >= timedelta(days=freq) - timedelta(hours=3)


def run_source(source: dict, ctx: Context) -> tuple[dict, CollectResult, int]:
    t0 = time.monotonic()
    fn = get_collector(source["method"])
    try:
        res = fn(source, ctx)
    except Exception as exc:  # a broken collector must not kill the run
        res = CollectResult()
        res.errors.append(f"collector crashed: {type(exc).__name__}: {exc}")
        res.notes.append(traceback.format_exc(limit=3)[-600:])
    return source, res, int((time.monotonic() - t0) * 1000)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", help="comma-separated source ids to refresh (forces them)")
    ap.add_argument("--force", action="store_true", help="ignore per-source frequency")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--reprocess", action="store_true", help="no collection; recompute and export")
    ap.add_argument("--trigger", default=os.environ.get("ATLAS_TRIGGER", "local"))
    ap.add_argument("--no-link-checks", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)

    now = now_utc()
    now_iso = now.isoformat()
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + stable_id(now_iso, str(os.getpid()))[:4]
    runner = "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"
    run = {"run_id": run_id, "trigger": args.trigger, "runner": runner, "started_at": now_iso, "finished_at": None,
           "status": "running", "mode": "reprocess" if args.reprocess else "collect", "per_source": [], "errors": [],
           "github_run_url": _gh_run_url()}
    try:
        sources = load_sources()
    except Exception as exc:
        log(f"configuration error: {exc}")
        return 2
    db = Database()
    db.runs.append(run)
    fetcher = Fetcher(min_delay=float(os.environ.get("ATLAS_MIN_DELAY", "3")))
    ctx = Context(fetcher=fetcher, now_iso=now_iso, today=now.date().isoformat())
    stats = {"sources_attempted": 0, "sources_ok": 0, "sources_failed": 0, "sources_skipped": 0, "sources_manual": 0,
             "events_extracted": 0, "events_new": 0, "events_updated": 0, "duplicates_merged": 0,
             "possible_duplicates": 0, "signals_extracted": 0, "signals_new": 0, "link_checks": 0, "submissions_processed": 0}
    try:
        # ---------------- Stage 1–2: collection & extraction
        selected = set(filter(None, (args.sources or "").split(",")))
        unknown = selected - {s["id"] for s in sources}
        if unknown:
            log(f"unknown source ids: {sorted(unknown)}")
            return 2
        jobs = []
        for s in sources:
            st = db.source_state.setdefault(s["id"], {})
            st["method"] = s["method"]
            st["monitorable"] = s["method"] != "manual"
            if not s.get("enabled", True):
                continue
            if s["method"] == "manual":
                stats["sources_manual"] += 1
                st["last_status"] = "manual"
                st["reason"] = s.get("reason")
                continue
            if args.reprocess:
                continue
            if selected and s["id"] not in selected:
                continue
            if args.retry_failed and st.get("last_status") != "failed":
                continue
            if not (selected or args.force or args.retry_failed) and not due(s, st, now) and s["method"] != "curated":
                stats["sources_skipped"] += 1
                run["per_source"].append({"id": s["id"], "status": "skipped", "note": "checked recently (frequency)"})
                continue
            jobs.append(s)
        candidates, new_signals = [], []
        if jobs:
            log(f"collecting {len(jobs)} sources")
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for source, res, ms in pool.map(lambda s: run_source(s, ctx), jobs):
                    stats["sources_attempted"] += 1
                    ok_fetches = [f for f in res.fetches if f["ok"]]
                    crashed = any(e.startswith("collector crashed") for e in res.errors)
                    failed = crashed or (res.fetches and not ok_fetches) or (not res.fetches and source["method"] != "curated" and res.errors)
                    status = "failed" if failed else ("partial" if res.errors else "ok")
                    st = db.source_state[source["id"]]
                    st["last_attempt_at"] = now_iso
                    st["last_status"] = status
                    st["last_error"] = res.errors[0][:300] if res.errors else None
                    st["last_duration_ms"] = ms
                    if status == "failed":
                        st["consecutive_failures"] = int(st.get("consecutive_failures", 0)) + 1
                        stats["sources_failed"] += 1
                    else:
                        st["consecutive_failures"] = 0
                        st["last_success_at"] = now_iso
                        stats["sources_ok"] += 1
                        if res.events:
                            st["last_event_found_at"] = now_iso
                    st["last_counts"] = {"events": len(res.events), "signals": len(res.signals)}
                    candidates.extend(res.events)
                    new_signals.extend(res.signals)
                    run["per_source"].append({"id": source["id"], "status": status, "events": len(res.events),
                                              "signals": len(res.signals), "requests": len(res.fetches), "ms": ms,
                                              "errors": res.errors[:5], "notes": res.notes[:4],
                                              "retries": sum(max(0, f["attempts"] - 1) for f in res.fetches)})
                    log(f"  {source['id']:<24} {status:<7} events={len(res.events):<3} signals={len(res.signals):<3} {res.errors[0][:80] if res.errors else ''}")
        stats["events_extracted"] = len(candidates)
        stats["signals_extracted"] = len(new_signals)

        # ---------------- user-submitted URLs
        if not args.reprocess:
            sub_events, sub_signals, n = process_submissions(db, ctx)
            candidates.extend(sub_events)
            new_signals.extend(sub_signals)
            stats["submissions_processed"] = n

        # ---------------- Stage 3–4, 7: normalise, dedupe, persist
        pool = [e for e in db.events.values() if not e.get("duplicate_of")]
        for c in candidates:
            if not c.get("title") or not c.get("city"):
                continue
            rid = event_id_for(c)
            existing = db.events.get(rid)
            if existing or c.get("curated_id"):
                # researched events are matched only by their explicit id; automated
                # listings may still merge into them below
                match, maybes = existing, []
            else:
                match, maybes = find_match(c, pool)
            if match:
                # a second source reporting the same event = one de-duplicated listing
                if c["source_id"] not in {x["source_id"] for x in match["sources"]}:
                    stats["duplicates_merged"] += 1
                if match["id"] != rid and rid not in match["related_ids"]:
                    match["related_ids"].append(rid)
                if merge_into(match, c, now_iso):
                    stats["events_updated"] += 1
            else:
                rec = new_record(c, now_iso)
                for mid, score in maybes:
                    rec["review_flags"].append(f"possible duplicate of {mid} (similarity {score})")
                    stats["possible_duplicates"] += 1
                db.events[rec["id"]] = rec
                pool.append(rec)
                stats["events_new"] += 1
        for s in new_signals:
            if s["id"] in db.signals:
                db.signals[s["id"]]["last_seen_at"] = now_iso
                continue
            db.signals[s["id"]] = s
            stats["signals_new"] += 1
            st = db.source_state.get(s["source_id"])
            if st is not None:
                st["last_signal_found_at"] = now_iso

        # ---------------- Stage 5: verification (+ official link re-checks)
        overrides = load_yaml(config.OVERRIDES_FILE, {}) or {}
        _apply_overrides(db, overrides, now_iso)
        for ev in db.events.values():
            assign_status(ev, now)
        if not args.reprocess and not args.no_link_checks:
            due_checks = [e for e in db.events.values() if link_check_due(e, now)][:40]
            for e in due_checks:
                r = fetcher.get(e["official_url"])
                apply_link_check(e, r, now_iso)
                stats["link_checks"] += 1
        _apply_overrides(db, overrides, now_iso, statuses_only=True)

        # ---------------- Stage 6: enrichment
        _link_signals(db)
        coverage = _coverage(db)
        for ev in db.events.values():
            if ev.get("trip_suitable") is None:
                text = " ".join([ev.get("title") or "", ev.get("subcategory") or "", " ".join(ev.get("tags") or [])])
                hit = contains_any(text, TRIP_WORDS)
                # one screening inside a festival is not a reason to travel: require a multi-day run
                s_, e_ = to_utc(ev.get("start")), to_utc(ev.get("end"))
                multi_day = bool(s_ and e_ and (e_ - s_) >= timedelta(hours=36))
                hit = hit if multi_day else None
                ev["trip_suitable"] = bool(hit)
                if hit:
                    ev["booking"].setdefault("inferred", [])
                    note = f"trip-suitable: inferred from '{hit}'"
                    if note not in ev["booking"]["inferred"]:
                        ev["booking"]["inferred"].append(note)
            score_event(ev, now, coverage.get(ev["id"], 1))
            ev["radar"] = radar_buckets(ev, now, coverage.get(ev["id"], 1))
            ev["booking"]["primary_action"] = primary_action(ev)
            ev["coverage"] = coverage.get(ev["id"], 1)
        _prune(db, now)

        # ---------------- Stage 8: briefing
        events = list(db.events.values())
        signals = list(db.signals.values())
        brief = briefing_mod.build(events, signals, now, run_id)
        save_json(config.BRIEFINGS_DIR / f"{brief['date']}.json", brief)
        save_json(config.BRIEFINGS_DIR / "latest.json", brief)

        # ---------------- Stage 9: monitoring
        if stats["sources_attempted"] and stats["sources_failed"] == stats["sources_attempted"]:
            run["status"] = "failed"
        elif stats["sources_failed"]:
            run["status"] = "partial"
        else:
            run["status"] = "success"
        _source_totals(db)
    except Exception as exc:
        run["status"] = "failed"
        run["errors"].append(f"pipeline crashed: {type(exc).__name__}: {exc}")
        run["errors"].append(traceback.format_exc(limit=6)[-1500:])
        log(run["errors"][-1])
    finally:
        run["finished_at"] = now_utc().isoformat()
        run["requests"] = fetcher.request_count
        run.update(stats)
        db.save()
        try:
            export.export_site(db)
        except Exception as exc:
            log(f"export failed: {exc}")
            run["status"] = "failed"
            run["errors"].append(f"export failed: {exc}")
            db.save()
    log(f"run {run_id}: {run['status']} · new events {stats['events_new']} · updated {stats['events_updated']} · "
        f"new signals {stats['signals_new']} · sources ok {stats['sources_ok']}/{stats['sources_attempted']}")
    return 1 if run["status"] == "failed" else 0


def _gh_run_url() -> str | None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    return f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}"


def _apply_overrides(db: Database, overrides: dict, now_iso: str, statuses_only: bool = False) -> None:
    for eid, ov in (overrides.get("events") or {}).items():
        ev = db.events.get(eid)
        if not ev or not isinstance(ov, dict):
            continue
        if statuses_only:
            if ov.get("verification_status"):
                ev["verification_status"] = ov["verification_status"]
                ev["manually_verified"] = True
            continue
        for k, v in (ov.get("set") or {}).items():
            if ev.get(k) != v:
                ev["history"].append({"at": now_iso, "field": k, "old": ev.get(k), "new": v, "source": "manual override"})
                ev[k] = v
        for k, v in (ov.get("booking") or {}).items():
            if ev["booking"].get(k) != v:
                ev["history"].append({"at": now_iso, "field": f"booking.{k}", "old": ev["booking"].get(k), "new": v, "source": "manual override"})
                ev["booking"][k] = v
        if ov.get("hide") is not None:
            ev["hidden"] = bool(ov["hide"])
        if ov.get("note"):
            note = {"url": None, "publisher": "Manual review", "reliability": 1, "checked_at": ov.get("checked_at", now_iso), "note": ov["note"]}
            if note["note"] not in [e.get("note") for e in ev["verification_evidence"]]:
                ev["verification_evidence"].append(note)
        if ov.get("verification_status"):
            ev["last_verified_at"] = ov.get("checked_at", now_iso)
            ev["review_flags"] = []
            ev["conflicts"] = []


def _link_signals(db: Database) -> None:
    by_city: dict[str, list[dict]] = {}
    for e in db.events.values():
        if e.get("verification_status") not in ("past", "cancelled"):
            by_city.setdefault(e["city"], []).append(e)
    for s in db.signals.values():
        if s.get("linked_event_id") or not s.get("city"):
            continue
        best, best_s = None, 0.0
        for e in by_city.get(s["city"], []):
            sc = similarity(s["title"], e["title"])
            if sc > best_s:
                best, best_s = e, sc
        if best and best_s >= 0.55:
            s["linked_event_id"] = best["id"]
            s["link_score"] = round(best_s, 2)


def _coverage(db: Database) -> dict[str, int]:
    cov = {e["id"]: len({x["source_id"] for x in e.get("sources", [])}) for e in db.events.values()}
    for s in db.signals.values():
        if s.get("linked_event_id") in cov:
            cov[s["linked_event_id"]] += 1
    return cov


def _source_totals(db: Database) -> None:
    totals: dict[str, dict] = {}
    for e in db.events.values():
        for ref in e.get("sources", []):
            t = totals.setdefault(ref["source_id"], {"events": 0, "verified_events": 0, "duplicates": 0, "signals": 0})
            t["events"] += 1
            if e.get("verification_status") == "confirmed":
                t["verified_events"] += 1
            if len(e.get("sources", [])) > 1:
                t["duplicates"] += 1
    for s in db.signals.values():
        t = totals.setdefault(s["source_id"], {"events": 0, "verified_events": 0, "duplicates": 0, "signals": 0})
        t["signals"] += 1
    for sid, st in db.source_state.items():
        st["totals"] = totals.get(sid, {"events": 0, "verified_events": 0, "duplicates": 0, "signals": 0})


def _prune(db: Database, now) -> None:
    keep_after = now - timedelta(days=config.PAST_EVENT_ARCHIVE_DAYS)
    for eid in [e["id"] for e in db.events.values() if e.get("verification_status") == "past"]:
        end = to_utc(db.events[eid].get("end") or db.events[eid].get("start"))
        if end and end < keep_after:
            del db.events[eid]
    sig_after = now - timedelta(days=config.SIGNAL_RETENTION_DAYS)
    for sid in [s["id"] for s in db.signals.values()]:
        d = to_utc(db.signals[sid].get("discovered_at"))
        if d and d < sig_after:
            del db.signals[sid]


if __name__ == "__main__":
    sys.exit(main())
