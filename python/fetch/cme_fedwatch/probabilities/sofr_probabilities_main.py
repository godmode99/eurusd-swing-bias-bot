import asyncio
import json
import re
import time
from pathlib import Path
from typing import Optional, List

from playwright.async_api import async_playwright


TARGET_URL = "https://www.cmegroup.com/markets/interest-rates/cme-sofrwatch.html"

# รอแบบตายตัวหลังโหลดหน้า (ตามที่มึงสั่ง)
WAIT_AFTER_GOTO_SECONDS = 10

# จำกัดขนาด body กันไฟล์บวม (อยากเก็บมากขึ้นก็เพิ่มได้)
MAX_BODY_BYTES = 8_000_000

# โฟลเดอร์ output
OUT_DIR = Path("dump_all")
OUT_DIR.mkdir(parents=True, exist_ok=True)

INDEX_JSON = OUT_DIR / "index.json"


def safe_bytes(raw: Optional[bytes], max_bytes: int = MAX_BODY_BYTES) -> bytes:
    if raw is None:
        return b""
    if len(raw) > max_bytes:
        return raw[:max_bytes] + b"\n...[TRUNCATED]..."
    return raw


def guess_ext(content_type: str, url: str) -> str:
    ct = (content_type or "").lower()
    if "application/json" in ct:
        return ".json"
    if "text/html" in ct:
        return ".html"
    if "javascript" in ct:
        return ".js"
    if "text/css" in ct:
        return ".css"
    if "image/" in ct:
        # เอานามสกุลจาก content-type
        sub = ct.split("image/")[-1].split(";")[0].strip()
        return "." + (sub if sub else "img")
    if "text/plain" in ct:
        return ".txt"

    # fallback จาก url
    m = re.search(r"\.([a-zA-Z0-9]{1,6})(\?|$)", url)
    if m:
        return "." + m.group(1)
    return ".bin"


def safe_filename(s: str, limit: int = 180) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:limit].strip("_")


async def goto_with_retry(page, url: str, retries: int = 5):
    last_err = None
    for i in range(1, retries + 1):
        try:
            # commit ให้ผ่านการเริ่มนำทางก่อน (ช่วยลด http2 งอแง)
            await page.goto(url, wait_until="commit", timeout=120_000)
            # แล้วค่อยรอ DOM
            await page.wait_for_load_state("domcontentloaded", timeout=60_000)
            return
        except Exception as e:
            last_err = e
            await page.wait_for_timeout(1500 * i)
    raise last_err


async def launch_best_browser(p):
    args = ["--disable-quic", "--disable-http2"]

    # พยายามใช้ Edge/Chrome ที่ติดเครื่องจริงก่อน
    for ch in ("msedge", "chrome"):
        try:
            b = await p.chromium.launch(headless=True, channel=ch, args=args)
            return b, f"chromium({ch})"
        except Exception:
            pass

    b = await p.chromium.launch(headless=True, args=args)
    return b, "chromium(playwright)"


async def main():
    saved: List[dict] = []
    errors: List[dict] = []
    counter = 0

    async with async_playwright() as p:
        browser, browser_tag = await launch_best_browser(p)

        context = await browser.new_context(
            java_script_enabled=True,
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1365, "height": 768},
        )
        page = await context.new_page()

        async def on_response(response):
            nonlocal counter
            counter += 1

            req = response.request
            rtype = req.resource_type

            try:
                headers = dict(response.headers)
            except Exception:
                headers = {}
            ct = headers.get("content-type", "")

            url = response.url
            status = response.status

            # อ่าน body (บางอย่างอ่านไม่ได้ เช่น streaming/บาง binary) ก็จับ error ไว้
            try:
                raw = await response.body()
                raw = safe_bytes(raw, MAX_BODY_BYTES)
                ext = guess_ext(ct, url)

                name = safe_filename(url)
                fname = f"{counter:05d}__{rtype}__{status}__{name}{ext}"
                fpath = OUT_DIR / fname
                fpath.write_bytes(raw)

                saved.append({
                    "i": counter,
                    "resource_type": rtype,
                    "status": status,
                    "content_type": ct,
                    "url": url,
                    "file": str(fpath),
                    "bytes": len(raw),
                })
            except Exception as e:
                errors.append({
                    "i": counter,
                    "resource_type": rtype,
                    "status": status,
                    "content_type": ct,
                    "url": url,
                    "error": f"{type(e).__name__}: {e}",
                })

        page.on("response", lambda res: asyncio.create_task(on_response(res)))

        # ไปหน้า + retry กัน http2
        await goto_with_retry(page, TARGET_URL, retries=5)

        # รอแบบตายตัว 10 วิ (ตามที่มึงขอ)
        await page.wait_for_timeout(int(WAIT_AFTER_GOTO_SECONDS * 2000))

        # dump index
        index = {
            "target_url": TARGET_URL,
            "browser": browser_tag,
            "wait_after_goto_seconds": WAIT_AFTER_GOTO_SECONDS,
            "max_body_bytes": MAX_BODY_BYTES,
            "saved_count": len(saved),
            "error_count": len(errors),
            "saved": saved,
            "errors": errors,
        }
        INDEX_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

        await context.close()
        await browser.close()

    print(f"[OK] dump dir: {OUT_DIR.resolve()}")
    print(f"[OK] index:    {INDEX_JSON.resolve()}")
    print(f"[OK] saved:    {len(saved)} files")
    print(f"[OK] errors:   {len(errors)}")
    print("Tip: เปิด index.json แล้ว search 'application/json' หรือ '.json' เพื่อหาไฟล์ข้อมูลไวๆ")


if __name__ == "__main__":
    asyncio.run(main())
