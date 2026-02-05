# pipeline.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd

from fetch_mt5 import MT5Client
from utils import (
    ensure_dir,
    th_now_iso,
    atomic_write_json,
    date_th_compact,
    timestamp_th_compact,
    build_output_filename,
    save_json,
    load_cache_json,
    find_latest_cache,
)


@dataclass
class SourceStatus:
    ok: bool
    rows: int
    latest_time: str | None
    used_cache: bool
    error: str | None


def validate_ohlc(df: pd.DataFrame, cfg: Dict[str, Any]) -> None:
    if df.empty:
        raise ValueError("OHLC dataframe is empty")

    min_price = float(cfg["validation"]["min_price"])
    max_price = float(cfg["validation"]["max_price"])
    max_missing_ratio = float(cfg["validation"]["max_missing_ratio"])

    for c in ["open", "high", "low", "close"]:
        miss = float(df[c].isna().mean())
        if miss > max_missing_ratio:
            raise ValueError(f"Too many missing values in {c}: {miss:.4f} > {max_missing_ratio}")
        if (df[c] <= 0).any():
            raise ValueError(f"Non-positive prices in {c}")
        if (df[c] < min_price).any() or (df[c] > max_price).any():
            raise ValueError(f"Price out of range in {c} (expected {min_price}..{max_price})")

    # OHLC containment
    if not ((df["low"] <= df["open"]) & (df["open"] <= df["high"])).all():
        raise ValueError("OHLC containment failed for open")
    if not ((df["low"] <= df["close"]) & (df["close"] <= df["high"])).all():
        raise ValueError("OHLC containment failed for close")

    # time monotonic
    if not df["time_th"].is_monotonic_increasing:
        raise ValueError("time_th is not sorted increasing")


def load_cache_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "time_th" in df.columns:
        df["time_th"] = pd.to_datetime(df["time_th"])
    elif "time_utc" in df.columns:
        df["time_th"] = pd.to_datetime(df["time_utc"], utc=True).dt.tz_convert("Asia/Bangkok")
        df = df.drop(columns=["time_utc"])
    return df


def save_csv(df: pd.DataFrame, path: Path) -> None:
    """
    Always overwrites OHLC files (as requested). We store time_th as ISO-TH string.
    """
    out = df.copy()
    out["time_th"] = out["time_th"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    out.to_csv(path, index=False)


def format_timeframe_label(timeframe: str) -> str:
    tf = timeframe.upper()
    digits = "".join(ch for ch in tf if ch.isdigit())
    letters = "".join(ch for ch in tf if ch.isalpha())
    if letters == "MN":
        letters = "M"
    return f"{digits}{letters}" if digits and letters else tf


def run_fetch_pipeline(cfg: Dict[str, Any], logger, base_dir: Path) -> Dict[str, Any]:
    """
    Policy:
      - OHLC CSVs overwrite (eurusd_d1.csv, eurusd_h4.csv)
      - Latest manifest overwrites (fetch_manifest.json)
      - Run manifest archived with date suffix (fetch_manifest_YYYYMMDD.json)
      - Error report archived with date suffix on failures (fetch_error_YYYYMMDD.json)
    """
    # Resolve output dirs relative to the folder containing main.py/config.yaml
    data_dir = ensure_dir((base_dir / cfg["output"]["data_dir"]).resolve())

    run_tag = date_th_compact()  # YYYYMMDD (TH)

    # Manifests
    manifest_path_latest = data_dir / "fetch_manifest.json"                 # overwrite
    manifest_path_archive = data_dir / f"fetch_manifest_{run_tag}.json"     # keep
    error_path_archive = data_dir / f"fetch_error_{run_tag}.json"           # keep on failure

    keep_run_manifest = cfg.get("archive", {}).get("keep_run_manifest", True)
    keep_error_report = cfg.get("archive", {}).get("keep_error_report", True)

    terminal_path = cfg["mt5"].get("terminal_path") or None
    symbols: List[str] = cfg.get("symbols", ["EURUSD"])
    fetch_cfg = cfg.get("fetch", {}) or {}
    store_time_as_th_default = bool(fetch_cfg.get("store_time_as_th", True))
    output_format = str(cfg.get("output", {}).get("format", "csv")).lower()
    if output_format == "cvs":
        output_format = "csv"
    file_label_default = str(cfg.get("output", {}).get("file_label", "data"))
    timeframe_configs = fetch_cfg.get("timeframes")
    if timeframe_configs:
        fetch_specs = [
            {
                "timeframe": str(item["timeframe"]).upper(),
                "bars": int(item["bars"]),
                "store_time_as_th": bool(item.get("store_time_as_th", store_time_as_th_default)),
                "file_label": str(item.get("file_label", file_label_default)),
            }
            for item in timeframe_configs
        ]
    else:
        fetch_specs = [
            {
                "timeframe": str(fetch_cfg["timeframe"]).upper(),
                "bars": int(fetch_cfg["bars"]),
                "store_time_as_th": store_time_as_th_default,
                "file_label": file_label_default,
            }
        ]

    mt5c = MT5Client(terminal_path=terminal_path)
    stale_sources: List[str] = []
    statuses: Dict[str, SourceStatus] = {}

    # --- CONNECT ---
    try:
        logger.info("Connecting to MT5...")
        mt5c.connect()
        logger.info("MT5 connected.")
    except Exception as e:
        logger.error(f"MT5 connect failed: {e}")
        try:
            mt5c.shutdown()
        except Exception:
            pass

        # Fallback to cache for each symbol/timeframe
        for sym in symbols:
            for spec in fetch_specs:
                timeframe = spec["timeframe"]
                file_label = spec["file_label"]
                timeframe_label = format_timeframe_label(timeframe)
                cache_path = find_latest_cache(data_dir, sym, file_label, output_format, timeframe_label)
                if cache_path and output_format == "json":
                    cache_df = load_cache_json(cache_path)
                elif cache_path:
                    cache_df = load_cache_csv(cache_path)
                else:
                    cache_df = None
                key = f"{sym}_{timeframe}"
                if cache_df is not None and len(cache_df) > 0:
                    latest = pd.to_datetime(cache_df["time_th"].iloc[-1]).strftime("%Y-%m-%dT%H:%M:%S%z")
                    statuses[key] = SourceStatus(ok=True, rows=len(cache_df), latest_time=latest, used_cache=True, error=str(e))
                    stale_sources.append(key)
                else:
                    statuses[key] = SourceStatus(ok=False, rows=0, latest_time=None, used_cache=False, error=str(e))

        manifest = {
            "asof_th": th_now_iso(),
            "sources": {k: vars(v) for k, v in statuses.items()},
            "stale_sources": stale_sources,
            "notes": "MT5 connect failed; used cache where available.",
        }

        # Write latest + archive manifest
        atomic_write_json(manifest_path_latest, manifest)
        if keep_run_manifest:
            atomic_write_json(manifest_path_archive, manifest)

        # Write error report (dated)
        if keep_error_report:
            atomic_write_json(error_path_archive, {
                "asof_th": th_now_iso(),
                "stage": "connect_mt5",
                "error": str(e),
            })

        return manifest

    # --- FETCH ---
    for sym in symbols:
        for spec in fetch_specs:
            timeframe = spec["timeframe"]
            bars = spec["bars"]
            store_time_as_th = spec["store_time_as_th"]
            file_label = spec["file_label"]
            timeframe_label = format_timeframe_label(timeframe)
            timestamp = timestamp_th_compact()
            filename = build_output_filename(sym, file_label, output_format, timestamp, timeframe_label)
            output_path = data_dir / filename
            try:
                logger.info(f"Fetching {sym} {timeframe} ({bars} bars)...")
                res = mt5c.fetch_rates(sym, timeframe, bars, store_time_as_th=store_time_as_th)
                validate_ohlc(res.df, cfg)
                if output_format == "json":
                    save_json(res.df, output_path)
                else:
                    save_csv(res.df, output_path)
                statuses[f"{sym}_{timeframe}"] = SourceStatus(
                    ok=True,
                    rows=res.rows,
                    latest_time=res.latest_time_th,
                    used_cache=False,
                    error=None,
                )
                logger.info(f"Saved {output_path} rows={res.rows} latest={res.latest_time_th}")
            except Exception as e:
                logger.error(f"Fetch {sym} {timeframe} failed: {e}")
                cache_path = find_latest_cache(data_dir, sym, file_label, output_format, timeframe_label)
                if cache_path and output_format == "json":
                    cache_df = load_cache_json(cache_path)
                elif cache_path:
                    cache_df = load_cache_csv(cache_path)
                else:
                    cache_df = None
                key = f"{sym}_{timeframe}"
                if cache_df is not None and len(cache_df) > 0:
                    latest = pd.to_datetime(cache_df["time_th"].iloc[-1]).strftime("%Y-%m-%dT%H:%M:%S%z")
                    statuses[key] = SourceStatus(ok=True, rows=len(cache_df), latest_time=latest, used_cache=True, error=str(e))
                    stale_sources.append(key)
                    logger.warning(f"Using cache for {sym} {timeframe} (stale).")
                    if keep_error_report:
                        atomic_write_json(error_path_archive, {
                            "asof_th": th_now_iso(),
                            "stage": f"fetch_{sym}_{timeframe}",
                            "error": str(e),
                        })
                else:
                    statuses[key] = SourceStatus(ok=False, rows=0, latest_time=None, used_cache=False, error=str(e))
                    if keep_error_report:
                        atomic_write_json(error_path_archive, {
                            "asof_th": th_now_iso(),
                            "stage": f"fetch_{sym}_{timeframe}",
                            "error": str(e),
                        })

    # Shutdown MT5 cleanly
    try:
        mt5c.shutdown()
    except Exception:
        pass

    # --- MANIFEST WRITE ---
    manifest = {
        "asof_th": th_now_iso(),
        "sources": {k: vars(v) for k, v in statuses.items()},
        "stale_sources": stale_sources,
        "notes": "",
    }

    # Always overwrite latest manifest
    atomic_write_json(manifest_path_latest, manifest)
    # Archive manifest with date suffix
    if keep_run_manifest:
        atomic_write_json(manifest_path_archive, manifest)

    logger.info(f"Wrote manifest latest: {manifest_path_latest}")
    if keep_run_manifest:
        logger.info(f"Wrote manifest archive: {manifest_path_archive}")

    return manifest
