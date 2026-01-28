from __future__ import annotations

import argparse
import json
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ART_DIR = Path("artifacts") / "fedwatch"
LATEST_DIR = ART_DIR / "latest"
RUNS_DIR = ART_DIR / "runs"


@dataclass
class ExtractResult:
    asof_utc: str
    source: str
    asof_text: str | None
    meetings: list[dict[str, Any]]
    tables: list[list[list[str]]]
    next_data: dict[str, Any] | None
    extracted_from: str
    notes: list[str]


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir:
        return Path(args.run_dir)
    return LATEST_DIR


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag == "table":
            self._in_table = True
            self._current_table = []
        if self._in_table and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []
        if self._in_table and tag == "tr":
            self._current_row = []

    def handle_endtag(self, tag: str):
        if self._in_table and tag in {"td", "th"}:
            self._in_cell = False
            cell_text = "".join(self._cell_parts).strip()
            self._current_row.append(re.sub(r"\s+", " ", cell_text))
        if self._in_table and tag == "tr":
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = []
        if tag == "table" and self._in_table:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = []
            self._in_table = False

    def handle_data(self, data: str):
        if self._in_cell:
            self._cell_parts.append(data)


def _parse_probability(cell: str) -> float | None:
    if not cell:
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)", cell.replace(",", ""))
    if not match:
        return None
    value = float(match.group(1))
    if "%" in cell:
        return value / 100.0
    if value > 1.0:
        return value / 100.0
    return value


def _parse_meeting_date(cell: str) -> str:
    text = cell.strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def _extract_tables(html: str) -> list[list[list[str]]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.tables


def _extract_asof_text(html: str) -> str | None:
    match = re.search(r"As of\s+([^<\n]+)", html, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_next_data(html: str) -> dict[str, Any] | None:
    match = re.search(r"<script[^>]+id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>", html, re.DOTALL)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _extract_meetings_from_tables(tables: list[list[list[str]]]) -> list[dict[str, Any]]:
    meetings: list[dict[str, Any]] = []
    for table in tables:
        if not table:
            continue
        header = table[0]
        if not header:
            continue
        header_lower = [h.lower() for h in header]
        if not any("meeting" in h for h in header_lower):
            continue
        rate_ranges = header[1:]
        if not rate_ranges:
            continue
        for row in table[1:]:
            if len(row) < 2:
                continue
            meeting_date = _parse_meeting_date(row[0])
            distribution = []
            for idx, cell in enumerate(row[1:]):
                prob = _parse_probability(cell)
                if prob is None:
                    continue
                distribution.append(
                    {
                        "rate_range": rate_ranges[idx].strip(),
                        "prob": prob,
                    }
                )
            if distribution:
                meetings.append(
                    {
                        "meeting_date": meeting_date,
                        "distribution": distribution,
                    }
                )
    return meetings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default="")
    args = parser.parse_args()

    run_dir = _parse_run_dir(args)
    run_dir.mkdir(parents=True, exist_ok=True)

    in_html = run_dir / "page.html"
    if not in_html.exists():
        raise FileNotFoundError(f"Missing input HTML: {in_html.resolve()}")

    html = in_html.read_text(encoding="utf-8", errors="ignore")

    notes: list[str] = []
    tables = _extract_tables(html)
    meetings = _extract_meetings_from_tables(tables)

    next_data = _extract_next_data(html)
    if next_data:
        notes.append("Found __NEXT_DATA__ JSON payload")
    else:
        notes.append("No __NEXT_DATA__ payload found")

    result = ExtractResult(
        asof_utc=_iso_utc_now(),
        source="fedwatch",
        asof_text=_extract_asof_text(html),
        meetings=meetings,
        tables=tables,
        next_data=next_data,
        extracted_from=str(in_html.resolve()),
        notes=notes,
    )

    out_raw = run_dir / "raw.json"
    out_meta = run_dir / "raw.meta.json"

    out_raw.write_text(json.dumps(result.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")
    out_meta.write_text(
        json.dumps(
            {
                "generated_at_utc": _iso_utc_now(),
                "input_html": str(in_html.resolve()),
                "tables_found": len(tables),
                "meetings_found": len(meetings),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        err_path = RUNS_DIR / "extract_error.txt"
        err_path.write_text(traceback.format_exc(), encoding="utf-8")
        print("ERROR saved ->", str(err_path.resolve()), flush=True)
        raise
