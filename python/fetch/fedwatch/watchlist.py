from __future__ import annotations

import csv
import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .config import DEFAULT_WATCHLIST_URL, NAV_TIMEOUT, resolve_output_paths
from .debug import save_debug


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
