# python/app/calendar_pipeline.py
#
# Purpose:
# - One-command pipeline runner:
#   02_capture_document_html.py  -> artifacts/ff/calendar_document.html (+ screenshot/meta)
#   03_extract_from_document.py  -> artifacts/ff/events.json (+ csv/meta)
#   20_make_risk_windows.py      -> artifacts/ff/no_trade_windows.json (+ meta)
# - After each run, archive key outputs to artifacts/ff/runs/<timestamp>/
#
# Notes:
# - ASCII-only console output (Windows cp1252 safe).
# - Assumes you run from repo root (recommended).
# - Assumes the three scripts exist and have main() functions as provided earlier.

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

# -------------------------------------------------------------------
# calendar_pipeline.py location: <repo_root>/python/fetch/calendar/app/calendar_pipeline.py
# telegram_notifier.py location: <repo_root>/python/telegram_report/telegram_notifier.py
# -------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()  # .../python/fetch/calendar/app
CALENDAR_DIR = BASE_DIR.parent.resolve()  # .../python/fetch/calendar
PYTHON_DIR = BASE_DIR.parents[2].resolve()  # .../python
TELEGRAM_REPORT_DIR = PYTHON_DIR / "telegram_report"

if CALENDAR_DIR.exists() and str(CALENDAR_DIR) not in sys.path:
    sys.path.insert(0, str(CALENDAR_DIR))

if TELEGRAM_REPORT_DIR.exists() and str(TELEGRAM_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_REPORT_DIR))

if not (TELEGRAM_REPORT_DIR / "telegram_notifier.py").exists():
    raise FileNotFoundError(
        "telegram_notifier.py not found at: "
        + str(TELEGRAM_REPORT_DIR / "telegram_notifier.py")
    )

from telegram_notifier import send_telegram_message
from utils import load_config, setup_logger

# --- repo-relative paths ---
REPO_ROOT = Path.cwd()  # expect running from repo root
ART_DIR = Path("artifacts") / "ff"
RUNS_DIR = ART_DIR / "runs"

# inputs/outputs written by individual scripts
CAPTURE_HTML = ART_DIR / "calendar_document.html"
CAPTURE_PNG  = ART_DIR / "document_debug.png"
CAPTURE_META = ART_DIR / "calendar_document.meta.json"

EVENTS_JSON  = ART_DIR / "events.json"
EVENTS_CSV   = ART_DIR / "events.csv"
EVENTS_META  = ART_DIR / "events.meta.json"

WINDOWS_JSON = ART_DIR / "no_trade_windows.json"
WINDOWS_META = ART_DIR / "no_trade_windows.meta.json"

PIPE_ERR     = ART_DIR / "pipeline_error.txt"
PIPE_META    = ART_DIR / "pipeline_run.meta.json"

CONFIG_PATH = CALENDAR_DIR / "config.yaml"


def _safe_count_json_list(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return len(data) if isinstance(data, list) else 0


def _pair_currencies(pair: str) -> list[str]:
    clean = "".join(ch for ch in str(pair) if ch.isalnum()).upper()
    if len(clean) < 6:
        return []
    return [clean[:3], clean[3:6]]


def _load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _summarize_related_news(events_path: Path, pair: str, limit: int = 10) -> dict:
    currencies = _pair_currencies(pair)
    if not currencies:
        return {"pair_currencies": [], "total": 0, "items": []}
    events = _load_events(events_path)
    related = [
        e for e in events if str(e.get("currency", "")).upper() in currencies
    ]
    items = []
    for event in related[:limit]:
        time_label = event.get("timeLabel") or event.get("datetime_bkk") or "-"
        currency = str(event.get("currency") or "-").upper()
        impact = event.get("impact") or ""
        name = event.get("prefixedName") or event.get("name") or "-"
        parts = [time_label, currency]
        if impact:
            parts.append(impact)
        detail = " ".join(parts)
        items.append(f"{detail} - {name}")
    return {"pair_currencies": currencies, "total": len(related), "items": items}


def _classify_status(steps_ok: bool, events_count: int, windows_count: int) -> str:
    if not steps_ok:
        return "ERROR"
    if events_count == 0 or windows_count == 0:
        return "WARN"
    return "OK"


def _format_telegram_message(meta: dict, status: str) -> str:
    if status == "OK":
        head = "✅ <b>FF Calendar: OK</b>"
    elif status == "WARN":
        head = "⚠️ <b>FF Calendar: WARNING</b>"
    else:
        head = "❌ <b>FF Calendar: ERROR</b>"

    lines = [
        head,
        f"<b>run_id</b>: {meta.get('run_id', '-')}",
        f"<b>pair</b>: {meta.get('pair', '-')}",
        f"<b>events</b>: {meta.get('events_count', 0)}",
        f"<b>windows</b>: {meta.get('windows_count', 0)}",
    ]

    if meta.get("merge_overlaps") is not None:
        lines.append(f"<b>merge_overlaps</b>: {meta.get('merge_overlaps')}")

    if meta.get("archived"):
        lines.append("<b>archived</b>: yes")

    steps = meta.get("steps", [])
    if steps:
        ok_steps = [s.get("step") for s in steps if s.get("ok") is True]
        bad_steps = [s.get("step") for s in steps if s.get("ok") is False]
        total_steps = len(steps)
        lines.append(f"<b>steps_total</b>: {total_steps}")
        if ok_steps:
            lines.append("<b>steps_ok</b>: " + ", ".join(ok_steps))
        if bad_steps:
            lines.append("<b>steps_failed</b>: " + ", ".join(bad_steps))

    related = meta.get("related_news") or {}
    related_total = related.get("total")
    related_items = related.get("items") or []
    related_currencies = related.get("pair_currencies") or []
    if related_total is not None:
        label = ", ".join(related_currencies) if related_currencies else meta.get("pair", "-")
        lines.append(f"<b>related_news</b> ({label}): {related_total}")
        if related_items:
            lines.append("<b>related_news_details</b>:")
            for item in related_items:
                lines.append(f"- {item}")

    err_file = meta.get("error_file") or ""
    if err_file:
        lines.append(f"<b>error_file</b>: {err_file}")

    paths = meta.get("paths", {})
    if paths:
        lines.append("<b>paths</b>:")
        for key, value in paths.items():
            lines.append(f"- <b>{key}</b>: {value}")

    archive_dir = meta.get("archive_dir")
    if archive_dir:
        lines.append(f"<b>archive_dir</b>: {archive_dir}")
        archived = meta.get("archived", {})
        if archived:
            lines.append(f"<b>archived_files</b>: {len(archived)}")

    return "\n".join(lines)


def ts_folder_name() -> str:
    # safe for Windows folder names
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def ensure_dirs() -> None:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def import_step_modules():
    """
    Import step modules. This assumes these files exist:
    - python/fetch/calendar/02_capture_document_html.py
    - python/fetch/calendar/03_extract_from_document.py
    - python/fetch/calendar/20_make_risk_windows.py
    """
    # Ensure repo root on sys.path for any package-relative imports.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    def load_module(name: str, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"Missing step module: {path}")
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load module spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)  # type: ignore[call-arg]
        return module

    step02 = load_module(
        "ff_step02",
        REPO_ROOT / "python" / "fetch" / "calendar" / "02_capture_document_html.py",
    )
    step03 = load_module(
        "ff_step03",
        REPO_ROOT / "python" / "fetch" / "calendar" / "03_extract_from_document.py",
    )
    step20 = load_module(
        "ff_step20",
        REPO_ROOT / "python" / "fetch" / "calendar" / "20_make_risk_windows.py",
    )
    return step02, step03, step20


def archive_run(run_dir: Path) -> dict:
    """
    Copy key output files into run_dir (if they exist).
    Returns dict of archived files.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    files = [
        CAPTURE_HTML, CAPTURE_PNG, CAPTURE_META,
        EVENTS_JSON, EVENTS_CSV, EVENTS_META,
        WINDOWS_JSON, WINDOWS_META,
    ]

    archived = {}
    for f in files:
        if f.exists():
            dst = run_dir / f.name
            shutil.copy2(f, dst)
            archived[f.name] = str(dst.resolve())

    return archived


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser(description="ForexFactory calendar pipeline runner")
    ap.add_argument("--pair", default="EURUSD", help="Target pair for risk windows (default: EURUSD)")
    ap.add_argument("--no-merge", action="store_true", help="Disable overlap merge in risk windows step")
    ap.add_argument("--archive", action="store_true", help="Archive outputs to artifacts/ff/runs/<timestamp>/")
    args = ap.parse_args()

    cfg = {}
    logger = logging.getLogger("calendar_pipeline")
    if CONFIG_PATH.exists():
        cfg = load_config(str(CONFIG_PATH))
        logs_dir = (CALENDAR_DIR / cfg.get("output", {}).get("logs_dir", "logs")).resolve()
        logger = setup_logger(logs_dir, name="fetch_calendar")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    # Import modules
    # Module names cannot start with digits, so we load by file path instead.
    step02, step03, step20 = import_step_modules()

    run_id = ts_folder_name()
    run_dir = RUNS_DIR / run_id

    meta = {
        "run_id": run_id,
        "cwd": str(REPO_ROOT.resolve()),
        "pair": args.pair,
        "merge_overlaps": (not args.no_merge),
        "steps": [],
        "archived": {},
        "paths": {
            "events_json": str(EVENTS_JSON.resolve()),
            "events_csv": str(EVENTS_CSV.resolve()),
            "windows_json": str(WINDOWS_JSON.resolve()),
            "pipeline_meta": str(PIPE_META.resolve()),
        },
    }

    try:
        # ---- Step 02: capture document ----
        print("STEP02 capture document ...", flush=True)
        step02.main()
        meta["steps"].append({"step": "02_capture_document_html", "ok": True})

        # ---- Step 03: extract events ----
        print("STEP03 extract events ...", flush=True)
        step03.main()
        events_count = _safe_count_json_list(EVENTS_JSON)
        meta["steps"].append({"step": "03_extract_from_document", "ok": True})
        meta["events_count"] = events_count
        meta["related_news"] = _summarize_related_news(EVENTS_JSON, args.pair)

        # ---- Step 20: risk windows ----
        print("STEP20 make risk windows ...", flush=True)
        step20.main(pair=args.pair, do_merge=(not args.no_merge))
        windows_count = _safe_count_json_list(WINDOWS_JSON)
        meta["steps"].append({"step": "20_make_risk_windows", "ok": True})
        meta["windows_count"] = windows_count

        # ---- Archive ----
        if args.archive:
            print("ARCHIVE outputs ...", flush=True)
            meta["archived"] = archive_run(run_dir)
            meta["archive_dir"] = str(run_dir.resolve())

        status = _classify_status(True, meta.get("events_count", 0), meta.get("windows_count", 0))
        meta["status"] = status
        PIPE_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        tg = cfg.get("telegram", {}) or {}
        send_ok = bool(tg.get("send_on_success", True))
        send_warn = bool(tg.get("send_on_warning", True))
        send_err = bool(tg.get("send_on_error", True))
        should_send = (status == "OK" and send_ok) or (status == "WARN" and send_warn) or (status == "ERROR" and send_err)
        if should_send:
            msg = _format_telegram_message(meta, status)
            send_telegram_message(cfg, msg, logger=logger)

        print("DONE", flush=True)
        print("saved pipeline meta:", str(PIPE_META.resolve()), flush=True)
        if args.archive:
            print("archived to:", str(run_dir.resolve()), flush=True)

    except Exception:
        PIPE_ERR.write_text(traceback.format_exc(), encoding="utf-8")
        print("ERROR saved ->", str(PIPE_ERR.resolve()), flush=True)
        error_path = str(PIPE_ERR.resolve())
        meta["steps"].append({"step": "pipeline", "ok": False, "error_file": error_path})
        meta["error_file"] = error_path
        meta["status"] = "ERROR"
        PIPE_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        cfg = {}
        logger = logging.getLogger("calendar_pipeline")
        if CONFIG_PATH.exists():
            cfg = load_config(str(CONFIG_PATH))
            logs_dir = (CALENDAR_DIR / cfg.get("output", {}).get("logs_dir", "logs")).resolve()
            logger = setup_logger(logs_dir, name="fetch_calendar")
        else:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
        tg = cfg.get("telegram", {}) or {}
        send_ok = bool(tg.get("send_on_success", True))
        send_warn = bool(tg.get("send_on_warning", True))
        send_err = bool(tg.get("send_on_error", True))
        should_send = (meta["status"] == "OK" and send_ok) or (meta["status"] == "WARN" and send_warn) or (meta["status"] == "ERROR" and send_err)
        if should_send:
            msg = _format_telegram_message(meta, meta["status"])
            send_telegram_message(cfg, msg, logger=logger)
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
