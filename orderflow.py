"""
Orderflow-Modul: Open Interest (OI) und Cumulative Volume Delta (CVD).

- OI:  Veraenderung in Coins und USD (Lookback einstellbar)
- CVD: Summierte Aggressor-Volumina (taker buy minus taker sell), getrennt
       fuer Spot und Perp.

Das Modul liefert reine Zahlen + ein paar Klassifikationen
(z. B. "OI steigt + Preis steigt = Long-Aufbau"). Die Interpretation
("Trapped Longs", "Cascading Liquidation" usw.) macht der Analyzer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
@dataclass
class OIResult:
    current: float
    delta_coins: float
    delta_pct: float
    series: pd.DataFrame   # DataFrame mit datetime + open_interest

    def as_dict(self) -> dict:
        return {
            "current": self.current,
            "delta_coins": self.delta_coins,
            "delta_pct": self.delta_pct,
        }


@dataclass
class CVDResult:
    perp_cvd: float
    spot_cvd: float
    perp_series: pd.Series      # cumulative
    spot_series: pd.Series
    perp_delta_recent: float    # delta ueber juengste Periode
    spot_delta_recent: float
    divergence: str             # spot-fuehrt | perp-fuehrt | parallel | gegen

    def as_dict(self) -> dict:
        return {
            "perp_cvd": self.perp_cvd,
            "spot_cvd": self.spot_cvd,
            "perp_delta_recent": self.perp_delta_recent,
            "spot_delta_recent": self.spot_delta_recent,
            "divergence": self.divergence,
        }


# ---------------------------------------------------------------------------
class Orderflow:
    """OI + CVD Berechnung und Klassifikation."""

    def __init__(self, oi_lookback_minutes: int = 60, cvd_lookback_minutes: int = 60) -> None:
        self.oi_lookback_minutes = oi_lookback_minutes
        self.cvd_lookback_minutes = cvd_lookback_minutes

    # ----- OI -----
    def compute_oi(self, oi_df: pd.DataFrame) -> Optional[OIResult]:
        if oi_df is None or oi_df.empty:
            return None
        df = oi_df.sort_values("timestamp").reset_index(drop=True)
        latest = df.iloc[-1]

        cutoff = latest["timestamp"] - self.oi_lookback_minutes * 60_000
        prior = df[df["timestamp"] <= cutoff]
        if prior.empty:
            prior_val = float(df.iloc[0]["open_interest"])
        else:
            prior_val = float(prior.iloc[-1]["open_interest"])

        current = float(latest["open_interest"])
        delta_coins = current - prior_val
        delta_pct = (delta_coins / prior_val) * 100 if prior_val else 0.0

        return OIResult(
            current=current,
            delta_coins=delta_coins,
            delta_pct=delta_pct,
            series=df,
        )

    # ----- CVD -----
    def compute_cvd(
        self,
        perp_trades: pd.DataFrame,
        spot_trades: pd.DataFrame,
    ) -> CVDResult:
        perp_series = self._cumulative_delta(perp_trades)
        spot_series = self._cumulative_delta(spot_trades)

        perp_delta_recent = self._recent_delta(perp_trades, self.cvd_lookback_minutes)
        spot_delta_recent = self._recent_delta(spot_trades, self.cvd_lookback_minutes)

        divergence = self._classify_divergence(perp_delta_recent, spot_delta_recent)

        return CVDResult(
            perp_cvd=float(perp_series.iloc[-1]) if not perp_series.empty else 0.0,
            spot_cvd=float(spot_series.iloc[-1]) if not spot_series.empty else 0.0,
            perp_series=perp_series,
            spot_series=spot_series,
            perp_delta_recent=perp_delta_recent,
            spot_delta_recent=spot_delta_recent,
            divergence=divergence,
        )

    # ------------------------------------------------------------------
    def _cumulative_delta(self, trades: pd.DataFrame) -> pd.Series:
        if trades is None or trades.empty:
            return pd.Series(dtype=float)
        signed = np.where(trades["side"].str.lower() == "buy", trades["amount"], -trades["amount"])
        cumulative = pd.Series(signed, index=trades["datetime"]).cumsum()
        return cumulative

    def _recent_delta(self, trades: pd.DataFrame, minutes: int) -> float:
        if trades is None or trades.empty:
            return 0.0
        latest_ts = trades["timestamp"].max()
        cutoff = latest_ts - minutes * 60_000
        recent = trades[trades["timestamp"] >= cutoff]
        if recent.empty:
            return 0.0
        signed = np.where(recent["side"].str.lower() == "buy", recent["amount"], -recent["amount"])
        return float(signed.sum())

    def _classify_divergence(self, perp: float, spot: float) -> str:
        if abs(perp) < 1e-9 and abs(spot) < 1e-9:
            return "parallel"
        # gleiche Richtung & vergleichbarer Betrag => parallel
        if np.sign(perp) == np.sign(spot):
            stronger = "spot-fuehrt" if abs(spot) > abs(perp) * 1.2 else (
                "perp-fuehrt" if abs(perp) > abs(spot) * 1.2 else "parallel"
            )
            return stronger
        return "gegen"

    # ----- Kombinierte Klassifikation OI + Preis + CVD -----
    @staticmethod
    def classify_oi_price(oi_delta: float, price_delta: float) -> str:
        """
        Klassische Lesart:
        - Preis hoch + OI hoch  => Long-Aufbau (frische Longs)
        - Preis hoch + OI down  => Short-Squeeze / Short-Cover (Schwach)
        - Preis down + OI hoch  => Short-Aufbau (frische Shorts)
        - Preis down + OI down  => Long-Liquidation / Long-Auflösung
        """
        if abs(oi_delta) < 1e-9 and abs(price_delta) < 1e-9:
            return "neutral"
        if price_delta > 0 and oi_delta > 0:
            return "long-aufbau"
        if price_delta > 0 and oi_delta < 0:
            return "short-cover"
        if price_delta < 0 and oi_delta > 0:
            return "short-aufbau"
        if price_delta < 0 and oi_delta < 0:
            return "long-liquidation"
        return "neutral"
