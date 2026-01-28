from __future__ import annotations

import json
import logging
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

LOGGER = logging.getLogger("fedwatch_pipeline")


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    LOGGER.info(
        "Ensured pipeline directories: runs=%s latest=%s history=%s",
        RUNS_DIR,
        LATEST_DIR,
        HISTORY_DIR,
    )


def _run(cmd: list[str]) -> int:
    LOGGER.info("Running command: %s", " ".join(cmd))
    res = subprocess.run(cmd, cwd=str(ROOT_DIR.parent))
    LOGGER.info("Command finished with exit code %s", res.returncode)
    return res.returncode


def _copy_latest(run_dir: Path) -> None:
    LOGGER.info("Copying latest artifacts from %s", run_dir)
    for item in run_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, LATEST_DIR / item.name)
            LOGGER.info("Copied %s -> %s", item.name, LATEST_DIR / item.name)


def _archive_history(run_dir: Path, run_id: str) -> None:
    dest = HISTORY_DIR / run_id
    shutil.copytree(run_dir, dest, dirs_exist_ok=True)
    LOGGER.info("Archived run to history: %s", dest)


def main() -> int:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    LOGGER.info("Starting fedwatch pipeline run.")
    _ensure_dirs()
    run_id = _run_id_now()
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Run id: %s", run_id)
    LOGGER.info("Run directory: %s", run_dir)

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
        LOGGER.info("Step '%s' completed with exit code %s", step, code)

    try:
        LOGGER.info("Step: capture")
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
            LOGGER.warning("Capture step returned challenge code 2.")
            status["status"] = "CHALLENGE"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return 2
        if code != 0:
            LOGGER.error("Capture step failed with exit code %s.", code)
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        LOGGER.info("Step: extract")
        extract_cmd = [
            sys.executable,
            str(FETCH_DIR / "03_extract_from_document.py"),
            "--run-dir",
            str(run_dir),
        ]
        code = _run(extract_cmd)
        record("extract", code)
        if code != 0:
            LOGGER.error("Extract step failed with exit code %s.", code)
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        LOGGER.info("Step: normalize")
        normalize_cmd = [
            sys.executable,
            str(TRANSFORM_DIR / "20_normalize.py"),
            "--run-dir",
            str(run_dir),
        ]
        code = _run(normalize_cmd)
        record("normalize", code)
        if code != 0:
            LOGGER.error("Normalize step failed with exit code %s.", code)
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        LOGGER.info("Step: delta")
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
            LOGGER.error("Delta step failed with exit code %s.", code)
            status["status"] = "ERROR"
            status["finished_at_utc"] = _iso_utc_now()
            (run_dir / "run_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            PIPE_META.write_text(json.dumps(status, indent=2), encoding="utf-8")
            _copy_latest(run_dir)
            return code

        LOGGER.info("Step: digest")
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
            LOGGER.error("Digest step failed with exit code %s.", code)
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
        LOGGER.info("Pipeline finished successfully.")

        _copy_latest(run_dir)
        _archive_history(run_dir, run_id)
        return 0
    except Exception as exc:
        LOGGER.exception("Pipeline failed with unexpected error: %s", exc)
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
