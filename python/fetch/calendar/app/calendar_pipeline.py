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
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

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
    }

    try:
        # ---- Step 02: capture document ----
        print("STEP02 capture document ...", flush=True)
        step02.main()
        meta["steps"].append({"step": "02_capture_document_html", "ok": True})

        # ---- Step 03: extract events ----
        print("STEP03 extract events ...", flush=True)
        step03.main()
        meta["steps"].append({"step": "03_extract_from_document", "ok": True})

        # ---- Step 20: risk windows ----
        print("STEP20 make risk windows ...", flush=True)
        step20.main(pair=args.pair, do_merge=(not args.no_merge))
        meta["steps"].append({"step": "20_make_risk_windows", "ok": True})

        # ---- Archive ----
        if args.archive:
            print("ARCHIVE outputs ...", flush=True)
            meta["archived"] = archive_run(run_dir)

        PIPE_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        print("DONE", flush=True)
        print("saved pipeline meta:", str(PIPE_META.resolve()), flush=True)
        if args.archive:
            print("archived to:", str(run_dir.resolve()), flush=True)

    except Exception:
        PIPE_ERR.write_text(traceback.format_exc(), encoding="utf-8")
        print("ERROR saved ->", str(PIPE_ERR.resolve()), flush=True)
        meta["steps"].append({"step": "pipeline", "ok": False, "error_file": str(PIPE_ERR.resolve())})
        PIPE_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
