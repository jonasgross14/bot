"""
Einstiegspunkt fuer den Auction-Theory-Bot.

Modi:
- live      : holt regelmaessig neue Daten und erzeugt MGI-Dashboards
- backtest  : laeuft ueber einen Zeitraum und produziert ein Dashboard pro Tag
- once      : einmaliger Durchlauf (Debug)

Beispiele:
    python main.py                        # Live, Default-Pair (BTC/USDT Perp)
    python main.py --mode once
    python main.py --symbol ETH/USDT --perp ETH/USDT:USDT
    python main.py --mode backtest --start 2024-01-01 --end 2024-01-07
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from analyzer import MGIAnalyzer, MGISignal
from config import CONFIG, Config
from data_fetcher import DataFetcher
from market_profile import MarketProfile, MarketProfileResult
from orderflow import Orderflow
from visualizer import MGIVisualizer, VolumeProfileChart
from volume_profile import VolumeProfile


# ---------------------------------------------------------------------------
def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
class BotOrchestrator:
    """Bringt alle Module zusammen."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        cfg.ensure_output_dir()

        self.fetcher = DataFetcher(
            exchange_id=cfg.exchange,
            symbol=cfg.symbol,
            perp_symbol=cfg.perp_symbol,
            spot_symbol=cfg.spot_symbol,
            api_key=cfg.api_key,
            api_secret=cfg.api_secret,
        )
        self.vp = VolumeProfile(
            num_bins=cfg.vp_num_bins,
            value_area_percent=cfg.value_area_percent,
            hvn_threshold=cfg.hvn_threshold,
            lvn_threshold=cfg.lvn_threshold,
        )
        self.mp = MarketProfile(
            tpo_size_minutes=cfg.tpo_size_minutes,
            initial_balance_periods=cfg.initial_balance_periods,
            value_area_percent=cfg.value_area_percent,
        )
        self.of = Orderflow(
            oi_lookback_minutes=cfg.oi_lookback_minutes,
            cvd_lookback_minutes=cfg.cvd_lookback_minutes,
        )
        self.analyzer = MGIAnalyzer(symbol=cfg.symbol)
        self.visualizer = MGIVisualizer(output_dir=cfg.output_dir)
        self.profile_chart = VolumeProfileChart(output_dir=cfg.output_dir)

        self._stop = False

    # ------------------------------------------------------------------
    def request_stop(self, *_: object) -> None:
        self._stop = True
        logging.info("Stopp angefordert - Loop endet nach naechster Iteration.")

    # ------------------------------------------------------------------
    def run_once(self) -> Optional[MGISignal]:
        """Ein vollstaendiger Analyse-Durchlauf."""
        logging.info("Starte Analyse-Durchlauf fuer %s", self.cfg.symbol)

        try:
            ohlcv_30m = self.fetcher.history_window(days=35, timeframe="30m", market="perp")
            if ohlcv_30m is None or ohlcv_30m.empty:
                logging.warning("Keine OHLCV-Daten - Abbruch.")
                return None
            current_price = float(ohlcv_30m["close"].iloc[-1])

            # Monthly Profile (~30 Tage)
            cutoff_m = ohlcv_30m["timestamp"].max() - 30 * 24 * 60 * 60_000
            monthly_df = ohlcv_30m[ohlcv_30m["timestamp"] >= cutoff_m]
            monthly_vp = self.vp.compute(monthly_df)

            # Weekly Profile
            cutoff_w = ohlcv_30m["timestamp"].max() - 7 * 24 * 60 * 60_000
            weekly_df = ohlcv_30m[ohlcv_30m["timestamp"] >= cutoff_w]
            weekly_vp = self.vp.compute(weekly_df)

            # Daily Market Profile (heute)
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today_ms = int(today.timestamp() * 1000)
            today_df = ohlcv_30m[ohlcv_30m["timestamp"] >= today_ms]
            if today_df.empty:
                today_df = ohlcv_30m.tail(self.cfg.session_length_hours * 2)

            # Vortag
            prior_start = today_ms - 24 * 60 * 60_000
            prior_df = ohlcv_30m[
                (ohlcv_30m["timestamp"] >= prior_start) & (ohlcv_30m["timestamp"] < today_ms)
            ]
            if prior_df.empty:
                prior_df = ohlcv_30m.iloc[-96:-48] if len(ohlcv_30m) >= 96 else ohlcv_30m.head(48)

            prior_mp = self.mp.compute(prior_df)
            daily_mp = self.mp.compute(today_df, prior_session=prior_mp)

            # Orderflow
            try:
                oi_df = self.fetcher.fetch_open_interest_hist(period="5m", limit=200)
                oi_result = self.of.compute_oi(oi_df)
            except Exception as exc:
                logging.warning("OI konnte nicht geladen werden: %s", exc)
                oi_result = None

            try:
                trades_perp = self.fetcher.trades_window(minutes=120, market="perp")
                trades_spot = self.fetcher.trades_window(minutes=120, market="spot")
                cvd_result = self.of.compute_cvd(trades_perp, trades_spot)
            except Exception as exc:
                logging.warning("CVD konnte nicht berechnet werden: %s", exc)
                cvd_result = None

            # 5D-OHLCV fuer Delta
            cutoff_5d = ohlcv_30m["timestamp"].max() - 5 * 24 * 60 * 60_000
            recent_5d = ohlcv_30m[ohlcv_30m["timestamp"] >= cutoff_5d]

            signal = self.analyzer.analyze(
                current_price=current_price,
                monthly_vp=monthly_vp,
                weekly_vp=weekly_vp,
                daily_mp=daily_mp,
                prior_day_mp=prior_mp,
                oi=oi_result,
                cvd=cvd_result,
                recent_ohlcv=recent_5d,
            )

            self._persist(signal, monthly_vp, ohlcv_30m, oi_result, cvd_result)
            return signal

        except Exception as exc:
            logging.exception("Fehler im Analyse-Durchlauf: %s", exc)
            return None

    # ------------------------------------------------------------------
    def _persist(self, signal: MGISignal, monthly_vp, ohlcv, oi_result, cvd_result) -> None:
        ts = signal.timestamp.strftime("%Y%m%d_%H%M%S")
        sym = signal.symbol.replace("/", "")

        # Konsolen-Ausgabe (wie Yugo: "Trading/Analyse Bot hat das hier gesagt...")
        print("\n" + "=" * 80)
        print(f"  {signal.setup_name}  [{signal.direction} {signal.strength}]   Score {signal.total_score}")
        print("=" * 80)
        print(signal.narrative)
        print("=" * 80 + "\n")

        if self.cfg.save_text:
            txt_path = f"{self.cfg.output_dir}/mgi_{sym}_{ts}.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(self._format_text(signal))
            logging.info("Analyse-Text gespeichert: %s", txt_path)

        if self.cfg.save_chart:
            try:
                dashboard_path = self.visualizer.render(signal)
                logging.info("Dashboard gespeichert: %s", dashboard_path)
            except Exception as exc:
                logging.warning("Dashboard-Render fehlgeschlagen: %s", exc)
            try:
                cvd_series = cvd_result.perp_series if cvd_result is not None else None
                oi_series = oi_result.series if oi_result is not None else None
                chart_path = self.profile_chart.render(
                    ohlcv.tail(500), monthly_vp,
                    oi_series=oi_series, cvd_series=cvd_series,
                )
                logging.info("Profile-Chart gespeichert: %s", chart_path)
            except Exception as exc:
                logging.warning("Profile-Chart fehlgeschlagen: %s", exc)

    def _format_text(self, signal: MGISignal) -> str:
        lines = []
        lines.append(f"MGI SIGNAL  {signal.timestamp.strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"Symbol: {signal.symbol}    Preis: {signal.current_price:.2f}")
        lines.append(f"Setup:  {signal.setup_name}  [{signal.direction} {signal.strength}]")
        lines.append(f"Score:  Basis {signal.basis_score:+d} | Kontext {signal.kontext_score:+d} | "
                     f"Intraday {signal.intraday_score:+d} | Total {signal.total_score:+d}")
        lines.append(f"Bias:   Monthly {signal.monthly_bias} | Weekly {signal.weekly_bias}")
        lines.append("")
        lines.append("KONTEXT:")
        for r in signal.kontext:
            lines.append(f"  - {r.label:<14} {r.value:<28} ({r.score:+d})")
        lines.append("")
        lines.append("INTRADAY:")
        for r in signal.intraday:
            lines.append(f"  [{r.icon}] {r.text} ({r.score:+d})")
        lines.append("")
        lines.append("BEGRUENDUNG:")
        for r in signal.reasons:
            lines.append(f"  - {r.text}  ({r.score:+d})")
        lines.append("")
        lines.append("TAKE PROFIT:")
        for tp in signal.take_profits:
            lines.append(f"  {tp.label}  {tp.price:>12.2f}   {tp.note:<22}  R/R 1:{tp.rr:.2f}")
        if signal.stop_loss:
            sl_p, sl_l, sl_pct = signal.stop_loss
            lines.append(f"\nSTOP LOSS REFERENZ: {sl_p:.2f}   ({sl_l},  {sl_pct:+.2f}%)")
        lines.append("")
        lines.append("LEVEL MAP:")
        for r in signal.level_map:
            arrow = "▲" if r.direction == "up" else "▼" if r.direction == "down" else "▶"
            lines.append(f"  {arrow} {r.price:>12.2f}  {r.label:<18}  {r.distance_pct:+.2f}%")
        lines.append("")
        lines.append(f"Vortag: {signal.vortag_label} | Close {signal.close_pct:.0f}% | {signal.ac_status}")
        lines.append("")
        lines.append("=" * 70)
        lines.append(signal.narrative)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def run_live(self) -> None:
        logging.info("Live-Modus gestartet. Intervall: %ds", self.cfg.live_interval_seconds)
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)
        while not self._stop:
            self.run_once()
            for _ in range(self.cfg.live_interval_seconds):
                if self._stop:
                    break
                time.sleep(1)
        logging.info("Live-Loop sauber beendet.")

    # ------------------------------------------------------------------
    def run_backtest(self, start: str, end: str) -> None:
        logging.info("Backtest %s -> %s", start, end)
        try:
            df = self.fetcher.backtest_window(start, end, timeframe="30m", market="perp")
        except Exception as exc:
            logging.error("Backtest-Daten konnten nicht geladen werden: %s", exc)
            return
        if df is None or df.empty:
            logging.warning("Backtest: keine Daten geladen.")
            return

        df["day"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.date
        days = sorted(df["day"].unique())
        if len(days) < 2:
            logging.warning("Backtest: zu wenige Tage in Range.")
            return

        for i, day in enumerate(days[1:], start=1):
            try:
                prior_df = df[df["day"] == days[i - 1]]
                today_df = df[df["day"] == day]
                if prior_df.empty or today_df.empty:
                    continue

                cutoff = today_df["timestamp"].max()
                hist_30 = df[df["timestamp"] <= cutoff].tail(30 * 24 * 2)
                hist_7 = df[df["timestamp"] <= cutoff].tail(7 * 24 * 2)
                if hist_30.empty or hist_7.empty:
                    continue

                monthly_vp = self.vp.compute(hist_30)
                weekly_vp = self.vp.compute(hist_7)
                prior_mp = self.mp.compute(prior_df)
                daily_mp = self.mp.compute(today_df, prior_session=prior_mp)

                signal_obj = self.analyzer.analyze(
                    current_price=float(today_df["close"].iloc[-1]),
                    monthly_vp=monthly_vp,
                    weekly_vp=weekly_vp,
                    daily_mp=daily_mp,
                    prior_day_mp=prior_mp,
                    oi=None,
                    cvd=None,
                    recent_ohlcv=df[df["timestamp"] <= cutoff].tail(5 * 48),
                )
                # Manueller Timestamp im Backtest
                signal_obj.timestamp = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
                self._persist(signal_obj, monthly_vp, hist_7, None, None)
            except Exception as exc:
                logging.warning("Backtest-Tag %s: %s", day, exc)

        logging.info("Backtest abgeschlossen (%d Tage).", len(days) - 1)


# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Auction-Theory Bot (MGI-Style)")
    p.add_argument("--mode", choices=["live", "once", "backtest"], default=None)
    p.add_argument("--symbol", default=None, help="z.B. BTC/USDT")
    p.add_argument("--perp", default=None, help="z.B. BTC/USDT:USDT")
    p.add_argument("--exchange", default=None)
    p.add_argument("--start", default=None, help="Backtest-Start YYYY-MM-DD")
    p.add_argument("--end", default=None, help="Backtest-Ende YYYY-MM-DD")
    p.add_argument("--interval", type=int, default=None, help="Live-Intervall in Sekunden")
    return p.parse_args()


def apply_args(cfg: Config, args: argparse.Namespace) -> Config:
    if args.mode:
        cfg.mode = args.mode
    if args.symbol:
        cfg.symbol = args.symbol
    if args.perp:
        cfg.perp_symbol = args.perp
    if args.exchange:
        cfg.exchange = args.exchange
    if args.start:
        cfg.backtest_start = args.start
    if args.end:
        cfg.backtest_end = args.end
    if args.interval:
        cfg.live_interval_seconds = args.interval
    return cfg


# ---------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    cfg = apply_args(CONFIG, args)
    setup_logging(cfg.log_level)

    bot = BotOrchestrator(cfg)
    mode = cfg.mode.lower()
    if mode == "live":
        bot.run_live()
    elif mode == "once":
        bot.run_once()
    elif mode == "backtest":
        bot.run_backtest(cfg.backtest_start, cfg.backtest_end)
    else:
        print(f"Unbekannter Modus: {cfg.mode}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
