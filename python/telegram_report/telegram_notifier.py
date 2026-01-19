# telegram_notifier.py
from __future__ import annotations

import requests
from typing import Any, Dict


def _bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def send_telegram_message(cfg: Dict[str, Any], text: str, logger=None) -> None:
    tg = cfg.get("telegram", {}) if cfg else {}
    if not _bool(tg.get("enabled"), False):
        return

    bot_token = tg.get("bot_token")
    chat_id = tg.get("chat_id")

    if not bot_token or not chat_id:
        if logger:
            logger.warning("Telegram enabled but bot_token/chat_id is missing. Skipping telegram notify.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, data=payload, timeout=20)
        if not r.ok and logger:
            detail = r.text
            try:
                response_json = r.json()
                detail = response_json.get("description", detail)
            except ValueError:
                response_json = None
            logger.warning(f"Telegram send failed: HTTP {r.status_code} {detail}")
            if r.status_code == 400 and "chat not found" in str(detail).lower():
                logger.warning(
                    "Telegram chat not found. Check telegram.chat_id, ensure the bot is added to the chat, "
                    "and send /start to the bot for direct messages."
                )
    except Exception as e:
        if logger:
            logger.warning(f"Telegram send exception: {e}")


def classify_manifest(manifest: Dict[str, Any]) -> str:
    """
    Returns: "OK" | "WARN" | "ERROR"
    """
    sources = manifest.get("sources", {}) or {}
    stale = manifest.get("stale_sources", []) or []
    notes = (manifest.get("notes") or "").strip()

    any_fail = any((not (v.get("ok") is True)) for v in sources.values()) if isinstance(sources, dict) else False
    if any_fail:
        return "ERROR"
    if stale or notes:
        return "WARN"
    return "OK"


def format_manifest_message(manifest: Dict[str, Any]) -> str:
    status = classify_manifest(manifest)
    asof = manifest.get("asof_utc", "?")

    if status == "OK":
        head = "✅ <b>MT5 Fetch: OK</b>"
    elif status == "WARN":
        head = "⚠️ <b>MT5 Fetch: WARNING</b>"
    else:
        head = "❌ <b>MT5 Fetch: ERROR</b>"

    lines = [head, f"<b>asof_utc</b>: {asof}"]

    sources = manifest.get("sources", {}) or {}
    if isinstance(sources, dict) and sources:
        lines.append("<b>Sources</b>:")
        for k, v in sources.items():
            ok = v.get("ok")
            rows = v.get("rows")
            latest = v.get("latest_time")
            used_cache = v.get("used_cache")
            tag = "OK" if ok else "FAIL"
            cache = " (cache)" if used_cache else ""
            lines.append(f"• {k}: {tag}{cache}, rows={rows}, latest={latest}")

    stale = manifest.get("stale_sources", []) or []
    if stale:
        lines.append(f"<b>stale_sources</b>: {', '.join(stale)}")

    notes = (manifest.get("notes") or "").strip()
    if notes:
        lines.append(f"<b>notes</b>: {notes}")

    return "\n".join(lines)
