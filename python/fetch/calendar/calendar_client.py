from __future__ import annotations

import requests
from datetime import date
from typing import Any, Dict, List, Optional

from utils import NonRetryableError

FMP_ENDPOINT = "https://financialmodelingprep.com/stable/economic-calendar"


def fetch_fmp_calendar(
    api_key: Optional[str],
    date_from: date,
    date_to: date,
    timeout_seconds: int = 30,
) -> List[Dict[str, Any]]:
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("Missing FMP API key. Set FMP_API_KEY in .env or calendar.api_key in config.yaml")

    params = {
        "from": date_from.strftime("%Y-%m-%d"),
        "to": date_to.strftime("%Y-%m-%d"),
        "apikey": key,  # FMP requires apikey param :contentReference[oaicite:2]{index=2}
    }

    r = requests.get(FMP_ENDPOINT, params=params, timeout=timeout_seconds)
    if r.status_code == 402:
        raise NonRetryableError(
            "FMP API returned 402 Payment Required. The economic calendar endpoint needs a paid plan "
            "or a valid API key with access."
        )
    if r.status_code in {401, 403}:
        raise NonRetryableError(
            f"FMP API returned {r.status_code} (Unauthorized). Check that your API key has access "
            "to the economic calendar endpoint."
        )
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected response type from FMP calendar: {type(data)}")

    return data


def normalize_impact(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    # normalize common variants
    s_low = s.lower()
    if "high" in s_low:
        return "High"
    if "med" in s_low:
        return "Medium"
    if "low" in s_low:
        return "Low"
    return s  # fallback


def normalize_currency(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip().upper()
