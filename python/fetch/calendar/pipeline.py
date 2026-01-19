from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
import json

from utils import ensure_dir, utc_now_iso, atomic_write_json, date_utc_compact, retry
from calendar_client import fetch_forexfactory_xml, normalize_currency, normalize_impact


@dataclass
class SourceStatus:
    ok: bool
    rows: int
    latest: str | None
    used_cache: bool
    error: str | None


def load_cache_json(path: Path) -> List[Dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def filter_events(events: List[Dict[str, Any]], currencies: List[str], impacts: List[str]) -> List[Dict[str, Any]]:
    cur_set = {c.upper() for c in (currencies or []) if c}
    imp_set = {i.capitalize() for i in (impacts or []) if i}

    out: List[Dict[str, Any]] = []
    for e in events:
        cur = normalize_currency(e.get("currency"))
        imp = normalize_impact(e.get("impact"))

        if cur_set and cur not in cur_set:
            continue
        if imp_set and imp not in imp_set:
            continue

        out.append(e)

    return out


def try_extract_latest_date(events: List[Dict[str, Any]]) -> str | None:
    # FF date format varies (sometimes blank / sometimes like "Jan 19" / sometimes numeric)
    # We keep it simple: pick the last non-empty 'date' encountered in the list order.
    last = None
    for e in events:
        d = str(e.get("date") or "").strip()
        if d:
            last = d
    return last


def run_fetch_pipeline(cfg: Dict[str, Any], logger, base_dir: Path) -> Dict[str, Any]:
    data_dir = ensure_dir((base_dir / cfg["output"]["data_dir"]).resolve())

    run_tag = date_utc_compact()
    manifest_path_latest = data_dir / "fetch_manifest.json"
    manifest_path_archive = data_dir / f"fetch_manifest_{run_tag}.json"
    error_path_archive = data_dir / f"fetch_error_{run_tag}.json"

    snapshot_latest = data_dir / "calendar.json"                 # overwrite always
    snapshot_daily = data_dir / f"calendar_{run_tag}.json"       # archive daily

    keep_run_manifest = cfg.get("output", {}).get("archive", {}).get("keep_run_manifest", True)
    keep_error_report = cfg.get("output", {}).get("archive", {}).get("keep_error_report", True)
    keep_daily_snapshot = cfg.get("output", {}).get("archive", {}).get("keep_daily_snapshot", True)

    cal_cfg = cfg.get("calendar", {}) or {}
    timeout_seconds = int(cal_cfg.get("timeout_seconds", 30))
    currencies = cal_cfg.get("currencies", ["USD", "EUR"]) or ["USD", "EUR"]
    impacts = cal_cfg.get("impacts", ["High", "Medium"]) or ["High", "Medium"]

    attempts = int(cfg.get("retry", {}).get("attempts", 3))
    sleep_seconds = int(cfg.get("retry", {}).get("sleep_seconds", 2))

    status = SourceStatus(ok=False, rows=0, latest=None, used_cache=False, error=None)

    try:
        logger.info("Fetching calendar from ForexFactory weekly XML...")
        raw_events = retry(
            lambda: fetch_forexfactory_xml(timeout_seconds=timeout_seconds),
            attempts=attempts,
            sleep_seconds=sleep_seconds,
            logger=logger,
            label="FF_XML_CALENDAR",
        )

        filtered = filter_events(raw_events, currencies=currencies, impacts=impacts)
        latest = try_extract_latest_date(filtered)

        # write snapshots
        atomic_write_json(snapshot_latest, filtered)
        if keep_daily_snapshot:
            atomic_write_json(snapshot_daily, filtered)

        status = SourceStatus(ok=True, rows=len(filtered), latest=latest, used_cache=False, error=None)

        logger.info(f"Saved snapshot latest: {snapshot_latest} rows={len(filtered)} latest={latest}")
        if keep_daily_snapshot:
            logger.info(f"Saved snapshot daily: {snapshot_daily}")

    except Exception as e:
        logger.error(f"Calendar fetch failed: {e}")

        cache = load_cache_json(snapshot_latest)
        if cache is not None:
            latest = try_extract_latest_date(cache)
            status = SourceStatus(ok=True, rows=len(cache), latest=latest, used_cache=True, error=str(e))
            logger.warning("Using cache calendar.json (stale).")
        else:
            status = SourceStatus(ok=False, rows=0, latest=None, used_cache=False, error=str(e))

        if keep_error_report:
            atomic_write_json(error_path_archive, {
                "asof_utc": utc_now_iso(),
                "stage": "fetch_calendar_forexfactory_xml",
                "error": str(e),
            })

    manifest = {
        "asof_utc": utc_now_iso(),
        "sources": {
            "FOREXFACTORY_XML_CALENDAR": {
                **vars(status),
                "filters": {"currencies": currencies, "impacts": impacts},
            }
        },
        "stale_sources": (["FOREXFACTORY_XML_CALENDAR"] if status.used_cache else []),
        "notes": "" if status.ok else "Calendar fetch failed and no cache available.",
    }

    atomic_write_json(manifest_path_latest, manifest)
    if keep_run_manifest:
        atomic_write_json(manifest_path_archive, manifest)

    logger.info(f"Wrote manifest latest: {manifest_path_latest}")
    if keep_run_manifest:
        logger.info(f"Wrote manifest archive: {manifest_path_archive}")

    return manifest
