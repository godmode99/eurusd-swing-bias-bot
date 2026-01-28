from __future__ import annotations

import csv
import json
import os
import sys
import getpass
from enum import Enum
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_AUTH_URL = "https://login.cmegroup.com/sso/accountstatus/showAuth.action"
DEFAULT_WATCHLIST_URL = "https://www.cmegroup.com/watchlists/details.1769586889025783750.C.html"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "Data" / "raw_data" / "cme"
NAV_TIMEOUT = 60_000

class AuthState(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    UNAUTHORIZED_OR_EXPIRED = "UNAUTHORIZED_OR_EXPIRED"
    UNKNOWN = "UNKNOWN"

def load_config() -> dict:
    cfg_path = Path(__file__).with_name("config.json")
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def pick_creds(cfg: dict):
    # 1) config.json
    user = (cfg.get("username") or "").strip()
    pwd  = (cfg.get("password") or "").strip()

    # 2) env fallback
    if not user:
        user = os.environ.get("CME_USER", "").strip()
    if not pwd:
        pwd = os.environ.get("CME_PASS", "").strip()

    # 3) prompt fallback
    if not user:
        user = input("CME username/email: ").strip()
    if not pwd:
        pwd = getpass.getpass("CME password: ").strip()

    return user, pwd

def is_login_page(page) -> bool:
    # จาก HTML ที่มึงแปะมา: #user, #pwd, #loginBtn
    return (
        page.locator("#user").count() > 0
        and page.locator("#pwd").count() > 0
        and page.locator("#loginBtn").count() > 0
    )

def detect_state(page, response_text: str | None = None) -> AuthState:
    text_upper = (response_text or "").upper()
    if "AUTHENTICATED" in text_upper:
        return AuthState.AUTHENTICATED
    if "LOGIN_REQUIRED" in text_upper:
        return AuthState.LOGIN_REQUIRED
    if "UNAUTHORIZED" in text_upper or "EXPIRED" in text_upper:
        return AuthState.UNAUTHORIZED_OR_EXPIRED

    # รอให้หน้า render นิดนึง กัน false positive
    try:
        page.wait_for_function(
            """() => {
                const u = document.querySelector('#user');
                const p = document.querySelector('#pwd');
                const b = document.querySelector('#loginBtn');
                const txt = document.body ? document.body.innerText.toLowerCase() : '';
                return (u && p && b) || txt.includes('session has expired') || txt.includes('unauthorized');
            }""",
            timeout=10_000
        )
    except:
        pass

    if is_login_page(page):
        return AuthState.LOGIN_REQUIRED

    # ถ้าไม่เจอ login form ก็ถือว่า authenticated สำหรับ showAuth URL
    body_txt = ""
    try:
        body_txt = page.locator("body").inner_text(timeout=2000).lower()
    except:
        body_txt = ""

    if "session has expired" in body_txt or "unauthorized" in body_txt:
        return AuthState.UNAUTHORIZED_OR_EXPIRED

    # ยังไงก็ไม่น่า UNKNOWN มาก แต่เผื่อไว้
    return AuthState.AUTHENTICATED

def save_debug(page, prefix="debug"):
    try:
        page.screenshot(path=f"{prefix}.png", full_page=True)
        print(f"📸 saved: {prefix}.png")
    except:
        pass
    try:
        html = page.content()
        with open(f"{prefix}.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"🧾 saved: {prefix}.html")
    except:
        pass

def resolve_output_paths(cfg: dict) -> dict[str, Path]:
    output_dir = Path(cfg.get("watchlist_output_dir", DEFAULT_OUTPUT_DIR))
    output_dir.mkdir(parents=True, exist_ok=True)

    html_output = Path(cfg.get("watchlist_output", output_dir / "watchlist.html"))
    json_output = Path(cfg.get("watchlist_json_output", output_dir / "watchlist.json"))
    csv_output = Path(cfg.get("watchlist_csv_output", output_dir / "watchlist.csv"))

    if not html_output.is_absolute():
        html_output = output_dir / html_output
    if not json_output.is_absolute():
        json_output = output_dir / json_output
    if not csv_output.is_absolute():
        csv_output = output_dir / csv_output

    return {
        "output_dir": output_dir,
        "html_output": html_output,
        "json_output": json_output,
        "csv_output": csv_output,
    }

def fetch_watchlist_html(page, cfg: dict) -> None:
    watchlist_url = (cfg.get("watchlist_url") or DEFAULT_WATCHLIST_URL).strip()
    outputs = resolve_output_paths(cfg)
    output_path = outputs["html_output"]
    json_output = outputs["json_output"]
    csv_output = outputs["csv_output"]

    try:
        page.goto(watchlist_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.wait_for_timeout(1200)
    except PlaywrightTimeoutError:
        print(f"❌ goto watchlist timeout: {watchlist_url}")
        save_debug(page, "watchlist_timeout")
        return

    table_data = extract_watchlist_table(page)
    if table_data is None:
        print("⚠️ watchlist table not found")
    else:
        headers, rows = table_data
        if rows:
            save_table_as_json(headers, rows, json_output)
            save_table_as_csv(headers, rows, csv_output)
        else:
            print("⚠️ watchlist table found but no rows to export")

    try:
        html = page.content()
    except Exception as exc:
        print(f"❌ read watchlist HTML failed: {exc}")
        save_debug(page, "watchlist_read_failed")
        return

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✅ saved watchlist html: {output_path}")
    except Exception as exc:
        print(f"❌ write watchlist HTML failed: {exc}")
        save_debug(page, "watchlist_write_failed")
        return

def extract_watchlist_table(page) -> tuple[list[str], list[list[str]]] | None:
    selectors = [".watchlist-table", ".watchlist-products table", "table"]
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=10_000)
        except PlaywrightTimeoutError:
            continue
        table_data = page.evaluate(
            """(sel) => {
                const table = document.querySelector(sel);
                if (!table) return null;

                if (table.classList.contains('watchlist-table')) {
                    const headers = [
                        'Name',
                        'Code',
                        'Expiry',
                        'Chart URL',
                        'Last Price',
                        'Change',
                        'High',
                        'Low',
                        'Open',
                        'Volume',
                        'Contract Code',
                        'Front Month',
                        'Product URL',
                    ];

                    const rows = Array.from(table.querySelectorAll('.tbody .tr')).map(row => {
                        const nameCell = row.querySelector('.first-column .table-cell.month-code');
                        let name = '';
                        let code = '';
                        if (nameCell) {
                            const lines = nameCell.innerText
                                .split('\\n')
                                .map(line => line.trim())
                                .filter(Boolean);
                            if (lines.length > 0) name = lines[0];
                            if (lines.length > 1) code = lines[lines.length - 1];
                        }

                        const codeAnchor = row.querySelector('.first-column a.code');
                        if (codeAnchor && codeAnchor.innerText.trim()) {
                            code = codeAnchor.innerText.trim();
                        }
                        const productUrl = codeAnchor ? codeAnchor.href : '';

                        const expiryCell = row.querySelector('.second-column .expiration-month');
                        const expiry = expiryCell ? expiryCell.innerText.trim() : '';

                        const contractInput = row.querySelector('input[data-contract-code]');
                        const contractCode = contractInput
                            ? contractInput.getAttribute('data-contract-code') || ''
                            : '';
                        const isFrontMonth = contractInput
                            ? (contractInput.getAttribute('data-is-front-month') === 'true')
                            : false;

                        const chartAnchor = row.querySelector('.third-column a[data-code]');
                        const chartUrl = chartAnchor ? chartAnchor.href : '';

                        const valueCells = Array.from(
                            row.querySelectorAll('.third-column .table-cell')
                        ).map(cell => cell.innerText.trim());

                        const lastPrice = valueCells[1] || '';
                        const change = valueCells[2] || '';
                        const high = valueCells[3] || '';
                        const low = valueCells[4] || '';
                        const open = valueCells[5] || '';
                        const volume = valueCells[6] || '';

                        return [
                            name,
                            code,
                            expiry,
                            chartUrl,
                            lastPrice,
                            change,
                            high,
                            low,
                            open,
                            volume,
                            contractCode,
                            isFrontMonth ? 'true' : 'false',
                            productUrl,
                        ];
                    });

                    return { headers, rows };
                }

                const headers = Array.from(table.querySelectorAll('thead th'))
                    .map(th => th.innerText.trim())
                    .filter(Boolean);
                const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr => {
                    return Array.from(tr.querySelectorAll('th, td'))
                        .map(td => td.innerText.trim());
                });
                return { headers, rows };
            }""",
            selector,
        )
        if table_data and table_data.get("rows"):
            headers = table_data.get("headers") or []
            rows = table_data.get("rows") or []
            return headers, rows
    return None

def save_table_as_json(headers: list[str], rows: list[list[str]], output_path: Path) -> None:
    payload = []
    if headers:
        for row in rows:
            item = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
            payload.append(item)
    else:
        payload = rows

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"✅ saved watchlist json: {output_path}")
    except Exception as exc:
        print(f"❌ write watchlist json failed: {exc}")

def save_table_as_csv(headers: list[str], rows: list[list[str]], output_path: Path) -> None:
    try:
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if headers:
                writer.writerow(headers)
            writer.writerows(rows)
        print(f"✅ saved watchlist csv: {output_path}")
    except Exception as exc:
        print(f"❌ write watchlist csv failed: {exc}")

def main():
    cfg = load_config()

    auth_url = (cfg.get("auth_url") or DEFAULT_AUTH_URL).strip()
    user_data_dir = (cfg.get("user_data_dir") or os.environ.get("CME_USER_DATA_DIR") or "cme_profile").strip()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
        )
        page = context.new_page()

        # 1) เริ่มที่ auth_url เสมอ
        try:
            response = page.goto(auth_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(1200)
        except PlaywrightTimeoutError:
            print("❌ goto auth_url timeout")
            save_debug(page, "auth_timeout")
            context.close()
            sys.exit(1)

        response_text = None
        if response is not None:
            try:
                response_text = response.text()
            except Exception:
                response_text = None
        state = detect_state(page, response_text=response_text)
        print(f"STATE: {state} | url={page.url}")

        if state == AuthState.AUTHENTICATED:
            print("✅ Already logged in")
            fetch_watchlist_html(page, cfg)
            context.close()
            return

        # 2) ต้อง login
        print("⚠️ Need login -> จะพยายามกรอกให้")
        user, pwd = pick_creds(cfg)

        try:
            page.wait_for_selector("#user", timeout=20_000)
            page.wait_for_selector("#pwd", timeout=20_000)
            page.wait_for_selector("#loginBtn", timeout=20_000)

            page.fill("#user", user)
            page.fill("#pwd", pwd)
            page.click("#loginBtn")

            # อาจติด reCAPTCHA/MFA -> ให้ทำเองได้
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except:
                pass

        except Exception as e:
            print(f"❌ Error while filling login: {e}")

        # 3) เช็คซ้ำด้วย auth_url
        response = page.goto(auth_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.wait_for_timeout(1200)
        response_text = None
        if response is not None:
            try:
                response_text = response.text()
            except Exception:
                response_text = None
        state2 = detect_state(page, response_text=response_text)
        print(f"AFTER LOGIN STATE: {state2} | url={page.url}")

        if state2 == AuthState.AUTHENTICATED:
            print("✅ Login success")
            fetch_watchlist_html(page, cfg)
            context.close()
            return

        print("❌ ยังไม่สำเร็จ (อาจติด reCAPTCHA/MFA/OTP หรือรหัสผิด)")
        print("➡️ ไปทำขั้นตอนบน browser ให้ผ่าน แล้วกลับมากด Enter เพื่อเช็คซ้ำ")
        input()

        response = page.goto(auth_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.wait_for_timeout(1200)
        response_text = None
        if response is not None:
            try:
                response_text = response.text()
            except Exception:
                response_text = None
        state3 = detect_state(page, response_text=response_text)
        print(f"AFTER MANUAL STATE: {state3} | url={page.url}")

        if state3 == AuthState.AUTHENTICATED:
            print("✅ Success after manual")
            fetch_watchlist_html(page, cfg)
            context.close()
            return

        save_debug(page, "auth_failed")
        context.close()
        sys.exit(2)

if __name__ == "__main__":
    main()
