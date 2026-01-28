from __future__ import annotations

import json
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
FETCH_DIR = ROOT_DIR / "fetch" / "fedwatch"
TRANSFORM_DIR = ROOT_DIR / "transform" / "fedwatch"

ART_DIR = ROOT_DIR.parent / "artifacts" / "fedwatch"
RUNS_DIR = ART_DIR / "runs"
LATEST_DIR = ART_DIR / "latest"
HISTORY_DIR = ART_DIR / "history"
PIPE_META = ART_DIR / "pipeline_run.meta.json"
PIPE_ERR = ART_DIR / "pipeline_error.txt"


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str]) -> int:
    res = subprocess.run(cmd, cwd=str(ROOT_DIR.parent))
    return res.returncode


def _copy_latest(run_dir: Path) -> None:
    for item in run_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, LATEST_DIR / item.name)


def _archive_history(run_dir: Path, run_id: str) -> None:
    dest = HISTORY_DIR / run_id
    shutil.copytree(run_dir, dest, dirs_exist_ok=True)


def main() -> int:
    _ensure_dirs()
    run_id = _run_id_now()
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    status = {
        "run_id": run_id,
        "started_at_utc": _iso_utc_now(),
        "status": "RUNNING",
        "steps": [],
        "paths": {
            "run_dir": str(run_dir.resolve()),
            "latest_dir": str(LATEST_DIR.resolve()),
            "history_dir": str(HISTORY_DIR.resolve()),
        },
    }

    def record(step: str, code: int) -> None:
        status["steps"].append({"step": step, "exit_code": code, "ok": code == 0})

    try:
        capture_cmd = [
            sys.executable,
            str(FETCH_DIR / "02_capture_document_html.py"),
            "--run-id",
            run_id,
            "--run-dir",
            str(run_dir),
        ]
        code = _run(capture_cmd)
        record("capture", code)
        if code == 2:
            status["status"] = "CHALLENGE"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return 2
        if code != 0:
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        extract_cmd = [
            sys.executable,
            str(FETCH_DIR / "03_extract_from_document.py"),
            "--run-dir",
            str(run_dir),
        ]
        code = _run(extract_cmd)
        record("extract", code)
        if code != 0:
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        normalize_cmd = [
            sys.executable,
            str(TRANSFORM_DIR / "20_normalize.py"),
            "--run-dir",
            str(run_dir),
        ]
        code = _run(normalize_cmd)
        record("normalize", code)
        if code != 0:
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        delta_cmd = [
            sys.executable,
            str(TRANSFORM_DIR / "30_compute_delta.py"),
            "--current",
            str(run_dir / "normalized.json"),
            "--output",
            str(run_dir / "delta.json"),
        ]
        code = _run(delta_cmd)
        record("delta", code)
        if code != 0:
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        digest_cmd = [
            sys.executable,
            str(TRANSFORM_DIR / "40_make_digest.py"),
            "--normalized",
            str(run_dir / "normalized.json"),
            "--delta",
            str(run_dir / "delta.json"),
            "--output",
            str(run_dir / "digest.json"),
        ]
        code = _run(digest_cmd)
        record("digest", code)
        if code != 0:
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        status["status"] = "OK"
        status["finished_at_utc"] = _iso_utc_now()
        (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")

        _copy_latest(run_dir)
        _archive_history(run_dir, run_id)
        return 0
    except Exception as exc:
        status["status"] = "ERROR"
        status["finished_at_utc"] = _iso_utc_now()
        status["error"] = str(exc)
        status["traceback"] = traceback.format_exc()
        (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
        PIPE_ERR.write_text(status["traceback"], encoding="utf-8")
        _copy_latest(run_dir)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
