from __future__ import annotations

import argparse
import json
import shutil
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
STATE_PATH = Path("secrets") / "fedwatch_storage.json"
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
class Meta:
    fetched_at_utc: str
    run_id: str
    url: str
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
    for name in ["page.html", "screenshot.png", "meta.json"]:
        src = run_dir / name
        if src.exists():
            shutil.copy2(src, LATEST_DIR / name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=_run_id_now())
    parser.add_argument("--run-dir", default="")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else RUNS_DIR / args.run_id
    _ensure_dirs(run_dir)

    if not STATE_PATH.exists():
        raise FileNotFoundError(
            f"Missing storage state file: {_abs(STATE_PATH)}\n"
            "Expected: secrets/fedwatch_storage.json (run 01_save_session.py)."
        )

    html_text: Optional[str] = None
    doc_status: Optional[int] = None
    final_url = ""
    page_title = ""
    body_text = ""
    ua = ""

    out_html = run_dir / "page.html"
    out_png = run_dir / "screenshot.png"
    out_meta = run_dir / "meta.json"
    out_err = run_dir / "capture_error.txt"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=str(STATE_PATH),
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )

        try:
            ua = context.user_agent
        except Exception:
            ua = ""

        page = context.new_page()

        def on_response(resp):
            nonlocal html_text, doc_status
            try:
                if resp.request.resource_type == "document" and resp.url.startswith(URL):
                    doc_status = resp.status
                    if resp.status == 200:
                        html_text = resp.text()
            except Exception:
                pass

        page.on("response", on_response)

        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(5000)

        final_url = page.url
        page_title = page.title()
        try:
            body_text = page.inner_text("body")
        except Exception:
            body_text = ""

        page.screenshot(path=str(out_png), full_page=True)

        if not html_text:
            try:
                html_text = page.content()
            except Exception:
                html_text = None

        context.close()
        browser.close()

    status = _detect_status(page_title, body_text)

    if not html_text:
        out_err.write_text(
            "Failed to capture document HTML.\n"
            f"- doc_status: {doc_status}\n"
            f"- final_url: {final_url}\n"
            f"- title: {page_title}\n",
            encoding="utf-8",
        )
        return 1

    out_html.write_text(html_text, encoding="utf-8")

    meta = Meta(
        fetched_at_utc=_iso_utc_now(),
        run_id=args.run_id,
        url=URL,
        final_url=final_url,
        page_title=page_title,
        status=status,
        html_saved_to=_abs(out_html),
        screenshot_saved_to=_abs(out_png),
        storage_state_path=_abs(STATE_PATH),
        playwright_user_agent=ua,
    )
    out_meta.write_text(json.dumps(asdict(meta), indent=2, ensure_ascii=False), encoding="utf-8")

    _copy_to_latest(run_dir)

    if status in {"CHALLENGE", "BLOCKED"}:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        err_path = RUNS_DIR / "capture_error.txt"
        err_path.write_text(traceback.format_exc(), encoding="utf-8")
        print("ERROR saved ->", str(err_path.resolve()), flush=True)
        raise
