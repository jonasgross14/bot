"""
Market Profile (TPO) nach Steidlmayer / Dalton.

Wir bauen ein TPO-Profil aus OHLCV-Daten auf. Jede TPO-Periode entspricht
einem Zeitfenster (z. B. 30 Minuten = ein Buchstabe). Im klassischen
Steidlmayer-Sinne werden alle Preise, die in einer Periode "berührt"
wurden, mit dem Buchstaben dieser Periode markiert.

Resultate:
- Tagesprofil mit POC, VAH, VAL (TPO-basiert)
- Initial Balance (IB) ueber die ersten N Perioden
- Erkennung von Profile-Strukturen:
    Single Prints, Poor High / Poor Low, b-Profile, p-Profile,
    Trend-Tag, Balanced/Normal Day, Range Extension
- Entwicklung gegenueber Vortags-Profil (Open Type, Acceptance/Rejection)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from string import ascii_uppercase, ascii_lowercase
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


TPO_LETTERS = list(ascii_uppercase) + list(ascii_lowercase)


@dataclass
class MarketProfileResult:
    poc: float
    vah: float
    val: float
    ib_high: float
    ib_low: float
    range_high: float
    range_low: float
    open_price: float
    close_price: float
    profile: Dict[float, str]                     # price -> TPO-string
    single_prints: List[float] = field(default_factory=list)
    poor_high: bool = False
    poor_low: bool = False
    profile_shape: str = "balanced"               # b | p | normal | trend | balanced
    range_extension_up: bool = False
    range_extension_down: bool = False
    open_type: str = "open-auction"               # open-drive | open-test-drive | open-rejection-reverse | open-auction
    acceptance_above_prior_value: bool = False
    acceptance_below_prior_value: bool = False
    prior_vah: Optional[float] = None
    prior_val: Optional[float] = None
    prior_poc: Optional[float] = None

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["profile"] = {float(k): v for k, v in self.profile.items()}
        return d


class MarketProfile:
    """TPO-Profil-Rechner."""

    def __init__(
        self,
        tpo_size_minutes: int = 30,
        initial_balance_periods: int = 2,
        value_area_percent: float = 0.70,
        tick_size: Optional[float] = None,
    ) -> None:
        self.tpo_size_minutes = tpo_size_minutes
        self.initial_balance_periods = initial_balance_periods
        self.value_area_percent = value_area_percent
        self.tick_size = tick_size

    # ------------------------------------------------------------------
    def compute(
        self,
        ohlcv: pd.DataFrame,
        prior_session: Optional["MarketProfileResult"] = None,
    ) -> MarketProfileResult:
        if ohlcv is None or ohlcv.empty:
            raise ValueError("MarketProfile.compute: leerer DataFrame")

        df = ohlcv.copy()
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Tick-Size automatisch ableiten, falls nicht gesetzt
        tick = self.tick_size
        if tick is None:
            rng = float(df["high"].max() - df["low"].min())
            tick = max(rng / 200, 1e-6)  # 200 Stufen ueber den Range

        # Auf TPO-Perioden gruppieren
        df["period"] = (
            (df["timestamp"] - df["timestamp"].iloc[0])
            // (self.tpo_size_minutes * 60_000)
        ).astype(int)

        periods = df.groupby("period").agg(
            high=("high", "max"),
            low=("low", "min"),
            start=("timestamp", "min"),
        ).reset_index()
        if periods.empty:
            raise ValueError("MarketProfile: keine Perioden generiert")

        # Profil aufbauen
        price_min = float(periods["low"].min())
        price_max = float(periods["high"].max())
        n_levels = max(int((price_max - price_min) / tick) + 1, 1)
        prices = np.round(price_min + np.arange(n_levels) * tick, 8)

        profile: Dict[float, str] = {p: "" for p in prices}
        for i, row in periods.iterrows():
            letter = TPO_LETTERS[i % len(TPO_LETTERS)]
            lo = row["low"]
            hi = row["high"]
            mask = (prices >= lo - 1e-9) & (prices <= hi + 1e-9)
            for p in prices[mask]:
                profile[p] += letter

        counts = np.array([len(profile[p]) for p in prices], dtype=float)

        # POC = Preis mit den meisten TPOs
        poc_idx = int(np.argmax(counts))
        poc = float(prices[poc_idx])

        # Value Area (TPO-basiert, 70 %)
        vah, val = self._tpo_value_area(prices, counts, poc_idx)

        # Initial Balance
        ib_periods = periods.head(self.initial_balance_periods)
        ib_high = float(ib_periods["high"].max())
        ib_low = float(ib_periods["low"].min())

        # Single Prints (nur 1 TPO an einem Preis)
        single_prints = [float(prices[i]) for i, c in enumerate(counts) if c == 1]
        single_prints = sorted(single_prints)

        # Poor High / Poor Low (zwei oder mehr TPOs am Extrem)
        poor_high = counts[-1] >= 2
        poor_low = counts[0] >= 2

        # Profil-Form heuristisch ableiten
        profile_shape = self._classify_shape(counts)

        # Range Extension
        range_high = float(periods["high"].max())
        range_low = float(periods["low"].min())
        range_extension_up = range_high > ib_high
        range_extension_down = range_low < ib_low

        # Open Type
        open_price = float(df["open"].iloc[0])
        close_price = float(df["close"].iloc[-1])
        open_type = self._classify_open(df, ib_high, ib_low, open_price)

        # Vergleich zum Vortag (Acceptance / Rejection)
        prior_vah = prior_val = prior_poc = None
        acc_above = acc_below = False
        if prior_session is not None:
            prior_vah = prior_session.vah
            prior_val = prior_session.val
            prior_poc = prior_session.poc
            acc_above = self._acceptance(periods, prior_vah, direction="above")
            acc_below = self._acceptance(periods, prior_val, direction="below")

        return MarketProfileResult(
            poc=poc,
            vah=vah,
            val=val,
            ib_high=ib_high,
            ib_low=ib_low,
            range_high=range_high,
            range_low=range_low,
            open_price=open_price,
            close_price=close_price,
            profile=profile,
            single_prints=single_prints,
            poor_high=bool(poor_high),
            poor_low=bool(poor_low),
            profile_shape=profile_shape,
            range_extension_up=bool(range_extension_up),
            range_extension_down=bool(range_extension_down),
            open_type=open_type,
            acceptance_above_prior_value=acc_above,
            acceptance_below_prior_value=acc_below,
            prior_vah=prior_vah,
            prior_val=prior_val,
            prior_poc=prior_poc,
        )

    # ------------------------------------------------------------------
    def _tpo_value_area(
        self, prices: np.ndarray, counts: np.ndarray, poc_idx: int
    ) -> Tuple[float, float]:
        total = counts.sum()
        if total <= 0:
            return float(prices[-1]), float(prices[0])
        target = total * self.value_area_percent
        included = counts[poc_idx]
        lo, hi = poc_idx, poc_idx
        n = len(counts)
        while included < target and (lo > 0 or hi < n - 1):
            up = counts[hi + 1 : hi + 3].sum() if hi + 1 < n else -1
            dn = counts[max(0, lo - 2) : lo].sum() if lo > 0 else -1
            if up >= dn and hi + 1 < n:
                hi = min(hi + 2, n - 1)
                included = counts[lo : hi + 1].sum()
            elif lo > 0:
                lo = max(lo - 2, 0)
                included = counts[lo : hi + 1].sum()
            else:
                break
        return float(prices[hi]), float(prices[lo])

    # ------------------------------------------------------------------
    def _classify_shape(self, counts: np.ndarray) -> str:
        """
        Sehr grobe Profil-Klassifikation:
        - b-Profile  : Volumen / TPOs ballen sich unten, Spitze nach oben
        - p-Profile  : Volumen / TPOs ballen sich oben, Spitze nach unten
        - trend      : Profil schmal, klare Verschiebung von POC ueber Zeit
        - normal     : symmetrisches Glockenprofil
        """
        if counts.size < 5:
            return "balanced"
        upper = counts[len(counts) // 2 :].sum()
        lower = counts[: len(counts) // 2].sum()
        ratio = upper / max(lower, 1)

        # Spreizung des Profils: hoher Standardabweichungs-Anteil = breit
        spread = counts.std() / max(counts.mean(), 1)

        if ratio > 1.4 and spread < 1.0:
            return "p"
        if ratio < 0.7 and spread < 1.0:
            return "b"
        if spread > 1.4:
            return "trend"
        return "normal"

    # ------------------------------------------------------------------
    def _classify_open(
        self, df: pd.DataFrame, ib_high: float, ib_low: float, open_price: float
    ) -> str:
        """Vereinfachte Open-Type-Klassifikation nach Dalton."""
        if df.empty:
            return "open-auction"
        first = df.head(max(2, self.initial_balance_periods))
        rng = float(first["high"].max() - first["low"].min())
        body = abs(float(first["close"].iloc[-1]) - open_price)
        # Open-Drive: Eroeffnung schiesst direktional weg, kaum Retest
        if body > rng * 0.7:
            return "open-drive"
        # Open-Test-Drive: kurzer Test gegen Open, dann klare Richtung
        if body > rng * 0.45:
            return "open-test-drive"
        # Open-Rejection-Reverse: Eroeffnung getestet, dann Reversal
        if (open_price > df["close"].iloc[-1] and df["high"].iloc[0] >= ib_high * 0.999) or (
            open_price < df["close"].iloc[-1] and df["low"].iloc[0] <= ib_low * 1.001
        ):
            return "open-rejection-reverse"
        return "open-auction"

    # ------------------------------------------------------------------
    def _acceptance(
        self, periods: pd.DataFrame, level: Optional[float], direction: str
    ) -> bool:
        """Akzeptanz = >=2 vollstaendige TPO-Perioden ueber/unter Level."""
        if level is None or periods.empty:
            return False
        if direction == "above":
            count = (periods["low"] > level).sum()
        else:
            count = (periods["high"] < level).sum()
        return bool(count >= 2)
