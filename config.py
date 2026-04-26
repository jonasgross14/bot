"""
Globale Konfiguration des Auction-Theory-Bots.

Werte werden aus einer .env-Datei geladen (siehe .env.example). Alle Strings
sind bewusst zentralisiert, damit du den Bot ohne Code-Änderungen auf
andere Pairs / Timeframes / Börsen umstellen kannst.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _get_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    # ----- Markt / Pair -----
    symbol: str = os.getenv("SYMBOL", "BTC/USDT")
    # Spot-Symbol (optional, fuer CVD-Vergleich Spot vs. Perp)
    spot_symbol: str = os.getenv("SPOT_SYMBOL", "BTC/USDT")
    # Perpetual-Symbol fuer ccxt (Binance Perp = BTC/USDT:USDT)
    perp_symbol: str = os.getenv("PERP_SYMBOL", "BTC/USDT:USDT")

    exchange: str = os.getenv("EXCHANGE", "binance")  # binance, bybit, ...
    market_type: str = os.getenv("MARKET_TYPE", "future")  # spot | future

    # ----- Timeframes -----
    timeframes: List[str] = field(
        default_factory=lambda: _get_list(
            "TIMEFRAMES", ["5m", "15m", "30m", "1h", "4h", "1d"]
        )
    )
    primary_timeframe: str = os.getenv("PRIMARY_TIMEFRAME", "30m")
    profile_timeframe: str = os.getenv("PROFILE_TIMEFRAME", "30m")
    profile_lookback_days: int = _get_int("PROFILE_LOOKBACK_DAYS", 1)

    # ----- Volume Profile -----
    vp_num_bins: int = _get_int("VP_NUM_BINS", 80)
    value_area_percent: float = _get_float("VALUE_AREA_PERCENT", 0.70)
    hvn_threshold: float = _get_float("HVN_THRESHOLD", 1.5)  # x mean volume
    lvn_threshold: float = _get_float("LVN_THRESHOLD", 0.4)  # x mean volume

    # ----- Market Profile -----
    tpo_size_minutes: int = _get_int("TPO_SIZE_MINUTES", 30)
    initial_balance_periods: int = _get_int("INITIAL_BALANCE_PERIODS", 2)  # 2x30m=1h
    session_start_utc: str = os.getenv("SESSION_START_UTC", "00:00")
    session_length_hours: int = _get_int("SESSION_LENGTH_HOURS", 24)

    # ----- Orderflow -----
    oi_lookback_minutes: int = _get_int("OI_LOOKBACK_MINUTES", 60)
    cvd_lookback_minutes: int = _get_int("CVD_LOOKBACK_MINUTES", 60)

    # ----- Modus -----
    mode: str = os.getenv("MODE", "live")  # live | backtest
    live_interval_seconds: int = _get_int("LIVE_INTERVAL_SECONDS", 300)  # alle 5 min
    backtest_start: str = os.getenv("BACKTEST_START", "2024-01-01")
    backtest_end: str = os.getenv("BACKTEST_END", "2024-01-07")

    # ----- API Keys (optional, fuer Public-Daten nicht zwingend noetig) -----
    api_key: str = os.getenv("API_KEY", "")
    api_secret: str = os.getenv("API_SECRET", "")

    # ----- Output -----
    output_dir: str = os.getenv("OUTPUT_DIR", "./output")
    save_text: bool = _get_bool("SAVE_TEXT", True)
    save_chart: bool = _get_bool("SAVE_CHART", True)
    chart_engine: str = os.getenv("CHART_ENGINE", "matplotlib")  # matplotlib | plotly

    # ----- Logging -----
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def ensure_output_dir(self) -> None:
        os.makedirs(self.output_dir, exist_ok=True)


CONFIG = Config()
