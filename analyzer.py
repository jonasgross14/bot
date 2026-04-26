"""
Analyzer / MGI-Signal-Engine.

Erzeugt aus mehreren Volume- und Market-Profilen (Monthly, Weekly, Daily,
Prior Day) sowie OI/CVD-Daten ein strukturiertes "MGI Signal" im Stil von
@YugoBetrug0:

- Setup-Name (z. B. "Monthly/Weekly VAH Resistance Bear")
- Bias-Tag (LONG STARK / SHORT SCHWACH / NEUTRAL ...)
- Score-Aufbau: Basis + Kontext + Intraday
- Kontext-Tabelle (Trend, Marktphase, Delta 5D, Range, Flow, CVD-Divergenz)
- Begruendung mit Punkten
- Take-Profit-Targets (TP0..TP+) + R/R
- Stop-Loss-Referenz
- Level-Map mit prozentualer Distanz

Der Bot gibt KEINE direkten Buy/Sell-Signale - er liefert kontextbasierte
Denkanstoesse im Sinne von Mind-Over-Markets / Steidlmayer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from market_profile import MarketProfile, MarketProfileResult
from orderflow import CVDResult, OIResult, Orderflow
from volume_profile import VolumeProfile, VolumeProfileResult

logger = logging.getLogger(__name__)


# ===========================================================================
#  Datenmodelle
# ===========================================================================
@dataclass
class KontextRow:
    label: str
    value: str
    score: int


@dataclass
class IntradayRow:
    icon: str           # "ok" | "warn" | "x" | "bolt"
    text: str
    score: int


@dataclass
class ReasonRow:
    text: str
    score: int


@dataclass
class TakeProfitRow:
    label: str          # "TP0", "TP1", "TP+", ...
    price: float
    note: str           # z.B. "Quick-TP +0.50%"
    rr: float           # Risk-Reward


@dataclass
class LevelMapRow:
    label: str
    price: float
    distance_pct: float
    direction: str      # "up" | "down" | "current"


@dataclass
class MGISignal:
    timestamp: datetime
    symbol: str
    current_price: float
    setup_name: str
    direction: str                 # "LONG" | "SHORT" | "NEUTRAL"
    strength: str                  # "STARK" | "SOLID" | "SCHWACH" | "NEUTRAL"
    monthly_bias: str              # "BULL" | "BEAR" | "NEUTRAL"
    weekly_bias: str               # "BULL" | "BEAR" | "NEUTRAL"
    basis_score: int
    kontext_score: int
    intraday_score: int
    extra_a: int = 0
    extra_b: int = 0
    total_score: int = 0
    kontext: List[KontextRow] = field(default_factory=list)
    intraday: List[IntradayRow] = field(default_factory=list)
    reasons: List[ReasonRow] = field(default_factory=list)
    take_profits: List[TakeProfitRow] = field(default_factory=list)
    stop_loss: Optional[Tuple[float, str, float]] = None  # (price, label, abs_pct)
    level_map: List[LevelMapRow] = field(default_factory=list)
    vortag_label: str = ""
    close_pct: float = 0.0
    ac_status: str = "AC Pending"   # "AC Complete" / "AC Pending"
    narrative: str = ""              # Lange deutsche Erklaerung

    def __post_init__(self) -> None:
        self.total_score = (
            self.basis_score
            + self.kontext_score
            + self.intraday_score
            + self.extra_a
            + self.extra_b
        )

    @property
    def score_breakdown(self) -> str:
        parts = [self.basis_score, self.kontext_score, self.intraday_score, self.extra_a, self.extra_b]
        return " ".join(f"{p:+d}" if p else "+0" for p in parts).replace("+0", "+0")


# ===========================================================================
#  Analyzer
# ===========================================================================
class MGIAnalyzer:
    """
    Erzeugt aus den vorberechneten Profilen + OI/CVD ein vollstaendiges
    MGI-Signal. Die Profile werden vom Aufrufer (main.py) uebergeben, damit
    der Analyzer leichtgewichtig bleibt.
    """

    # Schwellen fuer das Strength-Tagging
    STRONG = 7
    SOLID = 4
    WEAK = 1

    def __init__(self, symbol: str = "BTCUSDT") -> None:
        self.symbol = symbol

    # ------------------------------------------------------------------
    def analyze(
        self,
        current_price: float,
        monthly_vp: VolumeProfileResult,
        weekly_vp: VolumeProfileResult,
        daily_mp: MarketProfileResult,
        prior_day_mp: MarketProfileResult,
        oi: Optional[OIResult],
        cvd: Optional[CVDResult],
        recent_ohlcv: pd.DataFrame,
    ) -> MGISignal:
        # ---------- Setup erkennen ----------
        setup_name, direction = self._detect_setup(current_price, monthly_vp, weekly_vp, daily_mp)

        # ---------- Basis-Score (aus Setup / Profilstruktur) ----------
        basis_score, reasons = self._build_reasons(
            setup_name, direction, current_price, monthly_vp, weekly_vp,
            daily_mp, prior_day_mp,
        )

        # ---------- Kontext (Multi-Timeframe) ----------
        kontext_rows, kontext_score, monthly_bias, weekly_bias = self._build_kontext(
            current_price, monthly_vp, weekly_vp, daily_mp, prior_day_mp, cvd, recent_ohlcv,
        )

        # ---------- Intraday-Auktion ----------
        intraday_rows, intraday_score = self._build_intraday(
            current_price, daily_mp, oi, cvd, direction,
        )

        # ---------- Strength-Tag ----------
        total = basis_score + kontext_score + intraday_score
        strength = self._strength_tag(total, direction)

        # ---------- TP / SL ----------
        take_profits, stop_loss = self._build_targets(
            direction, current_price, monthly_vp, weekly_vp, daily_mp, prior_day_mp,
        )

        # ---------- Level-Map ----------
        level_map = self._build_level_map(
            current_price, monthly_vp, weekly_vp, daily_mp, prior_day_mp,
        )

        # ---------- Vortag / AC ----------
        vortag_label = self._classify_prior(prior_day_mp)
        close_pct = self._close_pct(prior_day_mp)
        ac_status = "AC Complete" if prior_day_mp.acceptance_above_prior_value or prior_day_mp.acceptance_below_prior_value else "AC Pending"

        # ---------- Narrative ----------
        narrative = self._render_narrative(
            setup_name, direction, strength, total, current_price,
            monthly_vp, weekly_vp, daily_mp, prior_day_mp, oi, cvd, reasons,
        )

        return MGISignal(
            timestamp=datetime.now(timezone.utc),
            symbol=self.symbol,
            current_price=current_price,
            setup_name=setup_name,
            direction=direction,
            strength=strength,
            monthly_bias=monthly_bias,
            weekly_bias=weekly_bias,
            basis_score=basis_score,
            kontext_score=kontext_score,
            intraday_score=intraday_score,
            kontext=kontext_rows,
            intraday=intraday_rows,
            reasons=reasons,
            take_profits=take_profits,
            stop_loss=stop_loss,
            level_map=level_map,
            vortag_label=vortag_label,
            close_pct=close_pct,
            ac_status=ac_status,
            narrative=narrative,
        )

    # ==================================================================
    #  Setup-Erkennung
    # ==================================================================
    def _detect_setup(
        self,
        price: float,
        monthly: VolumeProfileResult,
        weekly: VolumeProfileResult,
        daily: MarketProfileResult,
    ) -> Tuple[str, str]:
        """Heuristik im Stil Yugo: Konfluenz-Setups erkennen."""
        tol = max(price * 0.0015, 5.0)  # 0.15 % oder min. 5 USDT

        near_m_vah = abs(price - monthly.vah) <= tol
        near_w_vah = abs(price - weekly.vah) <= tol
        near_m_val = abs(price - monthly.val) <= tol
        near_w_val = abs(price - weekly.val) <= tol
        near_m_poc = abs(price - monthly.poc) <= tol
        near_w_poc = abs(price - weekly.poc) <= tol

        # Resistance Bear
        if near_m_vah and near_w_vah:
            return "Monthly/Weekly VAH Resistance Bear", "SHORT"
        if near_m_vah:
            return "Monthly VAH Resistance Bear", "SHORT"
        if near_w_vah:
            return "Weekly VAH Resistance Bear", "SHORT"

        # Support Bull
        if near_m_val and near_w_val:
            return "Monthly/Weekly VAL Support Bull", "LONG"
        if near_m_val:
            return "Monthly VAL Support Bull", "LONG"
        if near_w_val:
            return "Weekly VAL Support Bull", "LONG"

        # POC Reaktion
        if near_m_poc:
            return "Monthly POC Reaction", "NEUTRAL"
        if near_w_poc:
            return "Weekly POC Reaction", "NEUTRAL"

        # Range-Trade in Value Area
        in_weekly_va = weekly.val <= price <= weekly.vah
        if in_weekly_va:
            return "Inside Weekly Value - Rotational", "NEUTRAL"

        # Breakout / Trend
        if price > weekly.vah:
            return "Above Weekly VAH - Trend Continuation", "LONG"
        if price < weekly.val:
            return "Below Weekly VAL - Trend Continuation", "SHORT"

        return "Inside Balance - kein klares Setup", "NEUTRAL"

    # ==================================================================
    #  Begruendung / Basis-Score
    # ==================================================================
    def _build_reasons(
        self,
        setup_name: str,
        direction: str,
        price: float,
        monthly: VolumeProfileResult,
        weekly: VolumeProfileResult,
        daily: MarketProfileResult,
        prior: MarketProfileResult,
    ) -> Tuple[int, List[ReasonRow]]:
        rows: List[ReasonRow] = []

        if direction == "SHORT":
            if "VAH" in setup_name:
                rows.append(ReasonRow("Monthly VAH getestet und gehalten", +3))
            if daily.poor_high or daily.profile_shape == "p":
                rows.append(ReasonRow("SellingTail bestaetigt Ablehnung", +2))
            if not daily.acceptance_above_prior_value:
                rows.append(ReasonRow("Incomplete Bearish - Vortag-Value nicht akzeptiert", +1))
            if daily.profile_shape in {"normal", "balanced"}:
                rows.append(ReasonRow("RotationalBias Bearish", +1))

        elif direction == "LONG":
            if "VAL" in setup_name:
                rows.append(ReasonRow("Monthly VAL gehalten - Buyer responsive", +3))
            if daily.poor_low or daily.profile_shape == "b":
                rows.append(ReasonRow("BuyingTail bestaetigt Aufnahme", +2))
            if not daily.acceptance_below_prior_value:
                rows.append(ReasonRow("Incomplete Bullish - Value nicht nach unten verschoben", +1))
            if daily.profile_shape in {"normal", "balanced"}:
                rows.append(ReasonRow("RotationalBias Bullish", +1))

        else:  # NEUTRAL
            rows.append(ReasonRow("Markt in Balance - Auction sucht Richtung", +1))
            if daily.profile_shape == "normal":
                rows.append(ReasonRow("Normal-Day-Profil - Responsive Trade bevorzugt", +1))

        # Single Prints im Pfad als zusaetzliche Punkte
        if direction == "SHORT" and any(sp > price for sp in daily.single_prints):
            rows.append(ReasonRow("Single Prints oberhalb - schwache Auktion", +1))
        if direction == "LONG" and any(sp < price for sp in daily.single_prints):
            rows.append(ReasonRow("Single Prints unterhalb - schwache Auktion", +1))

        score = sum(r.score for r in rows)
        return score, rows

    # ==================================================================
    #  Kontext (Multi-Timeframe)
    # ==================================================================
    def _build_kontext(
        self,
        price: float,
        monthly: VolumeProfileResult,
        weekly: VolumeProfileResult,
        daily: MarketProfileResult,
        prior: MarketProfileResult,
        cvd: Optional[CVDResult],
        recent: pd.DataFrame,
    ) -> Tuple[List[KontextRow], int, str, str]:
        rows: List[KontextRow] = []

        # Monthly Bias
        if price > monthly.vah:
            monthly_bias = "BULL"
        elif price < monthly.val:
            monthly_bias = "BEAR"
        elif price > monthly.poc:
            monthly_bias = "BULL"
        else:
            monthly_bias = "BEAR"

        # Weekly Bias
        if price > weekly.vah:
            weekly_bias = "BULL"
        elif price < weekly.val:
            weekly_bias = "BEAR"
        elif price > weekly.poc:
            weekly_bias = "BULL"
        else:
            weekly_bias = "BEAR"

        # 1. Trend
        if monthly_bias == weekly_bias:
            rows.append(KontextRow("Trend", f"M {monthly_bias} / W {weekly_bias}",
                                    +1 if monthly_bias == "BULL" else -1))
        else:
            rows.append(KontextRow("Trend", f"W {weekly_bias} / M {monthly_bias}", -1))

        # 2. Marktphase
        if monthly.val <= price <= monthly.vah and weekly.val <= price <= weekly.vah:
            phase, score = "Balance", -1
        elif price > monthly.vah or price > weekly.vah:
            phase, score = "Discovery Up", +1
        elif price < monthly.val or price < weekly.val:
            phase, score = "Discovery Down", -1
        else:
            phase, score = "Transition", 0
        rows.append(KontextRow("Marktphase", phase, score))

        # 3. Delta 5D (Net-Delta ueber juengste Tage aus close-open)
        if recent is not None and not recent.empty:
            delta_signal = float(recent["close"].iloc[-1] - recent["close"].iloc[0])
            if abs(delta_signal) < price * 0.005:
                rows.append(KontextRow("Delta 5D", "Mixed", 0))
            elif delta_signal > 0:
                rows.append(KontextRow("Delta 5D", "Bullish", +1))
            else:
                rows.append(KontextRow("Delta 5D", "Bearish", -1))
        else:
            rows.append(KontextRow("Delta 5D", "Keine Daten", 0))

        # 4. Range-Lokation
        if abs(price - weekly.poc) < weekly.bin_size * 2:
            rows.append(KontextRow("Range", "Weekly POC", -1))
        elif price >= weekly.vah:
            rows.append(KontextRow("Range", "ueber Weekly VAH", +1))
        elif price <= weekly.val:
            rows.append(KontextRow("Range", "unter Weekly VAL", -1))
        else:
            rows.append(KontextRow("Range", "in Weekly Value", 0))

        # 5. Flow (CVD insgesamt)
        if cvd is None:
            rows.append(KontextRow("Flow", "Keine Daten", 0))
        else:
            if abs(cvd.perp_delta_recent) < 1e-9:
                rows.append(KontextRow("Flow", "Flat", 0))
            elif cvd.perp_delta_recent > 0:
                rows.append(KontextRow("Flow", "Buyer Aktiv", +1))
            else:
                rows.append(KontextRow("Flow", "Seller Aktiv", -1))

        # 6. CVD Divergenz Spot vs Perp
        if cvd is None:
            rows.append(KontextRow("CVD Divergenz", "Keine", 0))
        else:
            if cvd.divergence == "gegen":
                rows.append(KontextRow("CVD Divergenz", "Spot vs Perp gegen", -1))
            elif cvd.divergence == "spot-fuehrt":
                rows.append(KontextRow("CVD Divergenz", "Spot fuehrt", +1))
            elif cvd.divergence == "perp-fuehrt":
                rows.append(KontextRow("CVD Divergenz", "Perp fuehrt", -1))
            else:
                rows.append(KontextRow("CVD Divergenz", "Keine", 0))

        score = sum(r.score for r in rows)
        return rows, score, monthly_bias, weekly_bias

    # ==================================================================
    #  Intraday (Auction-Aktion)
    # ==================================================================
    def _build_intraday(
        self,
        price: float,
        daily: MarketProfileResult,
        oi: Optional[OIResult],
        cvd: Optional[CVDResult],
        direction: str,
    ) -> Tuple[List[IntradayRow], int]:
        rows: List[IntradayRow] = []

        # 1. Net-Delta heute
        if cvd is not None:
            d = cvd.perp_delta_recent
            if abs(d) < 1e-9:
                rows.append(IntradayRow("bolt", "Net-Delta neutral", 0))
            elif d > 0:
                rows.append(IntradayRow("bolt", "Net-Delta positiv - Buyer aktiv", +1 if direction == "LONG" else -1))
            else:
                rows.append(IntradayRow("bolt", "Net-Delta negativ - Seller aktiv", +1 if direction == "SHORT" else -1))
        else:
            rows.append(IntradayRow("bolt", "Net-Delta keine Daten", 0))

        # 2. Profile-Tail / Rejection
        if direction == "SHORT" and (daily.profile_shape == "p" or daily.poor_high is False):
            rows.append(IntradayRow("ok", "Rejection nach oben - Verkaeufer aktiv", +1))
        elif direction == "LONG" and (daily.profile_shape == "b" or daily.poor_low is False):
            rows.append(IntradayRow("ok", "Rejection nach unten - Kaeufer aktiv", +1))
        else:
            rows.append(IntradayRow("warn", "Keine klare Tail-Rejection", 0))

        # 3. IB-Verhalten
        if direction == "SHORT" and price > daily.ib_high:
            rows.append(IntradayRow("x", "Preis ueber IB High - Breakout gegen Short", -1))
        elif direction == "LONG" and price < daily.ib_low:
            rows.append(IntradayRow("x", "Preis unter IB Low - Breakout gegen Long", -1))
        elif direction == "SHORT" and price < daily.ib_low:
            rows.append(IntradayRow("ok", "Preis unter IB Low - bestaetigt Short", +1))
        elif direction == "LONG" and price > daily.ib_high:
            rows.append(IntradayRow("ok", "Preis ueber IB High - bestaetigt Long", +1))
        else:
            rows.append(IntradayRow("warn", "Preis innerhalb IB - Auktion offen", 0))

        # 4. OI-Verhalten
        if oi is not None:
            if abs(oi.delta_pct) < 0.1:
                rows.append(IntradayRow("warn", f"OI flat ({oi.delta_pct:+.2f}%)", 0))
            elif oi.delta_pct > 0:
                rows.append(IntradayRow("bolt", f"OI steigt ({oi.delta_pct:+.2f}%) - frische Positionen", 0))
            else:
                rows.append(IntradayRow("bolt", f"OI faellt ({oi.delta_pct:+.2f}%) - Cover/Liquidation", 0))

        score = sum(r.score for r in rows)
        return rows, score

    # ==================================================================
    #  TP / SL
    # ==================================================================
    def _build_targets(
        self,
        direction: str,
        price: float,
        monthly: VolumeProfileResult,
        weekly: VolumeProfileResult,
        daily: MarketProfileResult,
        prior: MarketProfileResult,
    ) -> Tuple[List[TakeProfitRow], Optional[Tuple[float, str, float]]]:
        if direction == "NEUTRAL":
            return [], None

        if direction == "SHORT":
            stop_price = monthly.vah * 1.001 if abs(price - monthly.vah) < price * 0.01 else weekly.vah * 1.001
            stop_label = "Monthly VAH" if stop_price >= monthly.vah else "Weekly VAH"
            risk = stop_price - price
            candidates = [
                ("TP0", price * 0.995, "Quick-TP +0.50%"),
                ("TP1", weekly.val, "Weekly VAL"),
                ("TP+", prior.poc, "Naked POC"),
                ("TP+", monthly.val, "Monthly VAL"),
            ]
            tps: List[TakeProfitRow] = []
            for label, target, note in candidates:
                if target >= price:
                    continue
                reward = price - target
                rr = reward / risk if risk > 0 else 0.0
                tps.append(TakeProfitRow(label, float(target), note, rr))
        else:  # LONG
            stop_price = monthly.val * 0.999 if abs(price - monthly.val) < price * 0.01 else weekly.val * 0.999
            stop_label = "Monthly VAL" if stop_price <= monthly.val else "Weekly VAL"
            risk = price - stop_price
            candidates = [
                ("TP0", price * 1.005, "Quick-TP +0.50%"),
                ("TP1", weekly.vah, "Weekly VAH"),
                ("TP+", prior.poc, "Naked POC"),
                ("TP+", monthly.vah, "Monthly VAH"),
            ]
            tps = []
            for label, target, note in candidates:
                if target <= price:
                    continue
                reward = target - price
                rr = reward / risk if risk > 0 else 0.0
                tps.append(TakeProfitRow(label, float(target), note, rr))

        sl_pct = abs(stop_price - price) / price * 100
        return tps, (float(stop_price), stop_label, sl_pct)

    # ==================================================================
    #  Level Map
    # ==================================================================
    def _build_level_map(
        self,
        price: float,
        monthly: VolumeProfileResult,
        weekly: VolumeProfileResult,
        daily: MarketProfileResult,
        prior: MarketProfileResult,
    ) -> List[LevelMapRow]:
        levels: List[Tuple[str, float]] = [
            ("Weekly VAH", weekly.vah),
            ("Weekly VAL", weekly.val),
            ("Weekly POC", weekly.poc),
            ("Monthly VAH", monthly.vah),
            ("Monthly VAL", monthly.val),
            ("Monthly POC", monthly.poc),
            ("PrevHigh", prior.range_high),
            ("PrevLow", prior.range_low),
            ("PrevPOC", prior.poc),
            ("PrevVAH", prior.vah),
            ("PrevVAL", prior.val),
        ]
        # HVN/LVN naheliegende
        for hvn in monthly.hvn:
            levels.append(("HVN", hvn))
        for lvn in monthly.lvn:
            levels.append(("LVN", lvn))

        rows: List[LevelMapRow] = []
        for label, lvl in levels:
            if lvl is None or not np.isfinite(lvl):
                continue
            dist = (lvl - price) / price * 100
            direction = "up" if lvl > price else "down" if lvl < price else "current"
            rows.append(LevelMapRow(label, float(lvl), float(dist), direction))

        # Aktuellen Preis einfuegen
        rows.append(LevelMapRow("AKTUELLER PREIS", float(price), 0.0, "current"))

        # Sortiert nach Preis (top -> bottom: hoechste oben)
        rows.sort(key=lambda r: -r.price)

        # Auf naheliegende Levels reduzieren (max +-2%)
        rows = [r for r in rows if abs(r.distance_pct) <= 2.5 or r.direction == "current"]
        return rows

    # ==================================================================
    #  Helpers
    # ==================================================================
    def _strength_tag(self, total: int, direction: str) -> str:
        if direction == "NEUTRAL":
            return "NEUTRAL"
        if total >= self.STRONG:
            return "STARK"
        if total >= self.SOLID:
            return "SOLID"
        if total >= self.WEAK:
            return "SCHWACH"
        if total <= -self.WEAK:
            return "GEGEN"  # Setup gegen Marktbias
        return "NEUTRAL"

    def _classify_prior(self, prior: MarketProfileResult) -> str:
        shape = prior.profile_shape
        rng = prior.range_high - prior.range_low
        body = prior.close_price - prior.open_price
        if shape == "trend" and body > 0:
            return "TrendDay_Bull"
        if shape == "trend" and body < 0:
            return "TrendDay_Bear"
        if shape == "p":
            return "p_Profile"
        if shape == "b":
            return "b_Profile"
        if abs(body) > rng * 0.6 and body > 0:
            return "DoubleDistribution_Bull"
        if abs(body) > rng * 0.6 and body < 0:
            return "DoubleDistribution_Bear"
        return "NormalDay"

    def _close_pct(self, prior: MarketProfileResult) -> float:
        rng = prior.range_high - prior.range_low
        if rng <= 0:
            return 0.0
        pos = (prior.close_price - prior.range_low) / rng
        return float(round(pos * 100))

    # ==================================================================
    def _render_narrative(
        self,
        setup_name: str,
        direction: str,
        strength: str,
        total: int,
        price: float,
        monthly: VolumeProfileResult,
        weekly: VolumeProfileResult,
        daily: MarketProfileResult,
        prior: MarketProfileResult,
        oi: Optional[OIResult],
        cvd: Optional[CVDResult],
        reasons: List[ReasonRow],
    ) -> str:
        lines: List[str] = []
        lines.append(f"Trading/Analyse-Bot hat das hier gesagt:")
        lines.append(f"")
        lines.append(f"Aktuelles Setup: {setup_name} (Score {total:+d}, {strength}).")
        lines.append("")

        # Profile-Kontext
        lines.append(
            f"Auf dem Monthly Profile sitzen wir bei {price:.2f} - VAH {monthly.vah:.2f}, "
            f"POC {monthly.poc:.2f}, VAL {monthly.val:.2f}. "
            f"Weekly: VAH {weekly.vah:.2f}, POC {weekly.poc:.2f}, VAL {weekly.val:.2f}."
        )

        # Vortag
        lines.append(
            f"Der Vortag schloss als {self._classify_prior(prior)} (Open {prior.open_price:.2f}, "
            f"Close {prior.close_price:.2f}, Range {prior.range_low:.2f}-{prior.range_high:.2f}). "
            f"POC {prior.poc:.2f}, Value Area {prior.val:.2f}-{prior.vah:.2f}."
        )

        # Heute
        lines.append(
            f"Heutige Auction: Open Type '{daily.open_type}', Profil '{daily.profile_shape}', "
            f"IB {daily.ib_low:.2f}-{daily.ib_high:.2f}. "
            f"{'Range Extension nach oben.' if daily.range_extension_up else ''}"
            f"{' Range Extension nach unten.' if daily.range_extension_down else ''}"
        )
        if daily.single_prints:
            sp_above = [s for s in daily.single_prints if s > price]
            sp_below = [s for s in daily.single_prints if s < price]
            if sp_above:
                lines.append(f"Single Prints oberhalb bei {', '.join(f'{s:.2f}' for s in sp_above[:3])} - schwache Auction-Zonen, die wieder geschlossen werden koennen.")
            if sp_below:
                lines.append(f"Single Prints unterhalb bei {', '.join(f'{s:.2f}' for s in sp_below[:3])} - klassische Magnet-Levels.")

        # Orderflow
        if oi:
            lines.append(
                f"Open Interest hat sich um {oi.delta_coins:+.0f} Coins ({oi.delta_pct:+.2f}%) "
                f"in den letzten Stunden veraendert."
            )
        if cvd:
            lines.append(
                f"CVD: Perp {cvd.perp_cvd:+.0f}, Spot {cvd.spot_cvd:+.0f}, "
                f"juengstes Delta Perp {cvd.perp_delta_recent:+.0f} / Spot {cvd.spot_delta_recent:+.0f} - "
                f"Divergenz: {cvd.divergence}."
            )

        lines.append("")
        # Dalton-typische Schlussreflexion
        if direction == "SHORT":
            lines.append(
                "Die Auction zeigt responsive Verkaeufer am Resistance-Cluster. "
                "Solange Preis unter dem Reaktionshoch bleibt und Akzeptanz darueber ausbleibt, "
                "bleibt das Bias defensiv. Vorsicht bei OI-Aufbau gegen die Bewegung - "
                "das waere ein Hinweis auf trapped Shorts."
            )
        elif direction == "LONG":
            lines.append(
                "Responsive Buyer verteidigen das untere Value-Cluster. "
                "Solange Preis ueber dem Reaktionstief bleibt, kann sich die Auction nach oben "
                "rotieren - vor allem wenn Single Prints darueber als Magnet wirken. "
                "Achte auf Akzeptanz im Vortags-Value als Bestaetigung."
            )
        else:
            lines.append(
                "Markt ist in Balance, ohne klare Konfluenz. Responsive Trade in der Value Area "
                "bevorzugt, kein Breakout-Trade ohne Akzeptanz ausserhalb der Range."
            )

        return "\n".join(lines)
