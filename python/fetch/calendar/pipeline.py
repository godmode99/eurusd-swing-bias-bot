# python/fetch/calendar/pipeline.py
#
# Purpose:
# - Run calendar fetch pipeline steps based on config.yaml flags.

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import fnmatch
from typing import Any
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).parent.resolve()
PYTHON_DIR = BASE_DIR.parents[1].resolve()
TELEGRAM_REPORT_DIR = PYTHON_DIR / "telegram_report"
SELECT_EVENTS_JSON = PYTHON_DIR / "Data" / "raw_data" / "calendar" / "latest_select_events.json"
SELECT_EVENTS_META_JSON = PYTHON_DIR / "Data" / "raw_data" / "calendar" / "select_events.meta.json"

if TELEGRAM_REPORT_DIR.exists() and str(TELEGRAM_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_REPORT_DIR))

if not (TELEGRAM_REPORT_DIR / "telegram_notifier.py").exists():
    raise FileNotFoundError(
        f"telegram_notifier.py not found at: {TELEGRAM_REPORT_DIR / 'telegram_notifier.py'}\n"
        f"BASE_DIR={BASE_DIR}\n"
        f"PYTHON_DIR={PYTHON_DIR}\n"
        f"TELEGRAM_REPORT_DIR={TELEGRAM_REPORT_DIR}"
    )

from telegram_notifier import send_telegram_message

from utils import load_config, setup_logger, utc_now_iso


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "app" / "config.yaml"

DEFAULT_STEPS = {
    "01_save_session": False,
    "02_capture_document_html": True,
    "03_extract_from_document": True,
    "select_events": True,
    "20_make_risk_windows": False,
    "30_refresh_actuals": False,
    "40_compute_surprise": False,
}

DEFAULT_CLEANUP = {
    "enabled": True,
    "target_dir": str(PYTHON_DIR / "Data" / "raw_data" / "calendar"),
    "remove_files": [
        "calendar_document.html",
        "calendar_document.meta.json",
        "document_debug.png",
        "capture_error.txt",
        "extract_error.txt",
    ],
    "remove_globs": [
        "*.tmp",
        "*.temp",
        "*.bak",
        "*debug*",
    ],
    "keep_files": [
        "latest_select_events.json",
        "calendar_select_events.json",
        "calendar_select_events.csv",
        "select_events.meta.json",
        "calendar_all_event.json",
        "calendar_all_event.csv",
        "events.meta.json",
    ],
}


def load_steps() -> dict[str, bool]:
    cfg = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else {}
    pipeline_cfg = cfg.get("pipeline", {}) or {}
    steps_cfg = pipeline_cfg.get("steps", {}) or {}
    steps: dict[str, bool] = {}
    for name, default in DEFAULT_STEPS.items():
        value = steps_cfg.get(name, default)
        steps[name] = bool(value)
    return steps


def run_step(name: str) -> None:
    script_path = SCRIPT_DIR / f"{name}.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing step script: {script_path}")
    subprocess.run([sys.executable, str(script_path)], check=True)


def load_cleanup_config(cfg: dict[str, Any]) -> dict[str, Any]:
    cleanup_cfg = ((cfg.get("pipeline", {}) or {}).get("cleanup", {}) or {}).copy()
    merged: dict[str, Any] = {**DEFAULT_CLEANUP, **cleanup_cfg}

    # normalize list-like fields
    for key in ("remove_files", "remove_globs", "keep_files"):
        value = merged.get(key)
        if not isinstance(value, list):
            merged[key] = list(DEFAULT_CLEANUP[key])
            continue
        merged[key] = [str(item) for item in value if str(item).strip()]

    target_dir = merged.get("target_dir") or DEFAULT_CLEANUP["target_dir"]
    merged["target_dir"] = Path(str(target_dir)).resolve()
    merged["enabled"] = bool(merged.get("enabled", True))
    return merged


def cleanup_pipeline_artifacts(cleanup_cfg: dict[str, Any], logger: Any) -> None:
    if not cleanup_cfg.get("enabled", True):
        logger.info("CLEANUP disabled")
        return

    target_dir = cleanup_cfg["target_dir"]
    if not isinstance(target_dir, Path):
        target_dir = Path(str(target_dir)).resolve()

    if not target_dir.exists():
        logger.info("CLEANUP skip: target_dir does not exist (%s)", target_dir)
        return

    keep_files = set(cleanup_cfg.get("keep_files", []))
    remove_files = set(cleanup_cfg.get("remove_files", []))
    remove_globs = list(cleanup_cfg.get("remove_globs", []))

    removed: list[str] = []
    for path in target_dir.iterdir():
        if not path.is_file():
            continue
        if path.name in keep_files:
            continue

        should_remove = path.name in remove_files
        if not should_remove:
            should_remove = any(fnmatch.fnmatch(path.name, pattern) for pattern in remove_globs)
        if not should_remove:
            continue

        path.unlink(missing_ok=True)
        removed.append(path.name)

    if removed:
        removed.sort()
        logger.info("CLEANUP removed %d files: %s", len(removed), ", ".join(removed))
    else:
        logger.info("CLEANUP completed: no files removed")


def derive_select_events_reason(meta_path: Path) -> str | None:
    if not meta_path.exists():
        return "ไม่พบไฟล์ select_events.meta.json เพื่อระบุสาเหตุ"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "อ่านไฟล์ select_events.meta.json ไม่ได้ (JSON ผิดรูปแบบ)"
    if not isinstance(meta, dict):
        return "ไฟล์ select_events.meta.json ไม่ใช่ข้อมูลแบบ object"

    selected_count = meta.get("selected_count")
    latest_count = meta.get("latest_selected_count")
    try:
        selected_count = int(selected_count)
    except Exception:
        selected_count = None
    try:
        latest_count = int(latest_count)
    except Exception:
        latest_count = None

    if latest_count == 0:
        if selected_count == 0:
            return "ไม่พบข่าวที่ผ่านเงื่อนไขการคัดเลือก (selected_count=0)"
        return "ไม่มีข้อมูลข่าวใหม่อัปเดต (latest_selected_count=0)"
    if latest_count is None and selected_count == 0:
        return "ไม่พบข่าวที่ผ่านเงื่อนไขการคัดเลือก (selected_count=0)"
    return "latest_select_events.json ว่าง แต่ไม่พบสาเหตุที่ชัดเจนใน meta"


def load_select_events(path: Path, meta_path: Path) -> tuple[list[dict[str, str]], str | None]:
    if not path.exists():
        return [], "ไม่พบไฟล์ latest_select_events.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], "อ่านไฟล์ latest_select_events.json ไม่ได้ (JSON ผิดรูปแบบ)"
    if not isinstance(data, list):
        return [], "latest_select_events.json ไม่ใช่ array"

    if not data:
        return [], derive_select_events_reason(meta_path)

    rows: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        time_label = item.get("datetime_bkk") or item.get("timeLabel") or ""
        rows.append(
            {
                "time_label": str(time_label),
                "currency": str(item.get("currency") or ""),
                "impact": str(item.get("impact") or ""),
                "name": str(item.get("name") or ""),
                "actual": str(item.get("actual") or ""),
            }
        )
    return rows, None


def get_bangkok_today() -> datetime.date:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Bangkok")).date()


def format_time_label(value: str, today_bkk: datetime.date) -> tuple[str, bool]:
    cleaned = value.strip()
    if not cleaned:
        return "", False
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return cleaned, False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
    parsed_bkk = parsed.astimezone(ZoneInfo("Asia/Bangkok"))
    day = str(parsed.day)
    month = parsed.strftime("%b")
    time_label = parsed.strftime("%H:%M")
    label = f"{day}{month}-{time_label}"
    return label, parsed_bkk.date() == today_bkk


def format_pipeline_message(status: str, results: list[dict[str, Any]], error: str | None) -> str:
    if status == "OK":
        head = "✅ <b>Calendar Fetch: OK</b>"
    else:
        head = "❌ <b>Calendar Fetch: ERROR</b>"

    lines = [head, f"<b>asof_utc</b>: {utc_now_iso()}"]
    if results:
        lines.append("<b>Steps</b>:")
        for item in results:
            name = item["name"]
            outcome = item["status"]
            tag = "OK" if outcome == "success" else "FAIL"
            lines.append(f"• {name}: {tag}")
    if error:
        lines.append(f"<b>error</b>: {error}")

    select_result = next((item for item in results if item.get("name") == "select_events"), None)
    if select_result is not None:
        select_details = select_result.get("details")
        empty_reason = select_result.get("empty_reason")
        lines.append("<b>select_events</b>:")
        if select_details:
            lines.append("เวลาข่าวออก | currency | impact | name | actual")
            today_bkk = get_bangkok_today()
            for row in select_details:
                time_label, is_today = format_time_label(row.get("time_label", ""), today_bkk)
                time_label = escape(time_label)
                if is_today:
                    time_label = f"<b>{time_label}</b>"
                currency = escape(row.get("currency", ""))
                impact = escape(row.get("impact", ""))
                name = escape(row.get("name", ""))
                actual = escape(row.get("actual", ""))
                lines.append(f"{time_label} | {currency} | {impact} | {name} | {actual}")
        else:
            lines.append("ไม่มีข้อมูลใหม่ใน latest_select_events.json")
            if empty_reason:
                lines.append(f"<b>reason</b>: {escape(empty_reason)}")
    return "\n".join(lines)


def main() -> None:
    steps = load_steps()
    cfg = load_config(str(CONFIG_PATH)) if CONFIG_PATH.exists() else {}
    logs_dir = (SCRIPT_DIR / cfg.get("output", {}).get("logs_dir", "logs")).resolve()
    logger = setup_logger(logs_dir, name="fetch_calendar")

    results: list[dict[str, Any]] = []
    error_message: str | None = None

    logger.info("=== CALENDAR PIPELINE START ===")
    for name, enabled in steps.items():
        if not enabled:
            logger.info("SKIP %s", name)
            continue
        logger.info("RUN  %s", name)
        try:
            run_step(name)
            result: dict[str, Any] = {"name": name, "status": "success"}
            if name == "select_events":
                details, empty_reason = load_select_events(SELECT_EVENTS_JSON, SELECT_EVENTS_META_JSON)
                result["details"] = details
                result["empty_reason"] = empty_reason
            results.append(result)
        except Exception as exc:
            error_message = str(exc)
            results.append({"name": name, "status": "failed"})
            logger.exception("Step failed: %s", name)
            break
    logger.info("=== CALENDAR PIPELINE END ===")

    status = "ERROR" if error_message else "OK"

    if status == "OK":
        cleanup_cfg = load_cleanup_config(cfg)
        cleanup_pipeline_artifacts(cleanup_cfg, logger)

    tg = cfg.get("telegram", {}) or {}
    send_ok = bool(tg.get("send_on_success", True))
    send_err = bool(tg.get("send_on_error", True))
    should_send = (status == "OK" and send_ok) or (status == "ERROR" and send_err)
    if should_send:
        message = format_pipeline_message(status, results, error_message)
        send_telegram_message(cfg, message, logger=logger)

    if error_message:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
