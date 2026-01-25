from playwright.sync_api import sync_playwright
import json, re

URL = "https://www.forexfactory.com/calendar"

# คีย์เวิร์ดช่วยกรอง URL ที่น่าสงสัย
SUSPECT_PATTERNS = [
    r"calendar",
    r"ff_calendar",
    r"faireconomy",
    r"nfs\.faireconomy\.media",
]

def is_suspect(url: str) -> bool:
    u = url.lower()
    return any(re.search(p, u) for p in SUSPECT_PATTERNS)

def run():
    hits = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(resp):
            try:
                url = resp.url
                ct  = (resp.headers.get("content-type") or "").lower()
                if is_suspect(url) or ("json" in ct or "xml" in ct or "csv" in ct):
                    # บาง response ใหญ่/ช้า อย่าดึง body ทุกตัว
                    size = int(resp.headers.get("content-length") or 0)
                    hits.append({
                        "url": url,
                        "status": resp.status,
                        "content_type": ct,
                        "size": size,
                    })
            except:
                pass

        page.on("response", on_response)

        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)

        browser.close()

    # เรียงให้ดูง่าย
    hits_sorted = sorted(hits, key=lambda x: (("json" not in x["content_type"]), -x["size"]))
    print(json.dumps(hits_sorted[:60], indent=2, ensure_ascii=False))

if __name__ == "__main__":
    run()
