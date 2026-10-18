script "Elliott Wave Counter (ATR ZigZag)"

// ============================================================
//  Elliott-Wave-Zaehler mit zwei unabhaengigen Wellenebenen:
//    Ebene 1 (klein): 1-5, a-b-c, A-B-C, W-X-Y
//    Ebene 2 (gross): (1)-(5) eingekreist, Ⓐ-Ⓑ-Ⓒ, Ⓦ-Ⓧ-Ⓨ
//  Jede Ebene hat ihren eigenen ATR-ZigZag und zaehlt nach denselben
//  Regeln: Impuls 1-5, danach a-b-c. Eigenstaendige Zigzag-Korrekturen
//  A-B-C stehen erst fest, wenn "Welle 4" das Gebiet von "Welle 1"
//  ueberlappt; der Impuls wird dann sichtbar ungueltig (grau, X) und
//  dieselben Pivots bekommen zusaetzlich A-B-C. Zwei gleichgerichtete
//  A-B-C mit einem X-Schenkel dazwischen werden W-X-Y.
//  Gezaehlt wird nur auf bestaetigten Bars (on chart.close); ein einmal
//  gesetztes Label wird nie verschoben oder umbenannt.
//  Hinweis: Die Ebenen zaehlen unabhaengig, Ebene 1 wird NICHT in die
//  Wellen von Ebene 2 eingepasst (keine Unterzaehlung).
// ============================================================

input (
  // ATR-Laenge fuer die ZigZag-Schwelle (beide Ebenen)
  atrLen = input.int(14, title: "ATR-Laenge", min: 1, max: 200)
  // Ebene 1: Schwelle = ATR * Multiplikator. Ein Pivot gilt als bestaetigt,
  // sobald die Gegenbewegung vom letzten Extrem diese Schwelle erreicht.
  atrMult = input.float(3.0, title: "Ebene 1 (klein): ATR-Multiplikator", min: 0.5, max: 50.0)
  // Ebene 2 ein/aus
  showLevel2 = input.bool(true, title: "Ebene 2 (gross) anzeigen")
  // Ebene 2: deutlich groesser als Ebene 1 waehlen. 15 trifft auf 5m die
  // grossen Wellen (Hauptpivots) einer typischen Analysten-Zaehlung.
  atrMult2 = input.float(15.0, title: "Ebene 2 (gross): ATR-Multiplikator", min: 0.5, max: 50.0)
  // Ungueltige (gebrochene) Zaehlungen grau sichtbar lassen
  showInvalid = input.bool(true, title: "Ungueltige Zaehlungen anzeigen")
  // Eigenstaendige Korrekturen A-B-C und W-X-Y erkennen und beschriften
  showCorrections = input.bool(true, title: "Korrekturen A-B-C / W-X-Y anzeigen")
  // Fenster fuer den Zaehler "ungueltige Zaehlungen" in der Statusanzeige.
  // Das Skript kennt den sichtbaren Chartbereich nicht, daher Bars zurueck.
  invalidWindow = input.int(500, title: "Ungueltig-Zaehler: letzte N Bars", min: 10, max: 100000)
  // Schriftgroesse der Wellen-Labels (Ebene 2 wird automatisch groesser)
  labelSize = input.float(18.0, title: "Label-Groesse", min: 6.0, max: 40.0)
  // Farben
  colImpulse = input.color(color.rgb(41, 121, 255), title: "Farbe Impuls")
  colCorr = input.color(color.rgb(255, 152, 0), title: "Farbe Korrektur")
  colInvalid = input.color(color.rgb(120, 123, 134), title: "Farbe ungueltig")
  colBreak = input.color(color.rgb(242, 54, 69), title: "Farbe Bruchpunkt (X)")
  colCombo = input.color(color.rgb(171, 71, 188), title: "Farbe W-X-Y")
)

data chart = subscribe(data.ohlcv)

type WavePayload {
  level: int
  wave: string
  price: float
  direction: string
}

type PatternPayload {
  level: int
  pattern: string
  price: float
  direction: string
}

type InvalidPayload {
  level: int
  rule: string
  price: float
}

alert (
  waveDone = alert(title: "EW: Welle bestaetigt", payload: WavePayload, onClose: true)
  countInvalid = alert(title: "EW: Zaehlung ungueltig", payload: InvalidPayload, onClose: true)
  patternDone = alert(title: "EW: Korrektur erkannt (A-B-C / W-X-Y)", payload: PatternPayload, onClose: true)
)

// Zeichenobjekte beider Ebenen; Schluessel beginnen mit der Ebene.
state (
  labels = entities.labelPool(max: 500)
  lines = entities.linePool(max: 500)
  marks = entities.markerPool(max: 200)
  provLine = entities.linePool(max: 2)    // vorlaeufiger Schenkel je Ebene
  provLabel = entities.labelPool(max: 2)
  hud = entities.labelPool(max: 8, anchor: anchor.topRight)
)

fn waveColor(n: int) -> color {
  return n <= 5 ? colImpulse : colCorr
}

// Punkte fuer einen Wert in [lo, hi]; ausserhalb linear bis 0 bei `tol` Abstand.
fn bandScore(v: float, lo: float, hi: float, tol: float, pts: float) -> float {
  if v >= lo && v <= hi {
    return pts
  }
  let dist = v < lo ? lo - v : v - hi
  return math.max(0.0, pts * (1.0 - dist / tol))
}
