# Auction-Theory-Bot (MGI-Style)

Reiner Analyse-Bot fuer Crypto-Futures auf Basis von **Market Profile**, **Volume Profile** und **Auction Theory** nach Steidlmayer / Dalton (*Mind Over Markets*) — angereichert mit **Open Interest** und **Cumulative Volume Delta** (CVD) fuer Spot und Perpetuals.

> Der Bot gibt **keine Buy/Sell-Signale**. Er liefert kontextbasierte Analysen im Stil eines erfahrenen Market-Profile-Traders ("Trading/Analyse-Bot hat das hier gesagt …") inklusive eines MGI-Dashboard-PNGs (siehe Vorbild [@YugoBetrug0](https://x.com/YugoBetrug0)).

---

## Features

- **Volume Profile** mit POC, VAH/VAL, HVN/LVN
- **Market Profile** (TPO) mit Initial Balance, Single Prints, Open-Type, Profile-Shape (b, p, normal, trend), Acceptance/Rejection des Vortags-Values
- **Open Interest** (in Coins, nicht USD), Veraenderung ueber konfigurierbarem Lookback
- **CVD** fuer Spot und Perp inkl. Divergenz-Klassifikation (`spot-fuehrt`, `perp-fuehrt`, `parallel`, `gegen`)
- **Multi-Timeframe-Profile**: Monthly, Weekly, Daily, Vortag
- **MGI-Signal-Dashboard** als PNG: Setup-Name, Strength-Tag, Score-Aufbau, Kontext-Spalte, Begruendung, TP/SL, Level-Map
- **Profile-Chart** als zweites PNG (Preis + Volume Profile + OI + CVD)
- **Live-Modus** (Loop) und **Backtest-Modus** (taegliche Dashboards)
- Konfigurierbar fuer beliebige Pairs / Exchanges (Binance, Bybit) ueber `.env`

---

## Installation

### 1. Voraussetzungen

- Python 3.11+
- macOS / Linux / Windows

### 2. Virtuelle Umgebung anlegen

```bash
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows
```

### 3. Abhaengigkeiten installieren

```bash
pip install -r requirements.txt
```

### 4. Konfiguration vorbereiten

```bash
cp .env.example .env
# .env oeffnen und ggf. anpassen (Symbol, Timeframes, Modus, ...)
```

> **API-Keys sind NICHT zwingend noetig.** Alle abgefragten Endpunkte (OHLCV, Trades, Open-Interest-History) sind public. Keys hebt nur die Rate-Limits.
>
> Falls Binance bei dir regional geblockt ist (HTTP 451), setze `EXCHANGE=bybit` in `.env`. Die OI-Historie ist aktuell nur fuer Binance Futures implementiert — auf Bybit laeuft der Bot dann ohne OI-Daten weiter.

---

## Bot starten

### Einmaliger Durchlauf (Debug / Test)

```bash
python main.py --mode once
```

Erzeugt im Ordner `output/`:

- `mgi_BTCUSDT_<timestamp>.txt` – ausfuehrliche Text-Analyse auf Deutsch
- `mgi_BTCUSDT_<timestamp>.png` – Dashboard im MGI-Stil
- `profile_<timestamp>.png` – Preis + Volume Profile + OI + CVD

### Live-Modus (alle paar Minuten neu)

```bash
python main.py --mode live
```

Default-Intervall: 300 Sekunden (5 Minuten), aenderbar in `.env` (`LIVE_INTERVAL_SECONDS`).

### Backtest

```bash
python main.py --mode backtest --start 2024-01-01 --end 2024-01-14
```

Erzeugt fuer jeden Tag im Range ein Dashboard auf Basis der vorhandenen historischen Profile.

### Anderes Pair (z. B. ETH)

```bash
python main.py --symbol ETH/USDT --perp ETH/USDT:USDT --mode live
```

oder dauerhaft in `.env`:

```env
SYMBOL=ETH/USDT
SPOT_SYMBOL=ETH/USDT
PERP_SYMBOL=ETH/USDT:USDT
```

---

## Konfiguration (`.env`)

| Variable | Default | Bedeutung |
|---|---|---|
| `SYMBOL` | `BTC/USDT` | Anzeige-Symbol |
| `PERP_SYMBOL` | `BTC/USDT:USDT` | ccxt-Perpetual-Symbol |
| `SPOT_SYMBOL` | `BTC/USDT` | Spot-Symbol fuer CVD-Vergleich |
| `EXCHANGE` | `binance` | `binance` oder `bybit` |
| `TIMEFRAMES` | `5m,15m,30m,1h,4h,1d` | Komma-Liste der unterstuetzten Timeframes |
| `PROFILE_TIMEFRAME` | `30m` | Basis-Timeframe fuer das Profile |
| `VP_NUM_BINS` | `80` | Anzahl Preis-Bins im Volume Profile |
| `VALUE_AREA_PERCENT` | `0.70` | Value-Area-Anteil (klassisch 70 %) |
| `HVN_THRESHOLD` | `1.5` | x mean-Volume → HVN |
| `LVN_THRESHOLD` | `0.4` | x mean-Volume → LVN |
| `TPO_SIZE_MINUTES` | `30` | Laenge eines TPO-Buchstabens |
| `INITIAL_BALANCE_PERIODS` | `2` | Anzahl TPO-Perioden, die die IB definieren |
| `OI_LOOKBACK_MINUTES` | `60` | Lookback fuer OI-Delta |
| `CVD_LOOKBACK_MINUTES` | `60` | Lookback fuer juengstes Delta |
| `MODE` | `live` | `live`, `once`, `backtest` |
| `LIVE_INTERVAL_SECONDS` | `300` | Live-Loop-Intervall |
| `OUTPUT_DIR` | `./output` | Zielordner fuer Dashboards / Logs |
| `SAVE_TEXT` / `SAVE_CHART` | `true` | Persistierung an/aus |

---

## Ausgabe verstehen

Das Dashboard ist in 3 Spalten aufgebaut:

**KONTEXT** – Multi-Timeframe-Bias  
- Trend (Monthly + Weekly), Marktphase (Balance / Discovery), 5-Tage-Delta, Range-Lokation, Flow (CVD), CVD-Divergenz.  
- Jede Zeile vergibt +1 / -1 / 0 Punkt → `Kontext Total`.

**BEGRUENDUNG (Basis Score)** – Setup-Begruendung im Klartext  
- z. B. *Monthly VAH getestet und gehalten (+3)*, *SellingTail bestaetigt Ablehnung (+2)*.  
- Darunter: **TAKE PROFIT** (TP0/TP1/TP+) mit Risk/Reward, **STOP LOSS REFERENZ** mit prozentualer Distanz.

**LEVEL MAP** – alle relevanten Levels im Umkreis von +/-2.5 % um den aktuellen Preis  
- Weekly/Monthly VAH/POC/VAL, PrevHigh/Low/POC/VAH/VAL, HVN, LVN.  
- Jeweils prozentualer Abstand zum aktuellen Preis.

Die Header-Zeile zeigt:
- Setup-Name (z. B. *Monthly/Weekly VAH Resistance Bear*)
- Strength-Badge (`LONG STARK`, `SHORT SCHWACH`, `NEUTRAL`)
- Aktueller Preis
- Score-Aufbau: `Basis +Kontext +Intraday = Total`
- Monthly / Weekly Bias

---

## Architektur

```
main.py                   # Orchestrierung + CLI
config.py                 # zentrale Settings (.env)
data_fetcher.py           # OHLCV / Trades / OI via ccxt + Binance fapi
volume_profile.py         # POC, VAH/VAL, HVN/LVN
market_profile.py         # TPO, IB, Single Prints, Open Type, Acceptance
orderflow.py              # OI-Delta, CVD Spot/Perp, Divergenz-Klassifikation
analyzer.py               # MGISignal-Engine: Setup-Detection + Scoring + Narrative
visualizer.py             # MGI-Dashboard-PNG + Profile-Chart-PNG
```

**Erweiterbarkeit**:

- Neue Setups → Methode `_detect_setup` und `_build_reasons` in `analyzer.py`
- Andere Bias-Logik → `_build_kontext`
- Andere Score-Schwellen → Klassen-Konstanten `STRONG`, `SOLID`, `WEAK` in `MGIAnalyzer`
- Andere Timeframes / Sessions → `.env`

---

## Hinweise zur Methodik

Die Logik basiert auf den Konzepten aus:

- **J. Peter Steidlmayer** – Market Profile / TPO
- **James Dalton** – *Mind Over Markets* (Initial Balance, Open Type, Acceptance/Rejection, Single Prints, Poor Highs/Lows, b/p/Trend/Normal Day)
- **Auction Market Theory** – Responsive vs. Initiative Activity
- **Modern Crypto Orderflow** – CVD-Divergenzen Spot vs. Perp, OI-Aufbau / Liquidation

Klassische Trend-Indikatoren (RSI, MACD, MAs, Bollinger Bands etc.) werden bewusst **nicht** verwendet — es geht ausschliesslich um die Auktion und die Akzeptanz von Preis durch das Volumen.

---

## Disclaimer

Der Bot ist ein **Analyse- und Lernwerkzeug**, kein Trading-System. Keine Anlageempfehlung. Trading mit Crypto-Futures ist hochriskant; Verluste koennen das eingesetzte Kapital uebersteigen.
