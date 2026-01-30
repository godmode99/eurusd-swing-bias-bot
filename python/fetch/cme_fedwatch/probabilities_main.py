# python/fetch/cme_fedwatch/probabilities_main.py
import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, Response, Error as PWError


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def safe_name(s: str, max_len: int = 120) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:max_len].strip("_") or "resp"


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


async def dump_response(resp: Response, out_dir: Path) -> Optional[Path]:
    """
    Save XHR/fetch responses to disk.
    - If JSON: save pretty JSON
    - Else: save text (best-effort)
    """
    try:
        req = resp.request
        rtype = req.resource_type
        url = resp.url
        status = resp.status
        headers = await resp.all_headers()
        ctype = headers.get("content-type", "") or headers.get("Content-Type", "")

        # we only care about network data, not images/css/fonts
        if rtype not in ("xhr", "fetch", "document"):
            return None

        # Skip obvious static assets even if misclassified
        if any(url.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".woff", ".woff2", ".ttf")):
            return None

        # Create a stable-ish filename
        base = safe_name(f"{status}_{rtype}_{url.split('?')[0].split('/')[-1]}")
        suffix = ".json" if "json" in ctype.lower() else ".txt"
        path = out_dir / f"{base}_{utc_stamp()}{suffix}"

        # Try JSON first if content-type suggests it, otherwise try text.
        if "json" in ctype.lower():
            data = await resp.json()
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return path

        # Some endpoints lie about content-type; try parse json anyway
        body = await resp.text()
        body_strip = body.strip()
        if (body_strip.startswith("{") and body_strip.endswith("}")) or (body_strip.startswith("[") and body_strip.endswith("]")):
            try:
                data = json.loads(body_strip)
                path = path.with_suffix(".json")
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                return path
            except Exception:
                pass

        path.write_text(body, encoding="utf-8", errors="replace")
        return path

    except Exception:
        return None


async def attach_sniffer(page: Page, out_dir: Path) -> None:
    async def on_response(resp: Response) -> None:
        saved = await dump_response(resp, out_dir)
        if saved:
            print(f"[CAPTURE] {resp.status} {resp.request.resource_type:8s} -> {saved.name}")

    page.on("response", on_response)


async def goto_with_fallback(page: Page, url: str, timeout_ms: int) -> None:
    """
    Try goto. If domcontentloaded fails, try load event. Then try plain goto.
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return
    except PWError as e:
        print(f"[WARN] goto(domcontentloaded) failed: {e}")

    try:
        await page.goto(url, wait_until="load", timeout=timeout_ms)
        return
    except PWError as e:
        print(f"[WARN] goto(load) failed: {e}")

    # last attempt
    await page.goto(url, timeout=timeout_ms)


async def run_once(
    browser_name: str,
    url: str,
    out_dir: Path,
    wait_s: int,
    save_har: bool,
    timeout_ms: int,
    headed: bool,
) -> None:
    ensure_dir(out_dir)

    async with async_playwright() as p:
        bt = {"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}[browser_name]

        launch_args = [
            "--disable-quic",
            # Some environments choke on H2; these flags may or may not help depending on Chromium version.
            "--disable-http2",
            "--disable-features=NetworkService,UseDnsHttpsSvcb,EncryptedClientHello",
        ] if browser_name == "chromium" else []

        print(f"[INFO] Launching {browser_name} (headed={headed})")
        browser: Browser = await bt.launch(
            headless=not headed,
            args=launch_args if launch_args else None,
        )

        har_path = out_dir / f"fedwatch_{browser_name}_{utc_stamp()}.har" if save_har else None
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            ignore_https_errors=True,
            record_har_path=str(har_path) if har_path else None,
            record_har_content="embed" if har_path else None,
        )
        page = await context.new_page()

        # Optional: reduce noise; keep XHR/fetch/document
        async def route_filter(route, request):
            rtype = request.resource_type
            if rtype in ("image", "media", "font"):
                return await route.abort()
            return await route.continue_()

        await context.route("**/*", route_filter)

        await attach_sniffer(page, out_dir)

        print(f"[INFO] Opening: {url}")
        await goto_with_fallback(page, url, timeout_ms=timeout_ms)

        # wait for iframe + XHR to fire
        print(f"[INFO] Waiting {wait_s}s to capture network…")
        await page.wait_for_timeout(wait_s * 1000)

        await context.close()
        await browser.close()

        if har_path:
            print(f"[INFO] HAR saved: {har_path}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html")
    ap.add_argument("--out", default="artifacts/cme_fedwatch_capture")
    ap.add_argument("--wait", type=int, default=20)
    ap.add_argument("--save_har", action="store_true")
    ap.add_argument("--timeout_ms", type=int, default=60000)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--browser", choices=["auto", "chromium", "firefox", "webkit"], default="auto")
    args = ap.parse_args()

    out_dir = Path(args.out)
    ensure_dir(out_dir)

    browsers = ["chromium", "firefox"] if args.browser == "auto" else [args.browser]

    last_err = None
    for b in browsers:
        try:
            await run_once(
                browser_name=b,
                url=args.url,
                out_dir=out_dir,
                wait_s=args.wait,
                save_har=args.save_har,
                timeout_ms=args.timeout_ms,
                headed=args.headed,
            )
            print("[DONE] capture complete.")
            return
        except PWError as e:
            last_err = e
            print(f"[FAIL] {b} failed: {e}")
        except Exception as e:
            last_err = e
            print(f"[FAIL] {b} failed (non-playwright): {e}")

    raise SystemExit(f"All browsers failed. Last error: {last_err}")


if __name__ == "__main__":
    asyncio.run(main())
