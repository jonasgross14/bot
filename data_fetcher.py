"""
Daten-Beschaffung fuer den Bot.

Verantwortlichkeiten:
- OHLCV-Kerzen (Spot + Perp) ueber ccxt holen
- Trade-Tape (aggregierte Trades) holen, getrennt nach Spot und Perp
- Open-Interest Historie holen (Binance: fapiData / Bybit: v5/market/...)
- Helfer fuer Backtesting (Zeitraeume in ms umrechnen, paginieren)

Hinweis: Fuer reine Public-Daten brauchst du KEINE API-Keys.
Fuer Live-Modus reichen die ccxt-REST-Endpunkte; Websockets werden im
main.py optional gestartet, sind aber nicht zwingend noetig.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import ccxt
import pandas as pd
import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Hilfsfunktionen
# ---------------------------------------------------------------------------
def _to_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


# ---------------------------------------------------------------------------
#  DataFetcher
# ---------------------------------------------------------------------------
@dataclass
class DataFetcher:
    exchange_id: str = "binance"
    symbol: str = "BTC/USDT"
    perp_symbol: str = "BTC/USDT:USDT"
    spot_symbol: str = "BTC/USDT"
    api_key: str = ""
    api_secret: str = ""

    def __post_init__(self) -> None:
        klass = getattr(ccxt, self.exchange_id)
        params = {
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
        if self.api_key and self.api_secret:
            params["apiKey"] = self.api_key
            params["secret"] = self.api_secret
        self.perp_client = klass(params)

        spot_params = dict(params)
        spot_params["options"] = {"defaultType": "spot"}
        self.spot_client = klass(spot_params)

    # ----- OHLCV -----
    def fetch_ohlcv(
        self,
        timeframe: str = "30m",
        since_ms: Optional[int] = None,
        limit: int = 1500,
        market: str = "perp",
    ) -> pd.DataFrame:
        """Holt OHLCV-Kerzen. market: perp | spot."""
        client = self.perp_client if market == "perp" else self.spot_client
        sym = self.perp_symbol if market == "perp" else self.spot_symbol
        rows: List[list] = []
        cursor = since_ms
        while True:
            chunk = client.fetch_ohlcv(sym, timeframe=timeframe, since=cursor, limit=limit)
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < limit:
                break
            cursor = chunk[-1][0] + 1
            if since_ms is None:
                break  # nur einen Batch holen, falls kein Startpunkt definiert
            time.sleep(client.rateLimit / 1000)
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        if df.empty:
            return df
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
        return df

    # ----- Trades -----
    def fetch_trades(
        self,
        since_ms: Optional[int] = None,
        until_ms: Optional[int] = None,
        market: str = "perp",
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Holt aggregierte Trades. Fuer CVD."""
        client = self.perp_client if market == "perp" else self.spot_client
        sym = self.perp_symbol if market == "perp" else self.spot_symbol
        rows: List[dict] = []
        cursor = since_ms
        end = until_ms or int(time.time() * 1000)
        while True:
            try:
                chunk = client.fetch_trades(sym, since=cursor, limit=limit)
            except Exception as exc:  # ccxt kann bei Rate-Limits schreien
                logger.warning("fetch_trades fehlgeschlagen: %s", exc)
                break
            if not chunk:
                break
            rows.extend(chunk)
            last_ts = chunk[-1]["timestamp"]
            if last_ts >= end or len(chunk) < limit:
                break
            cursor = last_ts + 1
            time.sleep(client.rateLimit / 1000)
        if not rows:
            return pd.DataFrame(
                columns=["timestamp", "datetime", "price", "amount", "side", "cost"]
            )
        df = pd.DataFrame(
            [
                {
                    "timestamp": t["timestamp"],
                    "price": float(t["price"]),
                    "amount": float(t["amount"]),
                    "side": t.get("side", "buy"),
                    "cost": float(t.get("cost") or t["price"] * t["amount"]),
                }
                for t in rows
            ]
        )
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    # ----- Open Interest -----
    def fetch_open_interest_hist(
        self,
        period: str = "5m",
        limit: int = 200,
    ) -> pd.DataFrame:
        """
        Holt Open-Interest-Historie in Coins (sumOpenInterest).
        Aktuell direkt gegen Binance Futures (fapi). Fuer Bybit waere ein
        analoger Endpoint zu nutzen.
        """
        if self.exchange_id != "binance":
            logger.info("OI-Historie aktuell nur fuer Binance Futures implementiert.")
            return pd.DataFrame(columns=["timestamp", "datetime", "open_interest", "open_interest_usd"])

        sym = self.perp_symbol.replace("/", "").replace(":USDT", "")
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        params = {"symbol": sym, "period": period, "limit": min(limit, 500)}
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("OI-Historie konnte nicht geladen werden: %s", exc)
            return pd.DataFrame(columns=["timestamp", "datetime", "open_interest", "open_interest_usd"])

        if not data:
            return pd.DataFrame(columns=["timestamp", "datetime", "open_interest", "open_interest_usd"])

        df = pd.DataFrame(data)
        df["timestamp"] = df["timestamp"].astype("int64")
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["open_interest"] = df["sumOpenInterest"].astype(float)            # in Coins
        df["open_interest_usd"] = df["sumOpenInterestValue"].astype(float)   # in USD
        df = df[["timestamp", "datetime", "open_interest", "open_interest_usd"]]
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    # ----- Bequeme Helfer -----
    def history_window(self, days: int, timeframe: str, market: str = "perp") -> pd.DataFrame:
        since = _to_ms(datetime.utcnow() - timedelta(days=days))
        return self.fetch_ohlcv(timeframe=timeframe, since_ms=since, market=market)

    def trades_window(self, minutes: int, market: str = "perp") -> pd.DataFrame:
        since = _to_ms(datetime.utcnow() - timedelta(minutes=minutes))
        return self.fetch_trades(since_ms=since, market=market)

    def backtest_window(self, start: str, end: str, timeframe: str, market: str = "perp") -> pd.DataFrame:
        since = _to_ms(_parse_date(start))
        until = _to_ms(_parse_date(end))
        df = self.fetch_ohlcv(timeframe=timeframe, since_ms=since, market=market)
        if df.empty:
            return df
        return df[df["timestamp"] <= until].reset_index(drop=True)
