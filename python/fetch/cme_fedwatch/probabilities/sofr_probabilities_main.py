# sofr_probabilities_main.py
# CME SOFRWatch Sniffer (Playwright Sync)
#
# Install:
#   pip install playwright
#   playwright install
#
# Run:
#   python sofr_probabilities_main.py --browser auto --wait_s 25
#   python sofr_probabilities_main.py --browser firefox --wait_s 25
#   python sofr_probabilities_main.py --browser chromium --channel chrome --wait_s 25
#   python sofr_probabilities_main.py --browser chromium --headless false --wait_s 25
#   python sofr_probabilities_main.py --browser auto --strict_filter --json_only

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import sync_playwright

TARGET_URL = "https://www.cmegroup.com/markets/interest-rates/cme-sofrwatch.html"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

BLOCK_RESOURCE_TYPES = {"image", "media", "font"}

# กรอง URL ที่ “น่าจะเป็น XHR/JSON/API” (ปรับได้)
INTERESTING_URL_RE = re.compile(
    r"(sofrwatch|sofr|fedwatch|fed|fomc|watch|prob|probab|dataservice|api|graphql|xhr|json|rates)",
    re.IGNORECASE,
)

# network error ที่ควร fallback
FATAL_NAV_SIGNS = (
    "ERR_HTTP2_PROTOCOL_ERROR",
    "net::ERR_HTTP2_PROTOCOL_ERROR",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_TIMED_OUT",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_SSL_PROTOCOL_ERROR",
    "ERR_CERT",
)


@dataclass
class RunConfig:
    browser: str                  # auto|chromium|firefox|webkit
    channel: Optional[str]        # chrome|msedge (chromium only)
    headless: bool
    wait_s: float
    outdir: Path
    save_har: bool
    ua: str
    strict_filter: bool
    timeout_ms: int
    json_only: bool


def ensure_outdir(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "responses").mkdir(parents=True, exist_ok=True)
    (outdir / "meta").mkdir(parents=True, exist_ok=True)


def safe_filename_from_url(url: str, max_len: int = 120) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "_", url)
    if len(clean) > max_len:
        clean = clean[:max_len]
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{clean}__{h}"


def is_fatal_nav_error(e: Exception) -> bool:
    msg = str(e)
    return any(sig in msg for sig in FATAL_NAV_SIGNS)


def route_filter(route) -> None:
    req = route.request
    if req.resource_type in BLOCK_RESOURCE_TYPES:
        return route.abort()
    return route.continue_()


def dump_response(cfg: RunConfig, url: str, status: int, headers: dict, body_bytes: bytes) -> None:
    ctype = (headers.get("content-type") or headers.get("Content-Type") or "").lower()

    # strict filter = เซฟเฉพาะ URL ที่ดูเข้าข่ายข้อมูลสำคัญ
    if cfg.strict_filter and not INTERESTING_URL_RE.search(url):
        return

    # กันไฟล์บวม
    if len(body_bytes) > 15 * 1024 * 1024:
        return

    base = safe_filename_from_url(url)
    ts = time.strftime("%Y%m%d_%H%M%S")

    meta_path = cfg.outdir / "meta" / f"{ts}__{base}.json"
    meta = {
        "timestamp": ts,
        "url": url,
        "status": status,
        "content_type": ctype,
        "headers": {k: v for k, v in headers.items()},
        "size_bytes": len(body_bytes),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ถ้าอยากเก็บ “แต่ JSON” เพียวๆ
    if cfg.json_only:
        if ("application/json" not in ctype) and (not ctype.endswith("+json")):
            return

    resp_dir = cfg.outdir / "responses"

    # JSON pretty
    if "application/json" in ctype or ctype.endswith("+json"):
        try:
            data = json.loads(body_bytes.decode("utf-8", errors="replace"))
            out_path = resp_dir / f"{ts}__{base}.json"
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[SAVE][json] {status} {url} -> {out_path.name}")
            return
        except Exception:
            # ถ้า decode/parse ไม่ได้ ก็ไหลไปแบบ text/binary
            pass

    # text-ish vs binary
    is_texty = any(x in ctype for x in ["text/", "application/javascript", "application/xml", "text/html"])
    if is_texty:
        out_path = resp_dir / f"{ts}__{base}.txt"
        out_path.write_text(body_bytes.decode("utf-8", errors="replace"), encoding="utf-8")
        print(f"[SAVE][txt] {status} {url} -> {out_path.name}")
    else:
        out_path = resp_dir / f"{ts}__{base}.bin"
        out_path.write_bytes(body_bytes)
        print(f"[SAVE][bin] {status} {url} -> {out_path.name}")


def goto_with_fallback(page, url: str, timeout_ms: int) -> None:
    # domcontentloaded -> load -> plain
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return
    except Exception as e1:
        print(f"[WARN] goto(domcontentloaded) failed: {e1}")

    try:
        page.goto(url, wait_until="load", timeout=timeout_ms)
        return
    except Exception as e2:
        print(f"[WARN] goto(load) failed: {e2}")

    page.goto(url, timeout=timeout_ms)


def launch_browser(p, browser_name: str, headless: bool, channel: Optional[str]):
    if browser_name == "chromium":
        if channel:
            return p.chromium.launch(headless=headless, channel=channel)
        return p.chromium.launch(
            headless=headless,
            args=[
                "--disable-quic",
                "--disable-blink-features=AutomationControlled",
            ],
        )
    if browser_name == "firefox":
        return p.firefox.launch(headless=headless)
    if browser_name == "webkit":
        return p.webkit.launch(headless=headless)
    raise ValueError(f"Unknown browser: {browser_name}")


def build_context(browser, cfg: RunConfig):
    context_kwargs = dict(
        user_agent=cfg.ua,
        ignore_https_errors=True,
        locale="en-US",
        timezone_id="America/New_York",
    )

    if cfg.save_har:
        har_path = cfg.outdir / "sofrwatch.har"
        context_kwargs.update(
            record_har_path=str(har_path),
            record_har_content="embed",
            record_har_mode="full",
        )
        print(f"[INFO] HAR enabled: {har_path.name}")

    context = browser.new_context(**context_kwargs)

    # ลด noise
    context.route("**/*", route_filter)

    return context


def attach_sniffer(page, cfg: RunConfig):
    def on_response(resp):
        try:
            url = resp.url
            status = resp.status
            headers = resp.headers
            body = resp.body()
            dump_response(cfg, url, status, headers, body)
        except Exception as e:
            print(f"[WARN] on_response error: {e}")

    page.on("response", on_response)


def try_open_with_engine(p, engine: str, cfg: RunConfig) -> Tuple[bool, str]:
    """
    returns (ok, used_engine)
    """
    browser = None
    context = None
    page = None

    try:
        browser = launch_browser(p, engine, cfg.headless, cfg.channel if engine == "chromium" else None)
        context = build_context(browser, cfg)
        page = context.new_page()
        attach_sniffer(page, cfg)

        print(f"[INFO] Opening: {TARGET_URL}")
        goto_with_fallback(page, TARGET_URL, timeout_ms=cfg.timeout_ms)

        # รอ XHR/fetch ยิงข้อมูล
        print(f"[INFO] Waiting {cfg.wait_s:.1f}s for XHR/fetch...")
        page.wait_for_timeout(int(cfg.wait_s * 1000))

        return True, engine

    except Exception as e:
        print(f"[WARN] Navigation failed on {engine}: {e}")
        # ถ้าเป็น error แบบ network/protocol ให้ caller ตัดสินใจ fallback
        if not is_fatal_nav_error(e):
            # ไม่ใช่ error กลุ่มที่เราตั้งใจ fallback ก็โยนต่อ (ให้รู้ว่าพังจริง)
            raise
        return False, engine

    finally:
        try:
            if context:
                context.close()
        except:
            pass
        try:
            if browser:
                browser.close()
        except:
            pass


def run(cfg: RunConfig) -> int:
    ensure_outdir(cfg.outdir)

    with sync_playwright() as p:
        used = cfg.browser

        # --- AUTO: chromium -> firefox -> webkit (optional) ---
        if cfg.browser == "auto":
            # 1) chromium
            ok, used = try_open_with_engine(p, "chromium", cfg)
            if ok:
                print(f"[DONE] Finished with {used}.")
                return 0

            print("[INFO] Fallback to firefox...")
            ok, used = try_open_with_engine(p, "firefox", cfg)
            if ok:
                print(f"[DONE] Finished with {used}.")
                return 0

            # ถ้าจะสุดทางค่อย webkit
            print("[INFO] Fallback to webkit...")
            ok, used = try_open_with_engine(p, "webkit", cfg)
            if ok:
                print(f"[DONE] Finished with {used}.")
                return 0

            raise RuntimeError("All engines failed (chromium/firefox/webkit).")

        # --- Specific engine ---
        ok, used = try_open_with_engine(p, cfg.browser, cfg)
        if not ok:
            raise RuntimeError(f"Failed to open with {used}. Try --browser firefox or --headless false.")
        print(f"[DONE] Finished with {used}.")
        return 0


def parse_args() -> RunConfig:
    ap = argparse.ArgumentParser(description="CME SOFRWatch Playwright response sniffer")
    ap.add_argument("--browser", choices=["auto", "chromium", "firefox", "webkit"], default="auto")
    ap.add_argument("--channel", choices=["chrome", "msedge"], default=None,
                    help="Chromium channel (use installed Chrome/Edge). Works only with --browser chromium/auto.")
    ap.add_argument("--headless", type=str, default="true", help="true/false")
    ap.add_argument("--wait_s", type=float, default=20.0)
    ap.add_argument("--outdir", type=str, default="sofrwatch_dump")
    ap.add_argument("--save_har", action="store_true")
    ap.add_argument("--ua", type=str, default=DEFAULT_UA)
    ap.add_argument("--strict_filter", action="store_true")
    ap.add_argument("--timeout_ms", type=int, default=60000)
    ap.add_argument("--json_only", action="store_true", help="Save only JSON responses (plus meta)")

    ns = ap.parse_args()
    headless = str(ns.headless).strip().lower() in {"1", "true", "yes", "y"}

    return RunConfig(
        browser=ns.browser,
        channel=ns.channel,
        headless=headless,
        wait_s=ns.wait_s,
        outdir=Path(ns.outdir),
        save_har=ns.save_har,
        ua=ns.ua,
        strict_filter=ns.strict_filter,
        timeout_ms=ns.timeout_ms,
        json_only=ns.json_only,
    )


if __name__ == "__main__":
    cfg = parse_args()
    print(f"[INFO] Browser: {cfg.browser} | channel={cfg.channel} | headless={cfg.headless}")
    print(f"[INFO] Outdir: {cfg.outdir.resolve()}")
    raise SystemExit(run(cfg))
