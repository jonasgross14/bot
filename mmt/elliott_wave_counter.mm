script "Elliott Wave Counter (ATR ZigZag)"

// ============================================================
//  Elliott-Wave-Zaehler, eine Wellenebene: Impuls 1-5, Korrektur a-b-c.
//  Basis: ZigZag mit ATR-Schwelle. Gezaehlt wird nur auf bestaetigten
//  Bars (on chart.close); ein einmal gesetztes Label auf einem
//  bestaetigten Pivot wird nie verschoben oder umbenannt.
// ============================================================

input (
  // ATR-Laenge fuer die ZigZag-Schwelle
  atrLen = input.int(14, title: "ATR-Laenge", min: 1, max: 200)
  // Schwelle = ATR * Multiplikator. Ein Pivot gilt als bestaetigt, sobald
  // die Gegenbewegung vom letzten Extrem diese Schwelle erreicht.
  atrMult = input.float(3.0, title: "ATR-Multiplikator", min: 0.5, max: 20.0)
  // Ungueltige (gebrochene) Zaehlungen grau sichtbar lassen
  showInvalid = input.bool(true, title: "Ungueltige Zaehlungen anzeigen")
  // Fenster fuer den Zaehler "ungueltige Zaehlungen" in der Statusanzeige.
  // Das Skript kennt den sichtbaren Chartbereich nicht, daher Bars zurueck.
  invalidWindow = input.int(500, title: "Ungueltig-Zaehler: letzte N Bars", min: 10, max: 100000)
  // Schriftgroesse der Wellen-Labels
  labelSize = input.float(13.0, title: "Label-Groesse", min: 6.0, max: 40.0)
  // Farben
  colImpulse = input.color(color.rgb(41, 121, 255), title: "Farbe Impuls")
  colCorr = input.color(color.rgb(255, 152, 0), title: "Farbe Korrektur")
  colInvalid = input.color(color.rgb(120, 123, 134), title: "Farbe ungueltig")
  colBreak = input.color(color.rgb(242, 54, 69), title: "Farbe Bruchpunkt (X)")
)

data chart = subscribe(data.ohlcv)

type WavePayload {
  wave: string
  price: float
  direction: string
}

type InvalidPayload {
  rule: string
  price: float
}

alert (
  waveDone = alert(title: "EW: Welle bestaetigt", payload: WavePayload, onClose: true)
  countInvalid = alert(title: "EW: Zaehlung ungueltig", payload: InvalidPayload, onClose: true)
)

state (
  // --- Zeichenobjekte ---
  labels = entities.labelPool(max: 500)
  lines = entities.linePool(max: 500)
  marks = entities.markerPool(max: 200)
  provLine = entities.linePool(max: 1)    // vorlaeufiger Schenkel, eigener Pool
  provLabel = entities.labelPool(max: 1)
  hud = entities.labelPool(max: 6, anchor: anchor.topRight)

  // --- ZigZag ---
  zzDir: int = 0              // 0 = Start, 1 = Schenkel steigt, -1 = Schenkel faellt
  extP: float = 0.0           // laufendes Extrem des offenen Schenkels
  extT: time? = null
  extI: int = 0
  initHiP: float = 0.0        // Startphase: hoechstes Hoch / tiefstes Tief
  initHiT: time? = null
  initHiI: int = 0
  initLoP: float = 0.0
  initLoT: time? = null
  initLoI: int = 0
  hasLast: bool = false       // letzter bestaetigter Pivot
  lastP: float = 0.0
  lastT: time? = null
  lastI: int = 0
  lastIsHigh: bool = false

  // --- Laufende Zaehlung: Punkte P0..P8 (0, 1..5, a, b, c) ---
  active: bool = false
  bull: bool = true
  countId: int = 0
  cntP = float[](9)
  cntY = float[](9)           // Label-Position (Preis + Abstand), festgeschrieben
  cntT = time[](9)
  cntI = int[](9)

  // --- Score (Richtwerte, nie Ausschluss) ---
  scorePts: float = 0.0
  scoreMax: float = 0.0
  r2: float = 0.0
  d2: int = 0

  // --- Statistik ---
  invalidBars = rolling<int>(1000)
)

fn waveName(n: int) -> string {
  return match n {
    1 => "1"
    2 => "2"
    3 => "3"
    4 => "4"
    5 => "5"
    6 => "a"
    7 => "b"
    _ => "c"
  }
}

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

fn startCount(p: float, t: time, i: int, isHigh: bool) {
  countId += 1
  active = true
  bull = !isHigh
  cntP.clear()
  cntY.clear()
  cntT.clear()
  cntI.clear()
  cntP.push(p)
  cntY.push(p)
  cntT.push(t)
  cntI.push(i)
  scorePts = 0.0
  scoreMax = 0.0
}

fn invalidate(t: time, price: float, rule: string) {
  let kEnd = cntP.len
  for n in 1..kEnd {
    let p = cntP[n]
    let y = cntY[n]
    let tt = cntT[n]
    let p0 = cntP[n - 1]
    let t0 = cntT[n - 1]
    if p != null && y != null && tt != null && p0 != null && t0 != null {
      if showInvalid {
        labels.get("L", countId, n).set(tt, y, waveName(n), color: colInvalid, size: labelSize)
        lines.get("W", countId, n).set(t0, p0, tt, p, width: 1.0, color: colInvalid)
      }
    }
  }
  if !showInvalid {
    labels.clear("L", countId)
    lines.clear("W", countId)
  }
  if showInvalid {
    marks.get("X", countId).set(t, price, shape: shape.cross, color: colBreak, size: 12.0)
  }
  invalidBars.push(chart.index)
  countInvalid.trigger(InvalidPayload { rule: rule, price: price })
  log.info(str.format("Zaehlung #{0} ungueltig: {1} @ {2:.2}", countId, rule, price))
  active = false
}

// Neuer bestaetigter Pivot: als naechste Welle der laufenden Zaehlung pruefen.
fn onPivot(p: float, t: time, i: int, isHigh: bool, atr: float) {
  if !active {
    startCount(p, t, i, isHigh)
    return
  }
  let s = bull ? 1.0 : -1.0
  let n = cntP.len
  let p0 = cntP[0] ?? p
  let p1 = cntP[1] ?? p
  let p2 = cntP[2] ?? p
  let p3 = cntP[3] ?? p
  let p4 = cntP[4] ?? p
  let i1 = cntI[1] ?? i
  let i3 = cntI[3] ?? i

  // --- Harte Regeln am bestaetigten Pivot ---
  let broken = ""
  if n == 2 && s * (p - p0) < 0.0 {
    broken = "Welle 2 unter Start von Welle 1"
  }
  if n == 4 && s * (p - p1) < 0.0 {
    broken = "Welle 4 ueberlappt Welle 1"
  }
  if n == 5 {
    let len1 = s * (p1 - p0)
    let len3 = s * (p3 - p2)
    let len5 = s * (p - p4)
    if len3 < len1 && len3 < len5 {
      broken = "Welle 3 ist die kuerzeste"
    }
    if s * (p - p3) <= 0.0 {
      broken = "Welle 5 erreicht Welle-3-Ende nicht (Truncation ausgeschlossen)"
    }
  }
  if broken != "" {
    invalidate(t, p, broken)
    startCount(p, t, i, isHigh)
    return
  }

  // --- Label festschreiben ---
  let y = isHigh ? p + atr * 0.35 : p - atr * 0.35
  cntP.push(p)
  cntY.push(y)
  cntT.push(t)
  cntI.push(i)
  let prevP = cntP[n - 1] ?? p
  let prevT = cntT[n - 1] ?? t
  labels.get("L", countId, n).set(t, y, waveName(n), color: waveColor(n), size: labelSize)
  lines.get("W", countId, n).set(prevT, prevP, t, p, width: 1.5, color: waveColor(n))
  waveDone.trigger(WavePayload { wave: waveName(n), price: p, direction: bull ? "bull" : "bear" })

  // --- Score (nur Richtwerte) ---
  if n == 2 {
    let w1 = math.abs(p1 - p0)
    r2 = math.safeDiv(math.abs(p - p1), w1, 0.0) ?? 0.0
    d2 = i - i1
    scorePts += bandScore(r2, 0.5, 0.786, 0.236, 25.0)
    scoreMax += 25.0
  }
  if n == 3 {
    let ext = math.safeDiv(math.abs(p - p2), math.abs(p1 - p0), 0.0) ?? 0.0
    scorePts += ext >= 1.618 ? 25.0 : math.max(0.0, 25.0 * (ext - 1.0) / 0.618)
    scoreMax += 25.0
  }
  if n == 4 {
    let r4 = math.safeDiv(math.abs(p - p3), math.abs(p3 - p2), 0.0) ?? 0.0
    scorePts += bandScore(r4, 0.236, 0.382, 0.236, 25.0)
    scoreMax += 25.0
    // Alternation: Tiefe (12.5) und Dauer (12.5)
    let d4 = i - i3
    let depthDiff = math.abs(r2 - r4)
    scorePts += math.min(12.5, 12.5 * depthDiff / 0.2)
    let dMin = math.max(1, math.min(d2, d4))
    let dMax = math.max(d2, d4)
    let ratio = float(dMax) / float(dMin)
    scorePts += math.min(12.5, math.max(0.0, 12.5 * (ratio - 1.0) / 0.5))
    scoreMax += 25.0
  }

  // --- Nach c: Zaehlung abgeschlossen, neue Suche ab c ---
  if n == 8 {
    active = false
    startCount(p, t, i, isHigh)
  }
}

// Harte Regeln, die schon waehrend eines laufenden Schenkels brechen koennen.
fn checkRunning(t: time, lo: float, hi: float) {
  if !active {
    return
  }
  let k = cntP.len - 1
  let s = bull ? 1.0 : -1.0
  let adverse = bull ? lo : hi
  let favor = bull ? hi : lo
  let p0 = cntP[0] ?? 0.0
  let p1 = cntP[1] ?? 0.0
  let p2 = cntP[2] ?? 0.0
  let p3 = cntP[3] ?? 0.0
  let p4 = cntP[4] ?? 0.0
  let broken = ""
  let at = adverse
  if k == 1 && s * (adverse - p0) < 0.0 {
    broken = "Welle 2 unter Start von Welle 1"
  }
  if k == 3 && s * (adverse - p1) < 0.0 {
    broken = "Welle 4 ueberlappt Welle 1"
  }
  if k == 4 {
    let len1 = s * (p1 - p0)
    let len3 = s * (p3 - p2)
    if len3 < len1 && s * (favor - p4) > len3 {
      broken = "Welle 3 ist die kuerzeste"
      at = favor
    }
  }
  if broken != "" {
    invalidate(t, at, broken)
    if hasLast {
      let lt = lastT
      if lt != null {
        startCount(lastP, lt, lastI, lastIsHigh)
      }
    }
  }
}

fn invalidationLevel() -> float? {
  if !active {
    return null
  }
  let k = cntP.len - 1
  if k <= 1 {
    return cntP[0]
  }
  if k <= 3 {
    return cntP[1]
  }
  if k == 4 {
    return cntP[4]
  }
  return null
}

on chart.close {
  let atrV = chart.atr(atrLen)
  let h = chart.high
  let l = chart.low
  let t = chart.time
  let i = chart.index
  if atrV == null || h == null || l == null || t == null {
    return
  }
  let thr = atrV * atrMult

  // ================= ZigZag =================
  let newPivot = false
  let pvP = 0.0
  let pvT = t
  let pvI = 0
  let pvHigh = false
  if zzDir == 0 {
    if initHiT == null || h > initHiP {
      initHiP = h
      initHiT = t
      initHiI = i
    }
    if initLoT == null || l < initLoP {
      initLoP = l
      initLoT = t
      initLoI = i
    }
    let ht = initHiT
    let lt = initLoT
    if ht != null && lt != null {
      if initHiP - initLoP >= thr {
        if initLoI < initHiI {
          // erst Tief, dann Hoch: Tief bestaetigt, Schenkel steigt
          newPivot = true
          pvP = initLoP
          pvT = lt
          pvI = initLoI
          pvHigh = false
          zzDir = 1
          extP = initHiP
          extT = ht
          extI = initHiI
        } else {
          newPivot = true
          pvP = initHiP
          pvT = ht
          pvI = initHiI
          pvHigh = true
          zzDir = -1
          extP = initLoP
          extT = lt
          extI = initLoI
        }
      }
    }
  } else {
    let et = extT
    if zzDir == 1 && et != null {
      if h > extP {
        extP = h
        extT = t
        extI = i
      } else {
        if extP - l >= thr {
          newPivot = true
          pvP = extP
          pvT = et
          pvI = extI
          pvHigh = true
          zzDir = -1
          extP = l
          extT = t
          extI = i
        }
      }
    }
    if zzDir == -1 && et != null && !newPivot {
      if l < extP {
        extP = l
        extT = t
        extI = i
      } else {
        if h - extP >= thr {
          newPivot = true
          pvP = extP
          pvT = et
          pvI = extI
          pvHigh = false
          zzDir = 1
          extP = h
          extT = t
          extI = i
        }
      }
    }
  }

  // ================= Zaehlung =================
  if newPivot {
    hasLast = true
    lastP = pvP
    lastT = pvT
    lastI = pvI
    lastIsHigh = pvHigh
    onPivot(pvP, pvT, pvI, pvHigh, atrV)
  }
  checkRunning(t, l, h)

  // ================= Vorlaeufiger Schenkel =================
  let lt = lastT
  let et = extT
  if hasLast && lt != null && et != null {
    let nextN = active ? cntP.len : 0
    let txt = nextN >= 1 && nextN <= 8 ? str.concat("(", waveName(nextN), ")") : "(?)"
    let col = nextN >= 1 && nextN <= 8 ? waveColor(nextN) : colInvalid
    let yOff = zzDir == 1 ? extP + atrV * 0.35 : extP - atrV * 0.35
    provLine.get(0).set(lt, lastP, et, extP, width: 1.0, color: col, style: linestyle.dashed)
    provLabel.get(0).set(et, yOff, txt, color: col, size: labelSize)
  }

  // ================= Statusanzeige =================
  let invCount = 0
  for b in invalidBars {
    if b > i - invalidWindow {
      invCount += 1
    }
  }
  let k = active ? cntP.len - 1 : 0
  let dirTxt = active ? (bull ? "Bull" : "Bear") : "-"
  let waveTxt = !active ? "Suche" :
    k == 0 ? "1 laeuft" :
    k >= 8 ? "c fertig" :
    str.concat(waveName(k), " fertig, ", waveName(k + 1), " laeuft")
  let lvl = invalidationLevel()
  let lvlTxt = lvl != null ? str.format("{0:.2}", lvl) : "-"
  let scoreTxt = scoreMax > 0.0 ?
    str.format("{0:.0} / 100 ({1:.0} von 4 Richtwerten)", scorePts / scoreMax * 100.0, scoreMax / 25.0) :
    "- (noch keine Richtwerte)"
  hud.get(0).set(12.0, 12.0, str.concat("Elliott Wave · ", dirTxt), size: 13.0, font: font.mono)
  hud.get(1).set(12.0, 30.0, str.concat("Welle: ", waveTxt), size: 12.0, font: font.mono)
  hud.get(2).set(12.0, 46.0, str.concat("Invalidierung: ", lvlTxt), size: 12.0, font: font.mono)
  hud.get(3).set(12.0, 62.0, str.concat("Score: ", scoreTxt), size: 12.0, font: font.mono)
  hud.get(4).set(12.0, 78.0, str.format("Ungueltige Zaehlungen: {0} (letzte {1} Bars)", invCount, invalidWindow), size: 12.0, font: font.mono)
}
