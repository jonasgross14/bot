"""
Visualizer - rendert das MGI-Signal als Dashboard-PNG im Yugo-Stil.

Aufbau (siehe Vorlage @YugoBetrug0):
- Header mit Zeitstempel, Setup-Name, Strength-Badge, Aktueller Preis,
  Score-Aufbau, Monthly/Weekly Bias
- Drei Spalten: KONTEXT | BEGRUENDUNG (+ TP/SL) | LEVEL MAP
- Footer mit Vortag-Kategorie, Close-%, AC-Status

Zusaetzlich kann ein Volume-Profile-Chart als zweites PNG erzeugt werden.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, Rectangle

from analyzer import MGISignal


# ----- Farbpalette (dunkles Theme wie Yugo) ---------------------------------
BG = "#0e1116"
PANEL = "#161a22"
PANEL_BORDER = "#262b36"
ACCENT = "#e0bf52"          # gold
TEXT = "#e6e6e6"
TEXT_DIM = "#8a93a3"
GREEN = "#3ddc84"
RED = "#ff5c5c"
ORANGE = "#ff9f43"
BLUE = "#5aa8ff"
NEUTRAL = "#888a92"


def _strength_color(direction: str, strength: str) -> str:
    if direction == "LONG":
        return GREEN
    if direction == "SHORT":
        return RED
    return NEUTRAL


def _score_color(score: int) -> str:
    if score > 0:
        return GREEN
    if score < 0:
        return RED
    return TEXT_DIM


def _signed(score: int) -> str:
    return f"+{score}" if score >= 0 else f"{score}"


# ===========================================================================
class MGIVisualizer:
    """Rendert MGISignal als Dashboard-PNG."""

    def __init__(self, output_dir: str = "./output") -> None:
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    def render(self, signal: MGISignal, filename: Optional[str] = None) -> str:
        fig = plt.figure(figsize=(14.5, 9.0), dpi=130)
        fig.patch.set_facecolor(BG)

        # ----- Top-/Bottom-Bar (akzentlinien) -----
        fig.add_axes([0, 0.985, 1, 0.015], facecolor=ACCENT, frameon=False, xticks=[], yticks=[])
        fig.add_axes([0, 0, 1, 0.005], facecolor=ACCENT, frameon=False, xticks=[], yticks=[])

        # ----- Header -----
        self._draw_header(fig, signal)

        # ----- Trennlinie unter Header -----
        line = fig.add_axes([0.04, 0.745, 0.92, 0.001], facecolor=PANEL_BORDER, frameon=False, xticks=[], yticks=[])

        # ----- 3 Spalten -----
        col_w = 0.295
        gap = 0.015
        x0 = 0.04
        y0 = 0.08
        h = 0.66

        self._draw_kontext(fig, signal, [x0, y0, col_w, h])
        self._draw_reasons(fig, signal, [x0 + col_w + gap, y0, col_w, h])
        self._draw_levelmap(fig, signal, [x0 + 2 * (col_w + gap), y0, col_w, h])

        # ----- Footer -----
        self._draw_footer(fig, signal)

        # ----- speichern -----
        if filename is None:
            ts = signal.timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"mgi_{signal.symbol.replace('/', '')}_{ts}.png"
        path = os.path.join(self.output_dir, filename)
        fig.savefig(path, facecolor=BG, bbox_inches=None, pad_inches=0)
        plt.close(fig)
        return path

    # ==================================================================
    #  Header
    # ==================================================================
    def _draw_header(self, fig, sig: MGISignal) -> None:
        ax = fig.add_axes([0, 0.76, 1, 0.225], frameon=False)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_facecolor(BG)

        ts = sig.timestamp.strftime("%d.%m.%Y %H:%M")
        ax.text(0.04, 0.85, f"MGI SIGNAL  ·  {ts}",
                color=ACCENT, fontsize=11, fontweight="bold", family="monospace")

        ax.text(0.04, 0.55, sig.setup_name,
                color=TEXT, fontsize=24, fontweight="bold")

        # Strength badge
        badge_color = _strength_color(sig.direction, sig.strength)
        badge_text = f"{sig.direction} {sig.strength}"
        bbox_x, bbox_y, bbox_w, bbox_h = 0.04, 0.18, 0.155, 0.18
        rect = FancyBboxPatch(
            (bbox_x, bbox_y), bbox_w, bbox_h,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            linewidth=1.2,
            edgecolor=badge_color,
            facecolor=badge_color + "22",
            transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(bbox_x + bbox_w / 2, bbox_y + bbox_h / 2, badge_text,
                ha="center", va="center",
                color=badge_color, fontsize=11, fontweight="bold")

        # rechts: Preis + Score
        ax.text(0.96, 0.85, "AKTUELLER PREIS",
                ha="right", color=TEXT_DIM, fontsize=10, family="monospace")
        ax.text(0.96, 0.50, f"{sig.current_price:,.0f}".replace(",", "."),
                ha="right", color=TEXT, fontsize=34, fontweight="bold")

        score_str = f"{sig.basis_score:+d} {sig.kontext_score:+d} {sig.intraday_score:+d} {sig.extra_a:+d} {sig.extra_b:+d}"
        ax.text(0.96, 0.27,
                f"{score_str}  =  Score {sig.total_score}",
                ha="right", color=ORANGE, fontsize=12, family="monospace", fontweight="bold")

        ax.text(0.96, 0.08,
                f"Monthly {sig.monthly_bias}  ·  Weekly {sig.weekly_bias}",
                ha="right", color=TEXT_DIM, fontsize=10, family="monospace")

    # ==================================================================
    #  Kontext-Spalte
    # ==================================================================
    def _draw_kontext(self, fig, sig: MGISignal, rect: List[float]) -> None:
        ax = self._panel(fig, rect, "KONTEXT")

        y = 0.92
        line_h = 0.055
        for row in sig.kontext:
            ax.text(0.05, y, row.label, color=TEXT_DIM, fontsize=10)
            ax.text(0.72, y, row.value, color=TEXT, fontsize=10, fontweight="bold", ha="right")
            ax.text(0.95, y, _signed(row.score), color=_score_color(row.score),
                    fontsize=10, fontweight="bold", ha="right", family="monospace")
            y -= line_h

        # Total
        y -= 0.02
        ax.plot([0.05, 0.95], [y, y], color=PANEL_BORDER, linewidth=0.6)
        y -= 0.04
        kontext_total = sum(r.score for r in sig.kontext)
        ax.text(0.05, y, "Kontext Total", color=ACCENT, fontsize=11, fontweight="bold")
        ax.text(0.95, y, _signed(kontext_total), color=_score_color(kontext_total),
                fontsize=11, fontweight="bold", ha="right", family="monospace")
        y -= 0.07

        # Intraday-Sektion
        ax.text(0.05, y, "— INTRADAY", color=TEXT_DIM, fontsize=9, family="monospace")
        y -= 0.05
        for row in sig.intraday:
            icon = self._icon_str(row.icon)
            color = self._icon_color(row.icon)
            ax.text(0.05, y, icon, color=color, fontsize=11)
            ax.text(0.13, y, row.text, color=TEXT, fontsize=9.5)
            if row.score != 0:
                ax.text(0.95, y, _signed(row.score), color=_score_color(row.score),
                        fontsize=9, ha="right", family="monospace")
            y -= 0.05

    # ==================================================================
    #  Begruendung + TP / SL
    # ==================================================================
    def _draw_reasons(self, fig, sig: MGISignal, rect: List[float]) -> None:
        ax = self._panel(fig, rect, f"BEGRUENDUNG (BASIS SCORE: {sig.basis_score})")

        y = 0.92
        for r in sig.reasons:
            ax.text(0.05, y, r.text, color=TEXT, fontsize=10)
            ax.text(0.95, y, _signed(r.score), color=_score_color(r.score),
                    fontsize=10, fontweight="bold", ha="right", family="monospace")
            y -= 0.06

        # ----- Take Profit -----
        y -= 0.04
        ax.text(0.05, y, "TAKE PROFIT", color=GREEN, fontsize=10, fontweight="bold", family="monospace")
        y -= 0.06
        for tp in sig.take_profits[:4]:
            ax.text(0.05, y, tp.label, color=GREEN, fontsize=10, fontweight="bold", family="monospace")
            ax.text(0.18, y, f"{tp.price:,.0f}".replace(",", "."), color=TEXT, fontsize=10, family="monospace")
            ax.text(0.42, y, tp.note, color=TEXT_DIM, fontsize=9.5)
            ax.text(0.95, y, f"R/R 1:{tp.rr:.2f}", color=TEXT_DIM, fontsize=9.5, ha="right", family="monospace")
            y -= 0.055

        # ----- Stop Loss -----
        y -= 0.03
        ax.text(0.05, y, "STOP LOSS REFERENZ", color=RED, fontsize=10, fontweight="bold", family="monospace")
        y -= 0.06
        if sig.stop_loss is not None:
            sl_price, sl_label, sl_pct = sig.stop_loss
            ax.text(0.05, y, "SL", color=RED, fontsize=10, fontweight="bold", family="monospace")
            ax.text(0.18, y, f"{sl_price:,.0f}".replace(",", "."), color=TEXT, fontsize=10, family="monospace")
            ax.text(0.42, y, sl_label, color=TEXT_DIM, fontsize=9.5)
            ax.text(0.95, y, f"{sl_pct:+.2f}%", color=ORANGE, fontsize=9.5, ha="right", family="monospace")

    # ==================================================================
    #  Level Map
    # ==================================================================
    def _draw_levelmap(self, fig, sig: MGISignal, rect: List[float]) -> None:
        ax = self._panel(fig, rect, "LEVEL MAP")

        rows = sig.level_map[:14]
        if not rows:
            return
        y = 0.92
        line_h = min(0.06, 0.85 / max(len(rows), 1))
        for row in rows:
            if row.direction == "current":
                # Highlight-Box
                ax.add_patch(Rectangle((0.02, y - line_h * 0.45), 0.96, line_h * 0.9,
                                       facecolor=ACCENT + "22", edgecolor=ACCENT,
                                       linewidth=1.0, transform=ax.transAxes))
                ax.text(0.07, y, "▶", color=ACCENT, fontsize=10)
                ax.text(0.16, y, f"{row.price:,.0f}".replace(",", "."),
                        color=ACCENT, fontsize=10, fontweight="bold", family="monospace")
                ax.text(0.42, y, row.label, color=ACCENT, fontsize=10, fontweight="bold")
            else:
                arrow = "▲" if row.direction == "up" else "▼"
                color = RED if row.direction == "up" else GREEN
                ax.text(0.07, y, arrow, color=color, fontsize=9.5)
                ax.text(0.16, y, f"{row.price:,.0f}".replace(",", "."),
                        color=TEXT, fontsize=9.5, family="monospace")
                ax.text(0.42, y, row.label, color=TEXT_DIM, fontsize=9.5)
                ax.text(0.95, y, f"{row.distance_pct:+.2f}%",
                        color=color, fontsize=9.5, ha="right", family="monospace")
            y -= line_h

    # ==================================================================
    #  Footer
    # ==================================================================
    def _draw_footer(self, fig, sig: MGISignal) -> None:
        ax = fig.add_axes([0, 0.005, 1, 0.06], frameon=False)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_facecolor(BG)
        ax.text(
            0.04, 0.5,
            f"Vortag: {sig.vortag_label}  ·  Close {sig.close_pct:.0f}%  ·  {sig.ac_status}",
            color=TEXT_DIM, fontsize=9, family="monospace",
        )
        ax.text(0.96, 0.5, "@AuctionTheoryBot", color=TEXT_DIM,
                fontsize=9, ha="right", family="monospace")

    # ==================================================================
    #  Helpers
    # ==================================================================
    def _panel(self, fig, rect: List[float], title: str):
        ax = fig.add_axes(rect, frameon=False)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_facecolor(PANEL)
        # gerundetes Panel
        bg = FancyBboxPatch((0, 0), 1, 1,
                             boxstyle="round,pad=0,rounding_size=0.02",
                             linewidth=1.0, edgecolor=PANEL_BORDER, facecolor=PANEL,
                             transform=ax.transAxes)
        ax.add_patch(bg)
        ax.text(0.05, 0.97, title, color=ACCENT, fontsize=11, fontweight="bold", family="monospace",
                va="top")
        return ax

    def _icon_str(self, kind: str) -> str:
        return {"ok": "✔", "x": "✘", "warn": "▲", "bolt": "⚡"}.get(kind, "·")

    def _icon_color(self, kind: str) -> str:
        return {"ok": GREEN, "x": RED, "warn": ORANGE, "bolt": BLUE}.get(kind, TEXT_DIM)


# ===========================================================================
#  Optional: Volume-Profile-Chart als Beleg
# ===========================================================================
class VolumeProfileChart:
    """Erzeugt einen Preis-+Volume-Profile-Plot fuers Archiv."""

    def __init__(self, output_dir: str = "./output") -> None:
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def render(self, ohlcv, vp_result, oi_series=None, cvd_series=None,
               filename: Optional[str] = None) -> str:
        fig = plt.figure(figsize=(13, 7), dpi=120)
        fig.patch.set_facecolor(BG)

        # Preis-Plot
        ax_p = fig.add_axes([0.05, 0.55, 0.7, 0.4], facecolor=PANEL)
        ax_p.plot(ohlcv["datetime"], ohlcv["close"], color=BLUE, linewidth=1.0)
        ax_p.axhline(vp_result.poc, color=ORANGE, linestyle="--", linewidth=0.8, label=f"POC {vp_result.poc:.2f}")
        ax_p.axhline(vp_result.vah, color=GREEN, linestyle=":", linewidth=0.8, label=f"VAH {vp_result.vah:.2f}")
        ax_p.axhline(vp_result.val, color=RED, linestyle=":", linewidth=0.8, label=f"VAL {vp_result.val:.2f}")
        ax_p.tick_params(colors=TEXT_DIM)
        for spine in ax_p.spines.values():
            spine.set_color(PANEL_BORDER)
        ax_p.legend(facecolor=PANEL, edgecolor=PANEL_BORDER, labelcolor=TEXT, fontsize=8, loc="upper left")
        ax_p.set_title("Preis", color=ACCENT, fontsize=10, loc="left")

        # Volume Profile
        ax_v = fig.add_axes([0.78, 0.55, 0.18, 0.4], facecolor=PANEL, sharey=ax_p)
        ax_v.barh(vp_result.bins + vp_result.bin_size / 2, vp_result.volume_per_bin,
                  height=vp_result.bin_size * 0.9, color=BLUE, alpha=0.6)
        ax_v.axhline(vp_result.poc, color=ORANGE, linestyle="--", linewidth=0.8)
        ax_v.tick_params(colors=TEXT_DIM)
        for spine in ax_v.spines.values():
            spine.set_color(PANEL_BORDER)
        ax_v.set_title("Volume Profile", color=ACCENT, fontsize=10, loc="left")

        # OI
        if oi_series is not None and not oi_series.empty:
            ax_o = fig.add_axes([0.05, 0.30, 0.91, 0.18], facecolor=PANEL)
            ax_o.plot(oi_series["datetime"], oi_series["open_interest"], color=ORANGE, linewidth=1.0)
            ax_o.set_title("Open Interest (Coins)", color=ACCENT, fontsize=10, loc="left")
            ax_o.tick_params(colors=TEXT_DIM)
            for spine in ax_o.spines.values():
                spine.set_color(PANEL_BORDER)

        # CVD
        if cvd_series is not None and len(cvd_series) > 0:
            ax_c = fig.add_axes([0.05, 0.06, 0.91, 0.18], facecolor=PANEL)
            ax_c.plot(cvd_series.index, cvd_series.values, color=GREEN, linewidth=1.0)
            ax_c.axhline(0, color=TEXT_DIM, linewidth=0.5)
            ax_c.set_title("CVD Perp", color=ACCENT, fontsize=10, loc="left")
            ax_c.tick_params(colors=TEXT_DIM)
            for spine in ax_c.spines.values():
                spine.set_color(PANEL_BORDER)

        if filename is None:
            filename = f"profile_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(self.output_dir, filename)
        fig.savefig(path, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return path
