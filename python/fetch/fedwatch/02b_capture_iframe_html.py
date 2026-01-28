from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
DEFAULT_STATE_PATH = Path("secrets") / "fedwatch_storage.json"
FALLBACK_STATE_PATHS = (Path("ff_storage.json"), Path("secrets") / "ff_storage.json")
ART_DIR = Path("artifacts") / "fedwatch"
LATEST_DIR = ART_DIR / "latest"
RUNS_DIR = ART_DIR / "runs"

CHALLENGE_KEYWORDS = [
    "just a moment",
    "checking your browser",
    "cloudflare",
    "attention required",
    "pardon our interruption",
    "access denied",
    "request blocked",
    "temporarily unavailable",
    "verify you are human",
    "captcha",
]


@dataclass
class IframeMeta:
    fetched_at_utc: str
    run_id: str
    host_url: str
    iframe_url: str
    final_url: str
    page_title: str
    status: str
    html_saved_to: str
    screenshot_saved_to: str
    storage_state_path: str
    playwright_user_agent: str


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _ensure_dirs(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _abs(p: Path) -> str:
    return str(p.resolve())


def _detect_status(title: str, body_text: str) -> str:
    text = f"{title} {body_text}".lower()
    if any(k in text for k in CHALLENGE_KEYWORDS):
        if "access denied" in text or "blocked" in text:
            return "BLOCKED"
        return "CHALLENGE"
    return "OK"


def _copy_to_latest(run_dir: Path) -> None:
    for name in ["iframe.html", "iframe_screenshot.png", "iframe_meta.json"]:
        src = run_dir / name
        if src.exists():
            shutil.copy2(src, LATEST_DIR / name)


def _resolve_state_path() -> Path:
    env_path = os.getenv("FEDWATCH_STORAGE_PATH")
    if env_path:
        return Path(env_path)
    if DEFAULT_STATE_PATH.exists():
        return DEFAULT_STATE_PATH
    for candidate in FALLBACK_STATE_PATHS:
        if candidate.exists():
            return candidate
    return DEFAULT_STATE_PATH


def _find_iframe_src(html: str) -> Optional[str]:
    match = re.search(r"<iframe[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=_run_id_now())
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--iframe-url", default="")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else RUNS_DIR / args.run_id
    _ensure_dirs(run_dir)

    state_path = _resolve_state_path()
    if not state_path.exists():
        raise FileNotFoundError(
            f"Missing storage state file: {_abs(state_path)}\n"
            "Expected: secrets/fedwatch_storage.json (run 01_save_session.py), "
            "ff_storage.json in repo root, or set FEDWATCH_STORAGE_PATH."
        )

    iframe_url: Optional[str] = args.iframe_url or None
    html_text: Optional[str] = None
    final_url = ""
    page_title = ""
    body_text = ""
    ua = ""

    out_html = run_dir / "iframe.html"
    out_png = run_dir / "iframe_screenshot.png"
    out_meta = run_dir / "iframe_meta.json"
    out_err = run_dir / "iframe_capture_error.txt"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=str(state_path),
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )

        try:
            ua = context.user_agent
        except Exception:
            ua = ""

        host_page = context.new_page()

        if not iframe_url:
            host_page.goto(URL, wait_until="domcontentloaded", timeout=120000)
            try:
                host_page.wait_for_selector("iframe.cmeIframe", timeout=60000)
                iframe_url = host_page.locator("iframe.cmeIframe").first.get_attribute("src")
            except Exception:
                iframe_url = None

            if not iframe_url:
                try:
                    host_html = host_page.content()
                except Exception:
                    host_html = ""
                iframe_url = _find_iframe_src(host_html)

        if not iframe_url:
            host_page.close()
            context.close()
            browser.close()
            out_err.write_text(
                "Failed to locate iframe src.\n"
                f"- host_url: {URL}\n",
                encoding="utf-8",
            )
            return 1

        iframe_url = urljoin(URL, iframe_url)
        iframe_page = context.new_page()
        iframe_page.goto(iframe_url, wait_until="domcontentloaded", timeout=120000)
        iframe_page.wait_for_timeout(5000)

        final_url = iframe_page.url
        page_title = iframe_page.title()
        try:
            body_text = iframe_page.inner_text("body")
        except Exception:
            body_text = ""

        iframe_page.screenshot(path=str(out_png), full_page=True)
        try:
            html_text = iframe_page.content()
        except Exception:
            html_text = None

        iframe_page.close()
        host_page.close()
        context.close()
        browser.close()

    status = _detect_status(page_title, body_text)

    meta = IframeMeta(
        fetched_at_utc=_iso_utc_now(),
        run_id=args.run_id,
        host_url=URL,
        iframe_url=iframe_url,
        final_url=final_url,
        page_title=page_title,
        status=status,
        html_saved_to=_abs(out_html),
        screenshot_saved_to=_abs(out_png),
        storage_state_path=_abs(state_path),
        playwright_user_agent=ua,
    )
    out_meta.write_text(json.dumps(asdict(meta), indent=2, ensure_ascii=False), encoding="utf-8")

    if not html_text:
        out_err.write_text(
            "Failed to capture iframe HTML.\n"
            f"- iframe_url: {iframe_url}\n"
            f"- final_url: {final_url}\n"
            f"- title: {page_title}\n",
            encoding="utf-8",
        )
        _copy_to_latest(run_dir)
        return 1

    out_html.write_text(html_text, encoding="utf-8")
    _copy_to_latest(run_dir)

    if status in {"CHALLENGE", "BLOCKED"}:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        err_path = RUNS_DIR / "iframe_capture_error.txt"
        err_path.write_text(traceback.format_exc(), encoding="utf-8")
        print("ERROR saved ->", str(err_path.resolve()), flush=True)
        raise
