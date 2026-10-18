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

// 14 Tage Historie laden, damit auch grosse Wellen vor dem sichtbaren
// Bereich gezaehlt werden (der Chart laedt sonst oft nur wenige Tage).
data chart = subscribe(data.ohlcv, history: 14D)

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

// ############################################################
//  EBENE 1
// ############################################################

state (
  // --- ZigZag ---
  zzDir1: int = 0           // 0 = Start, 1 = Schenkel steigt, -1 = Schenkel faellt
  extP1: float = 0.0        // laufendes Extrem des offenen Schenkels
  extT1: time? = null
  extI1: int = 0
  // Gegen-Extrem seit dem Extrem (z. B. tiefstes Tief seit dem Hoch eines
  // steigenden Schenkels) und dessen Gegen-Extrem. Damit beginnt ein neuer
  // Schenkel an seinem echten Extrem, auch wenn die Bestaetigung wegen der
  // veraenderlichen ATR erst einige Bars spaeter kommt.
  hasOpp1: bool = false
  oppP1: float = 0.0
  oppT1: time? = null
  oppI1: int = 0
  hasOpp21: bool = false
  opp2P1: float = 0.0
  opp2T1: time? = null
  opp2I1: int = 0
  initHiP1: float = 0.0     // Startphase: hoechstes Hoch / tiefstes Tief
  initHiT1: time? = null
  initHiI1: int = 0
  initLoP1: float = 0.0
  initLoT1: time? = null
  initLoI1: int = 0
  hasLast1: bool = false    // letzter bestaetigter Pivot
  lastP1: float = 0.0
  lastT1: time? = null
  lastI1: int = 0
  lastIsHigh1: bool = false
  pivSeq1: int = 0          // laufende Nummer der bestaetigten Pivots
  lastSeq1: int = 0

  // --- Laufende Zaehlung: Punkte P0..P8 (0, 1..5, a, b, c) ---
  active1: bool = false
  bull1: bool = true
  countId1: int = 0
  cntP1 = float[](9)
  cntY1 = float[](9)        // Label-Position (Preis + Abstand), festgeschrieben
  cntT1 = time[](9)
  cntI1 = int[](9)
  cntS1 = int[](9)          // Pivot-Nummern der Punkte

  // --- Score (Richtwerte, nie Ausschluss) ---
  scorePts1: float = 0.0
  scoreMax1: float = 0.0
  r21: float = 0.0
  d21: int = 0

  // --- Letzte eigenstaendige Korrektur (Kandidat fuer W einer W-X-Y) ---
  pcActive1: bool = false
  pcBull1: bool = true      // true = Korrektur aufwaerts
  pcStartP1: float = 0.0
  pcEndSeq1: int = 0
  pcEndP1: float = 0.0
  pcEndT1: time? = null
  pcEndY1: float = 0.0
  pcId1: int = 0
  lastPattern1: string = "-"

  // --- Statistik ---
  invalidBars1 = rolling<int>(1000)
)

fn waveName1(n: int) -> string {
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

fn startCount1(p: float, t: time, i: int, isHigh: bool, seq: int) {
  countId1 += 1
  active1 = true
  bull1 = !isHigh
  cntP1.clear()
  cntY1.clear()
  cntT1.clear()
  cntI1.clear()
  cntS1.clear()
  cntS1.push(seq)
  cntP1.push(p)
  cntY1.push(p)
  cntT1.push(t)
  cntI1.push(i)
  scorePts1 = 0.0
  scoreMax1 = 0.0
}

fn invalidate1(t: time, price: float, rule: string) {
  let kEnd = cntP1.len
  for n in 1..kEnd {
    let p = cntP1[n]
    let y = cntY1[n]
    let tt = cntT1[n]
    let p0 = cntP1[n - 1]
    let t0 = cntT1[n - 1]
    if p != null && y != null && tt != null && p0 != null && t0 != null {
      if showInvalid {
        labels.get("L", 1, countId1, n).set(tt, y, waveName1(n), color: colInvalid, size: labelSize)
        lines.get("W", 1, countId1, n).set(t0, p0, tt, p, width: 1.0, color: colInvalid)
      }
    }
  }
  if !showInvalid {
    labels.clear("L", 1, countId1)
    lines.clear("W", 1, countId1)
  }
  if showInvalid {
    marks.get("X", 1, countId1).set(t, price, shape: shape.cross, color: colBreak, size: 12.0)
  }
  invalidBars1.push(chart.index)
  countInvalid.trigger(InvalidPayload { level: 1, rule: rule, price: price })
  log.info(str.format("Ebene 1, Zaehlung #{0} ungueltig: {1} @ {2:.2}", countId1, rule, price))
  active1 = false
}

// Gebrochener Impuls mit Ueberlappung in Welle 4: P0..P3 als Zigzag A-B-C
// beschriften (B nicht ueber den Start von A hinaus, C ueber das Ende von A).
// Folgt direkt nach einem A-B-C ein X-Schenkel und ein zweites A-B-C in
// dieselbe Richtung, werden W, X und Y zusaetzlich gesetzt.
fn markCorrection1(t: time) {
  if !showCorrections || cntP1.len < 4 {
    return
  }
  let bull = bull1
  let s = bull ? 1.0 : -1.0
  let p0 = cntP1[0] ?? 0.0
  let p1 = cntP1[1] ?? 0.0
  let p2 = cntP1[2] ?? 0.0
  let p3 = cntP1[3] ?? 0.0
  if s * (p2 - p0) < 0.0 || s * (p3 - p1) <= 0.0 {
    return
  }
  for n in 1..4 {
    let p = cntP1[n]
    let y = cntY1[n]
    let tt = cntT1[n]
    let pp = cntP1[n - 1]
    let t0 = cntT1[n - 1]
    if p != null && y != null && tt != null && pp != null && t0 != null {
      let yc = p + (y - p) * 2.2
      let name = n == 1 ? "A" : n == 2 ? "B" : "C"
      labels.get("C", 1, countId1, n).set(tt, yc, name, color: colCorr, size: labelSize)
      lines.get("CW", 1, countId1, n).set(t0, pp, tt, p, width: 1.5, color: colCorr, zIndex: 1)
    }
  }
  let dirTxt = bull ? "aufwaerts" : "abwaerts"
  let seq0 = cntS1[0] ?? 0
  let t3 = cntT1[3]
  let y3 = cntY1[3]
  let t0c = cntT1[0]
  let isCombo = pcActive1 && pcBull1 == bull && seq0 == pcEndSeq1 + 1 && s * (p0 - pcStartP1) > 0.0
  if isCombo {
    let wt = pcEndT1
    if wt != null && t3 != null && y3 != null && t0c != null {
      // X liegt auf P0 der zweiten Korrektur; Label auf der Gegenseite
      let off = math.abs(pcEndY1 - pcEndP1)
      let yx = bull ? p0 - off * 2.2 : p0 + off * 2.2
      labels.get("WXY", 1, pcId1, 1).set(wt, pcEndP1 + (pcEndY1 - pcEndP1) * 3.6, "W", color: colCombo, size: labelSize + 2.0)
      labels.get("WXY", 1, pcId1, 2).set(t0c, yx, "X", color: colCombo, size: labelSize + 2.0)
      labels.get("WXY", 1, pcId1, 3).set(t3, p3 + (y3 - p3) * 3.6, "Y", color: colCombo, size: labelSize + 2.0)
      lastPattern1 = str.concat("W-X-Y ", dirTxt)
      patternDone.trigger(PatternPayload { level: 1, pattern: "W-X-Y", price: p3, direction: dirTxt })
    }
    pcActive1 = false
    return
  }
  pcActive1 = true
  pcBull1 = bull
  pcStartP1 = p0
  pcEndSeq1 = cntS1[3] ?? 0
  pcEndP1 = p3
  pcEndT1 = t3
  pcEndY1 = y3 ?? p3
  pcId1 = countId1
  lastPattern1 = str.concat("A-B-C ", dirTxt)
  patternDone.trigger(PatternPayload { level: 1, pattern: "A-B-C", price: p3, direction: dirTxt })
}

// Neuer bestaetigter Pivot: als naechste Welle der laufenden Zaehlung pruefen.
fn onPivot1(p: float, t: time, i: int, isHigh: bool, atr: float, seq: int) {
  if !active1 {
    startCount1(p, t, i, isHigh, seq)
    return
  }
  let s = bull1 ? 1.0 : -1.0
  let n = cntP1.len
  let p0 = cntP1[0] ?? p
  let p1 = cntP1[1] ?? p
  let p2 = cntP1[2] ?? p
  let p3 = cntP1[3] ?? p
  let p4 = cntP1[4] ?? p
  let i1 = cntI1[1] ?? i
  let i3 = cntI1[3] ?? i

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
    invalidate1(t, p, broken)
    if n == 4 {
      markCorrection1(t)
    }
    startCount1(p, t, i, isHigh, seq)
    return
  }

  // --- Label festschreiben ---
  let y = isHigh ? p + atr * 0.35 : p - atr * 0.35
  cntP1.push(p)
  cntY1.push(y)
  cntT1.push(t)
  cntI1.push(i)
  cntS1.push(seq)
  let prevP = cntP1[n - 1] ?? p
  let prevT = cntT1[n - 1] ?? t
  labels.get("L", 1, countId1, n).set(t, y, waveName1(n), color: waveColor(n), size: labelSize)
  lines.get("W", 1, countId1, n).set(prevT, prevP, t, p, width: 1.5, color: waveColor(n))
  waveDone.trigger(WavePayload { level: 1, wave: waveName1(n), price: p, direction: bull1 ? "bull" : "bear" })

  // --- Score (nur Richtwerte) ---
  if n == 2 {
    let w1 = math.abs(p1 - p0)
    r21 = math.safeDiv(math.abs(p - p1), w1, 0.0) ?? 0.0
    d21 = i - i1
    scorePts1 += bandScore(r21, 0.5, 0.786, 0.236, 25.0)
    scoreMax1 += 25.0
  }
  if n == 3 {
    let ext = math.safeDiv(math.abs(p - p2), math.abs(p1 - p0), 0.0) ?? 0.0
    scorePts1 += ext >= 1.618 ? 25.0 : math.max(0.0, 25.0 * (ext - 1.0) / 0.618)
    scoreMax1 += 25.0
  }
  if n == 4 {
    let r4 = math.safeDiv(math.abs(p - p3), math.abs(p3 - p2), 0.0) ?? 0.0
    scorePts1 += bandScore(r4, 0.236, 0.382, 0.236, 25.0)
    scoreMax1 += 25.0
    // Alternation: Tiefe (12.5) und Dauer (12.5)
    let d4 = i - i3
    let depthDiff = math.abs(r21 - r4)
    scorePts1 += math.min(12.5, 12.5 * depthDiff / 0.2)
    let dMin = math.max(1, math.min(d21, d4))
    let dMax = math.max(d21, d4)
    let ratio = float(dMax) / float(dMin)
    scorePts1 += math.min(12.5, math.max(0.0, 12.5 * (ratio - 1.0) / 0.5))
    scoreMax1 += 25.0
  }

  // --- Nach c: Zaehlung abgeschlossen, neue Suche ab c ---
  if n == 8 {
    active1 = false
    startCount1(p, t, i, isHigh, seq)
  }
}

// Harte Regeln, die schon waehrend eines laufenden Schenkels brechen koennen.
fn checkRunning1(t: time, lo: float, hi: float) {
  if !active1 {
    return
  }
  let k = cntP1.len - 1
  let s = bull1 ? 1.0 : -1.0
  let adverse = bull1 ? lo : hi
  let favor = bull1 ? hi : lo
  let p0 = cntP1[0] ?? 0.0
  let p1 = cntP1[1] ?? 0.0
  let p2 = cntP1[2] ?? 0.0
  let p3 = cntP1[3] ?? 0.0
  let p4 = cntP1[4] ?? 0.0
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
    invalidate1(t, at, broken)
    if k == 3 {
      markCorrection1(t)
    }
    if hasLast1 {
      let lt = lastT1
      if lt != null {
        startCount1(lastP1, lt, lastI1, lastIsHigh1, lastSeq1)
      }
    }
  }
}

fn invalidationLevel1() -> float? {
  if !active1 {
    return null
  }
  let k = cntP1.len - 1
  if k <= 1 {
    return cntP1[0]
  }
  if k <= 3 {
    return cntP1[1]
  }
  if k == 4 {
    return cntP1[4]
  }
  return null
}

// Ein bestaetigter Bar fuer diese Ebene: ZigZag, Zaehlung, vorlaeufiger Schenkel.
fn step1(t: time, h: float, l: float, i: int, atrV: float) {
  let thr = atrV * atrMult

  // ================= ZigZag =================
  let newPivot = false
  let pvP = 0.0
  let pvT = t
  let pvI = 0
  let pvHigh = false
  if zzDir1 == 0 {
    if initHiT1 == null || h > initHiP1 {
      initHiP1 = h
      initHiT1 = t
      initHiI1 = i
    }
    if initLoT1 == null || l < initLoP1 {
      initLoP1 = l
      initLoT1 = t
      initLoI1 = i
    }
    let ht = initHiT1
    let lt = initLoT1
    if ht != null && lt != null {
      if initHiP1 - initLoP1 >= thr {
        if initLoI1 < initHiI1 {
          // erst Tief, dann Hoch: Tief bestaetigt, Schenkel steigt
          newPivot = true
          pvP = initLoP1
          pvT = lt
          pvI = initLoI1
          pvHigh = false
          zzDir1 = 1
          extP1 = initHiP1
          extT1 = ht
          extI1 = initHiI1
        } else {
          newPivot = true
          pvP = initHiP1
          pvT = ht
          pvI = initHiI1
          pvHigh = true
          zzDir1 = -1
          extP1 = initLoP1
          extT1 = lt
          extI1 = initLoI1
        }
      }
    }
  } else {
    let up = zzDir1 == 1
    let et = extT1
    if et != null {
      let newExt = up ? (h > extP1) : (l < extP1)
      if newExt {
        extP1 = up ? h : l
        extT1 = t
        extI1 = i
        hasOpp1 = false
        hasOpp21 = false
      } else {
        let v = up ? l : h
        let better = !hasOpp1 || (up ? (v < oppP1) : (v > oppP1))
        if better {
          oppP1 = v
          oppT1 = t
          oppI1 = i
          hasOpp1 = true
          hasOpp21 = false
        } else {
          let w = up ? h : l
          if !hasOpp21 || (up ? (w > opp2P1) : (w < opp2P1)) {
            opp2P1 = w
            opp2T1 = t
            opp2I1 = i
            hasOpp21 = true
          }
        }
      }
      // Umkehr bestaetigt, sobald die Gegenbewegung die Schwelle erreicht
      let ot = oppT1
      let rev = up ? extP1 - oppP1 : oppP1 - extP1
      if !newExt && hasOpp1 && ot != null && rev >= thr {
        newPivot = true
        pvP = extP1
        pvT = et
        pvI = extI1
        pvHigh = up
        zzDir1 = up ? -1 : 1
        extP1 = oppP1
        extT1 = ot
        extI1 = oppI1
        hasOpp1 = hasOpp21
        oppP1 = opp2P1
        oppT1 = opp2T1
        oppI1 = opp2I1
        hasOpp21 = false
      }
    }
  }

  // ================= Zaehlung =================
  if newPivot {
    hasLast1 = true
    lastP1 = pvP
    lastT1 = pvT
    lastI1 = pvI
    lastIsHigh1 = pvHigh
    pivSeq1 += 1
    lastSeq1 = pivSeq1
    onPivot1(pvP, pvT, pvI, pvHigh, atrV, pivSeq1)
  }
  checkRunning1(t, l, h)

  // ================= Vorlaeufiger Schenkel =================
  let lt = lastT1
  let et = extT1
  if hasLast1 && lt != null && et != null {
    let nextN = active1 ? cntP1.len : 0
    let txt = nextN >= 1 && nextN <= 8 ? str.concat("(", waveName1(nextN), ")") : "(?)"
    let col = nextN >= 1 && nextN <= 8 ? waveColor(nextN) : colInvalid
    let yOff = zzDir1 == 1 ? extP1 + atrV * 0.35 : extP1 - atrV * 0.35
    provLine.get(1).set(lt, lastP1, et, extP1, width: 1.0, color: col, style: linestyle.dashed)
    provLabel.get(1).set(et, yOff, txt, color: col, size: labelSize)
  }
}

// Drei Zeilen Statusanzeige fuer diese Ebene ab Zeile `row`, Hoehe `y0` in px.
fn status1(i: int, row: int, y0: float) {
  let invCount = 0
  for b in invalidBars1 {
    if b > i - invalidWindow {
      invCount += 1
    }
  }
  let k = active1 ? cntP1.len - 1 : 0
  let dirTxt = active1 ? (bull1 ? "Bull" : "Bear") : "-"
  let waveTxt = !active1 ? "Suche" :
    k == 0 ? str.concat(waveName1(1), " laeuft") :
    k >= 8 ? str.concat(waveName1(8), " fertig") :
    str.concat(waveName1(k), " fertig, ", waveName1(k + 1), " laeuft")
  let lvl = invalidationLevel1()
  let lvlTxt = lvl != null ? str.format("{0:.2}", lvl) : "-"
  let scoreTxt = scoreMax1 > 0.0 ?
    str.format("{0:.0}/100 ({1:.0} von 4)", scorePts1 / scoreMax1 * 100.0, scoreMax1 / 25.0) :
    "-"
  hud.get(row).set(12.0, y0, str.concat("Ebene 1 · ", dirTxt, " · Welle ", waveTxt), size: 12.0, font: font.mono)
  hud.get(row + 1).set(12.0, y0 + 16.0, str.concat("Invalidierung ", lvlTxt, " · Score ", scoreTxt), size: 12.0, font: font.mono)
  hud.get(row + 2).set(12.0, y0 + 32.0, str.format("Ungueltig {0} (letzte {1} Bars) · Korrektur {2}", invCount, invalidWindow, lastPattern1), size: 12.0, font: font.mono)
}

// ############################################################
//  EBENE 2
// ############################################################

state (
  // --- ZigZag ---
  zzDir2: int = 0           // 0 = Start, 1 = Schenkel steigt, -1 = Schenkel faellt
  extP2: float = 0.0        // laufendes Extrem des offenen Schenkels
  extT2: time? = null
  extI2: int = 0
  // Gegen-Extrem seit dem Extrem (z. B. tiefstes Tief seit dem Hoch eines
  // steigenden Schenkels) und dessen Gegen-Extrem. Damit beginnt ein neuer
  // Schenkel an seinem echten Extrem, auch wenn die Bestaetigung wegen der
  // veraenderlichen ATR erst einige Bars spaeter kommt.
  hasOpp2: bool = false
  oppP2: float = 0.0
  oppT2: time? = null
  oppI2: int = 0
  hasOpp22: bool = false
  opp2P2: float = 0.0
  opp2T2: time? = null
  opp2I2: int = 0
  initHiP2: float = 0.0     // Startphase: hoechstes Hoch / tiefstes Tief
  initHiT2: time? = null
  initHiI2: int = 0
  initLoP2: float = 0.0
  initLoT2: time? = null
  initLoI2: int = 0
  hasLast2: bool = false    // letzter bestaetigter Pivot
  lastP2: float = 0.0
  lastT2: time? = null
  lastI2: int = 0
  lastIsHigh2: bool = false
  pivSeq2: int = 0          // laufende Nummer der bestaetigten Pivots
  lastSeq2: int = 0

  // --- Laufende Zaehlung: Punkte P0..P8 (0, 1..5, a, b, c) ---
  active2: bool = false
  bull2: bool = true
  countId2: int = 0
  cntP2 = float[](9)
  cntY2 = float[](9)        // Label-Position (Preis + Abstand), festgeschrieben
  cntT2 = time[](9)
  cntI2 = int[](9)
  cntS2 = int[](9)          // Pivot-Nummern der Punkte

  // --- Score (Richtwerte, nie Ausschluss) ---
  scorePts2: float = 0.0
  scoreMax2: float = 0.0
  r22: float = 0.0
  d22: int = 0

  // --- Letzte eigenstaendige Korrektur (Kandidat fuer W einer W-X-Y) ---
  pcActive2: bool = false
  pcBull2: bool = true      // true = Korrektur aufwaerts
  pcStartP2: float = 0.0
  pcEndSeq2: int = 0
  pcEndP2: float = 0.0
  pcEndT2: time? = null
  pcEndY2: float = 0.0
  pcId2: int = 0
  lastPattern2: string = "-"

  // --- Statistik ---
  invalidBars2 = rolling<int>(1000)
)

fn waveName2(n: int) -> string {
  return match n {
    1 => "①"
    2 => "②"
    3 => "③"
    4 => "④"
    5 => "⑤"
    6 => "ⓐ"
    7 => "ⓑ"
    _ => "ⓒ"
  }
}

fn startCount2(p: float, t: time, i: int, isHigh: bool, seq: int) {
  countId2 += 1
  active2 = true
  bull2 = !isHigh
  cntP2.clear()
  cntY2.clear()
  cntT2.clear()
  cntI2.clear()
  cntS2.clear()
  cntS2.push(seq)
  cntP2.push(p)
  cntY2.push(p)
  cntT2.push(t)
  cntI2.push(i)
  scorePts2 = 0.0
  scoreMax2 = 0.0
}

fn invalidate2(t: time, price: float, rule: string) {
  let kEnd = cntP2.len
  for n in 1..kEnd {
    let p = cntP2[n]
    let y = cntY2[n]
    let tt = cntT2[n]
    let p0 = cntP2[n - 1]
    let t0 = cntT2[n - 1]
    if p != null && y != null && tt != null && p0 != null && t0 != null {
      if showInvalid {
        labels.get("L", 2, countId2, n).set(tt, y, waveName2(n), color: colInvalid, size: (labelSize + 4.0))
        lines.get("W", 2, countId2, n).set(t0, p0, tt, p, width: 1.5, color: colInvalid)
      }
    }
  }
  if !showInvalid {
    labels.clear("L", 2, countId2)
    lines.clear("W", 2, countId2)
  }
  if showInvalid {
    marks.get("X", 2, countId2).set(t, price, shape: shape.cross, color: colBreak, size: 16.0)
  }
  invalidBars2.push(chart.index)
  countInvalid.trigger(InvalidPayload { level: 2, rule: rule, price: price })
  log.info(str.format("Ebene 2, Zaehlung #{0} ungueltig: {1} @ {2:.2}", countId2, rule, price))
  active2 = false
}

// Gebrochener Impuls mit Ueberlappung in Welle 4: P0..P3 als Zigzag A-B-C
// beschriften (B nicht ueber den Start von A hinaus, C ueber das Ende von A).
// Folgt direkt nach einem A-B-C ein X-Schenkel und ein zweites A-B-C in
// dieselbe Richtung, werden W, X und Y zusaetzlich gesetzt.
fn markCorrection2(t: time) {
  if !showCorrections || cntP2.len < 4 {
    return
  }
  let bull = bull2
  let s = bull ? 1.0 : -1.0
  let p0 = cntP2[0] ?? 0.0
  let p1 = cntP2[1] ?? 0.0
  let p2 = cntP2[2] ?? 0.0
  let p3 = cntP2[3] ?? 0.0
  if s * (p2 - p0) < 0.0 || s * (p3 - p1) <= 0.0 {
    return
  }
  for n in 1..4 {
    let p = cntP2[n]
    let y = cntY2[n]
    let tt = cntT2[n]
    let pp = cntP2[n - 1]
    let t0 = cntT2[n - 1]
    if p != null && y != null && tt != null && pp != null && t0 != null {
      let yc = p + (y - p) * 2.2
      let name = n == 1 ? "Ⓐ" : n == 2 ? "Ⓑ" : "Ⓒ"
      labels.get("C", 2, countId2, n).set(tt, yc, name, color: colCorr, size: (labelSize + 4.0))
      lines.get("CW", 2, countId2, n).set(t0, pp, tt, p, width: 2.5, color: colCorr, zIndex: 1)
    }
  }
  let dirTxt = bull ? "aufwaerts" : "abwaerts"
  let seq0 = cntS2[0] ?? 0
  let t3 = cntT2[3]
  let y3 = cntY2[3]
  let t0c = cntT2[0]
  let isCombo = pcActive2 && pcBull2 == bull && seq0 == pcEndSeq2 + 1 && s * (p0 - pcStartP2) > 0.0
  if isCombo {
    let wt = pcEndT2
    if wt != null && t3 != null && y3 != null && t0c != null {
      // X liegt auf P0 der zweiten Korrektur; Label auf der Gegenseite
      let off = math.abs(pcEndY2 - pcEndP2)
      let yx = bull ? p0 - off * 2.2 : p0 + off * 2.2
      labels.get("WXY", 2, pcId2, 1).set(wt, pcEndP2 + (pcEndY2 - pcEndP2) * 3.6, "Ⓦ", color: colCombo, size: (labelSize + 4.0) + 2.0)
      labels.get("WXY", 2, pcId2, 2).set(t0c, yx, "Ⓧ", color: colCombo, size: (labelSize + 4.0) + 2.0)
      labels.get("WXY", 2, pcId2, 3).set(t3, p3 + (y3 - p3) * 3.6, "Ⓨ", color: colCombo, size: (labelSize + 4.0) + 2.0)
      lastPattern2 = str.concat("W-X-Y ", dirTxt)
      patternDone.trigger(PatternPayload { level: 2, pattern: "W-X-Y", price: p3, direction: dirTxt })
    }
    pcActive2 = false
    return
  }
  pcActive2 = true
  pcBull2 = bull
  pcStartP2 = p0
  pcEndSeq2 = cntS2[3] ?? 0
  pcEndP2 = p3
  pcEndT2 = t3
  pcEndY2 = y3 ?? p3
  pcId2 = countId2
  lastPattern2 = str.concat("A-B-C ", dirTxt)
  patternDone.trigger(PatternPayload { level: 2, pattern: "A-B-C", price: p3, direction: dirTxt })
}

// Neuer bestaetigter Pivot: als naechste Welle der laufenden Zaehlung pruefen.
fn onPivot2(p: float, t: time, i: int, isHigh: bool, atr: float, seq: int) {
  if !active2 {
    startCount2(p, t, i, isHigh, seq)
    return
  }
  let s = bull2 ? 1.0 : -1.0
  let n = cntP2.len
  let p0 = cntP2[0] ?? p
  let p1 = cntP2[1] ?? p
  let p2 = cntP2[2] ?? p
  let p3 = cntP2[3] ?? p
  let p4 = cntP2[4] ?? p
  let i1 = cntI2[1] ?? i
  let i3 = cntI2[3] ?? i

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
    invalidate2(t, p, broken)
    if n == 4 {
      markCorrection2(t)
    }
    startCount2(p, t, i, isHigh, seq)
    return
  }

  // --- Label festschreiben ---
  let y = isHigh ? p + atr * 0.9 : p - atr * 0.9
  cntP2.push(p)
  cntY2.push(y)
  cntT2.push(t)
  cntI2.push(i)
  cntS2.push(seq)
  let prevP = cntP2[n - 1] ?? p
  let prevT = cntT2[n - 1] ?? t
  labels.get("L", 2, countId2, n).set(t, y, waveName2(n), color: waveColor(n), size: (labelSize + 4.0))
  lines.get("W", 2, countId2, n).set(prevT, prevP, t, p, width: 2.5, color: waveColor(n))
  waveDone.trigger(WavePayload { level: 2, wave: waveName2(n), price: p, direction: bull2 ? "bull" : "bear" })

  // --- Score (nur Richtwerte) ---
  if n == 2 {
    let w1 = math.abs(p1 - p0)
    r22 = math.safeDiv(math.abs(p - p1), w1, 0.0) ?? 0.0
    d22 = i - i1
    scorePts2 += bandScore(r22, 0.5, 0.786, 0.236, 25.0)
    scoreMax2 += 25.0
  }
  if n == 3 {
    let ext = math.safeDiv(math.abs(p - p2), math.abs(p1 - p0), 0.0) ?? 0.0
    scorePts2 += ext >= 1.618 ? 25.0 : math.max(0.0, 25.0 * (ext - 1.0) / 0.618)
    scoreMax2 += 25.0
  }
  if n == 4 {
    let r4 = math.safeDiv(math.abs(p - p3), math.abs(p3 - p2), 0.0) ?? 0.0
    scorePts2 += bandScore(r4, 0.236, 0.382, 0.236, 25.0)
    scoreMax2 += 25.0
    // Alternation: Tiefe (12.5) und Dauer (12.5)
    let d4 = i - i3
    let depthDiff = math.abs(r22 - r4)
    scorePts2 += math.min(12.5, 12.5 * depthDiff / 0.2)
    let dMin = math.max(1, math.min(d22, d4))
    let dMax = math.max(d22, d4)
    let ratio = float(dMax) / float(dMin)
    scorePts2 += math.min(12.5, math.max(0.0, 12.5 * (ratio - 1.0) / 0.5))
    scoreMax2 += 25.0
  }

  // --- Nach c: Zaehlung abgeschlossen, neue Suche ab c ---
  if n == 8 {
    active2 = false
    startCount2(p, t, i, isHigh, seq)
  }
}

// Harte Regeln, die schon waehrend eines laufenden Schenkels brechen koennen.
fn checkRunning2(t: time, lo: float, hi: float) {
  if !active2 {
    return
  }
  let k = cntP2.len - 1
  let s = bull2 ? 1.0 : -1.0
  let adverse = bull2 ? lo : hi
  let favor = bull2 ? hi : lo
  let p0 = cntP2[0] ?? 0.0
  let p1 = cntP2[1] ?? 0.0
  let p2 = cntP2[2] ?? 0.0
  let p3 = cntP2[3] ?? 0.0
  let p4 = cntP2[4] ?? 0.0
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
    invalidate2(t, at, broken)
    if k == 3 {
      markCorrection2(t)
    }
    if hasLast2 {
      let lt = lastT2
      if lt != null {
        startCount2(lastP2, lt, lastI2, lastIsHigh2, lastSeq2)
      }
    }
  }
}

fn invalidationLevel2() -> float? {
  if !active2 {
    return null
  }
  let k = cntP2.len - 1
  if k <= 1 {
    return cntP2[0]
  }
  if k <= 3 {
    return cntP2[1]
  }
  if k == 4 {
    return cntP2[4]
  }
  return null
}

// Ein bestaetigter Bar fuer diese Ebene: ZigZag, Zaehlung, vorlaeufiger Schenkel.
fn step2(t: time, h: float, l: float, i: int, atrV: float) {
  let thr = atrV * atrMult2

  // ================= ZigZag =================
  let newPivot = false
  let pvP = 0.0
  let pvT = t
  let pvI = 0
  let pvHigh = false
  if zzDir2 == 0 {
    if initHiT2 == null || h > initHiP2 {
      initHiP2 = h
      initHiT2 = t
      initHiI2 = i
    }
    if initLoT2 == null || l < initLoP2 {
      initLoP2 = l
      initLoT2 = t
      initLoI2 = i
    }
    let ht = initHiT2
    let lt = initLoT2
    if ht != null && lt != null {
      if initHiP2 - initLoP2 >= thr {
        if initLoI2 < initHiI2 {
          // erst Tief, dann Hoch: Tief bestaetigt, Schenkel steigt
          newPivot = true
          pvP = initLoP2
          pvT = lt
          pvI = initLoI2
          pvHigh = false
          zzDir2 = 1
          extP2 = initHiP2
          extT2 = ht
          extI2 = initHiI2
        } else {
          newPivot = true
          pvP = initHiP2
          pvT = ht
          pvI = initHiI2
          pvHigh = true
          zzDir2 = -1
          extP2 = initLoP2
          extT2 = lt
          extI2 = initLoI2
        }
      }
    }
  } else {
    let up = zzDir2 == 1
    let et = extT2
    if et != null {
      let newExt = up ? (h > extP2) : (l < extP2)
      if newExt {
        extP2 = up ? h : l
        extT2 = t
        extI2 = i
        hasOpp2 = false
        hasOpp22 = false
      } else {
        let v = up ? l : h
        let better = !hasOpp2 || (up ? (v < oppP2) : (v > oppP2))
        if better {
          oppP2 = v
          oppT2 = t
          oppI2 = i
          hasOpp2 = true
          hasOpp22 = false
        } else {
          let w = up ? h : l
          if !hasOpp22 || (up ? (w > opp2P2) : (w < opp2P2)) {
            opp2P2 = w
            opp2T2 = t
            opp2I2 = i
            hasOpp22 = true
          }
        }
      }
      // Umkehr bestaetigt, sobald die Gegenbewegung die Schwelle erreicht
      let ot = oppT2
      let rev = up ? extP2 - oppP2 : oppP2 - extP2
      if !newExt && hasOpp2 && ot != null && rev >= thr {
        newPivot = true
        pvP = extP2
        pvT = et
        pvI = extI2
        pvHigh = up
        zzDir2 = up ? -1 : 1
        extP2 = oppP2
        extT2 = ot
        extI2 = oppI2
        hasOpp2 = hasOpp22
        oppP2 = opp2P2
        oppT2 = opp2T2
        oppI2 = opp2I2
        hasOpp22 = false
      }
    }
  }

  // ================= Zaehlung =================
  if newPivot {
    hasLast2 = true
    lastP2 = pvP
    lastT2 = pvT
    lastI2 = pvI
    lastIsHigh2 = pvHigh
    pivSeq2 += 1
    lastSeq2 = pivSeq2
    onPivot2(pvP, pvT, pvI, pvHigh, atrV, pivSeq2)
  }
  checkRunning2(t, l, h)

  // ================= Vorlaeufiger Schenkel =================
  let lt = lastT2
  let et = extT2
  if hasLast2 && lt != null && et != null {
    let nextN = active2 ? cntP2.len : 0
    let txt = nextN >= 1 && nextN <= 8 ? str.concat("(", waveName2(nextN), ")") : "(?)"
    let col = nextN >= 1 && nextN <= 8 ? waveColor(nextN) : colInvalid
    let yOff = zzDir2 == 1 ? extP2 + atrV * 0.9 : extP2 - atrV * 0.9
    provLine.get(2).set(lt, lastP2, et, extP2, width: 1.5, color: col, style: linestyle.dashed)
    provLabel.get(2).set(et, yOff, txt, color: col, size: (labelSize + 4.0))
  }
}

// Drei Zeilen Statusanzeige fuer diese Ebene ab Zeile `row`, Hoehe `y0` in px.
fn status2(i: int, row: int, y0: float) {
  let invCount = 0
  for b in invalidBars2 {
    if b > i - invalidWindow {
      invCount += 1
    }
  }
  let k = active2 ? cntP2.len - 1 : 0
  let dirTxt = active2 ? (bull2 ? "Bull" : "Bear") : "-"
  let waveTxt = !active2 ? "Suche" :
    k == 0 ? str.concat(waveName2(1), " laeuft") :
    k >= 8 ? str.concat(waveName2(8), " fertig") :
    str.concat(waveName2(k), " fertig, ", waveName2(k + 1), " laeuft")
  let lvl = invalidationLevel2()
  let lvlTxt = lvl != null ? str.format("{0:.2}", lvl) : "-"
  let scoreTxt = scoreMax2 > 0.0 ?
    str.format("{0:.0}/100 ({1:.0} von 4)", scorePts2 / scoreMax2 * 100.0, scoreMax2 / 25.0) :
    "-"
  hud.get(row).set(12.0, y0, str.concat("Ebene 2 · ", dirTxt, " · Welle ", waveTxt), size: 12.0, font: font.mono)
  hud.get(row + 1).set(12.0, y0 + 16.0, str.concat("Invalidierung ", lvlTxt, " · Score ", scoreTxt), size: 12.0, font: font.mono)
  hud.get(row + 2).set(12.0, y0 + 32.0, str.format("Ungueltig {0} (letzte {1} Bars) · Korrektur {2}", invCount, invalidWindow, lastPattern2), size: 12.0, font: font.mono)
}

// ############################################################
//  Handler
// ############################################################

on chart.close {
  let atrV = chart.atr(atrLen)
  let h = chart.high
  let l = chart.low
  let t = chart.time
  let i = chart.index
  if atrV == null || h == null || l == null || t == null {
    return
  }
  step1(t, h, l, i, atrV)
  if showLevel2 {
    step2(t, h, l, i, atrV)
  }

  // Statusanzeige oben rechts, 40 px unter dem Rand (Chart-Buttons frei)
  status1(i, 0, 40.0)
  if showLevel2 {
    status2(i, 3, 96.0)
  }
}
