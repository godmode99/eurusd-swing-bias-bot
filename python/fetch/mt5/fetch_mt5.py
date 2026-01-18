from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

import pandas as pd

# ต้องติดตั้ง: pip install MetaTrader5 pandas
import MetaTrader5 as mt5


TF_MAP = {
    "D1": mt5.TIMEFRAME_D1,
    "H4": mt5.TIMEFRAME_H4,
}


@dataclass
class MT5FetchResult:
    df: pd.DataFrame
    latest_time_utc: str
    rows: int


class MT5Client:
    def __init__(self, terminal_path: Optional[str] = None):
        self.terminal_path = terminal_path

    def connect(self) -> None:
        ok = mt5.initialize(path=self.terminal_path) if self.terminal_path else mt5.initialize()
        if not ok:
            raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")

        # ตรวจว่าเชื่อมต่อได้จริง
        ti = mt5.terminal_info()
        ai = mt5.account_info()
        if ti is None:
            raise RuntimeError("MT5 terminal_info() returned None (terminal not ready?)")
        if ai is None:
            # บางกรณี terminal เปิดแต่ยังไม่ล็อกอิน
            raise RuntimeError("MT5 account_info() returned None (not logged in?)")

    def shutdown(self) -> None:
        mt5.shutdown()

    def ensure_symbol(self, symbol: str) -> None:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol_info({symbol}) is None. Symbol not found in MT5.")
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                raise RuntimeError(f"symbol_select({symbol}, True) failed")

    def fetch_rates(self, symbol: str, timeframe: str, bars: int, store_time_as_utc: bool = True) -> MT5FetchResult:
        if timeframe not in TF_MAP:
            raise ValueError(f"Unsupported timeframe: {timeframe}. Use one of {list(TF_MAP.keys())}")

        self.ensure_symbol(symbol)

        tf = TF_MAP[timeframe]
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"copy_rates_from_pos returned empty for {symbol} {timeframe}")

        df = pd.DataFrame(rates)
        # MT5 returns 'time' as POSIX seconds in terminal timezone context; treat as UTC seconds safely
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)

        # Normalize columns
        df = df.rename(columns={
            "time": "time_utc",
            "tick_volume": "tick_volume",
            "real_volume": "real_volume",
            "spread": "spread",
        })

        # Keep only common columns
        keep = ["time_utc", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
        for col in keep:
            if col not in df.columns:
                df[col] = None
        df = df[keep].copy()

        # Sort and drop duplicates
        df = df.sort_values("time_utc").drop_duplicates(subset=["time_utc"], keep="last").reset_index(drop=True)

        latest_time = df["time_utc"].iloc[-1]
        latest_iso = latest_time.to_pydatetime().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        # Option: store as naive UTC string in CSV (easy to parse)
        if not store_time_as_utc:
            # If user wants server time, they'd handle it; default is UTC
            pass

        return MT5FetchResult(df=df, latest_time_utc=latest_iso, rows=len(df))
