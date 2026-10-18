
// ############################################################
//  EBENE @L@
// ############################################################

state (
  // --- ZigZag ---
  zzDir@S@: int = 0           // 0 = Start, 1 = Schenkel steigt, -1 = Schenkel faellt
  extP@S@: float = 0.0        // laufendes Extrem des offenen Schenkels
  extT@S@: time? = null
  extI@S@: int = 0
  // Gegen-Extrem seit dem Extrem (z. B. tiefstes Tief seit dem Hoch eines
  // steigenden Schenkels) und dessen Gegen-Extrem. Damit beginnt ein neuer
  // Schenkel an seinem echten Extrem, auch wenn die Bestaetigung wegen der
  // veraenderlichen ATR erst einige Bars spaeter kommt.
  hasOpp@S@: bool = false
  oppP@S@: float = 0.0
  oppT@S@: time? = null
  oppI@S@: int = 0
  hasOpp2@S@: bool = false
  opp2P@S@: float = 0.0
  opp2T@S@: time? = null
  opp2I@S@: int = 0
  initHiP@S@: float = 0.0     // Startphase: hoechstes Hoch / tiefstes Tief
  initHiT@S@: time? = null
  initHiI@S@: int = 0
  initLoP@S@: float = 0.0
  initLoT@S@: time? = null
  initLoI@S@: int = 0
  hasLast@S@: bool = false    // letzter bestaetigter Pivot
  lastP@S@: float = 0.0
  lastT@S@: time? = null
  lastI@S@: int = 0
  lastIsHigh@S@: bool = false
  pivSeq@S@: int = 0          // laufende Nummer der bestaetigten Pivots
  lastSeq@S@: int = 0

  // --- Laufende Zaehlung: Punkte P0..P8 (0, 1..5, a, b, c) ---
  active@S@: bool = false
  bull@S@: bool = true
  countId@S@: int = 0
  cntP@S@ = float[](9)
  cntY@S@ = float[](9)        // Label-Position (Preis + Abstand), festgeschrieben
  cntT@S@ = time[](9)
  cntI@S@ = int[](9)
  cntS@S@ = int[](9)          // Pivot-Nummern der Punkte

  // --- Score (Richtwerte, nie Ausschluss) ---
  scorePts@S@: float = 0.0
  scoreMax@S@: float = 0.0
  r2@S@: float = 0.0
  d2@S@: int = 0

  // --- Letzte eigenstaendige Korrektur (Kandidat fuer W einer W-X-Y) ---
  pcActive@S@: bool = false
  pcBull@S@: bool = true      // true = Korrektur aufwaerts
  pcStartP@S@: float = 0.0
  pcEndSeq@S@: int = 0
  pcEndP@S@: float = 0.0
  pcEndT@S@: time? = null
  pcEndY@S@: float = 0.0
  pcId@S@: int = 0
  lastPattern@S@: string = "-"

  // --- Statistik ---
  invalidBars@S@ = rolling<int>(1000)
)

fn waveName@S@(n: int) -> string {
  return match n {
    1 => "@N1@"
    2 => "@N2@"
    3 => "@N3@"
    4 => "@N4@"
    5 => "@N5@"
    6 => "@Na@"
    7 => "@Nb@"
    _ => "@Nc@"
  }
}

fn startCount@S@(p: float, t: time, i: int, isHigh: bool, seq: int) {
  countId@S@ += 1
  active@S@ = true
  bull@S@ = !isHigh
  cntP@S@.clear()
  cntY@S@.clear()
  cntT@S@.clear()
  cntI@S@.clear()
  cntS@S@.clear()
  cntS@S@.push(seq)
  cntP@S@.push(p)
  cntY@S@.push(p)
  cntT@S@.push(t)
  cntI@S@.push(i)
  scorePts@S@ = 0.0
  scoreMax@S@ = 0.0
}

fn invalidate@S@(t: time, price: float, rule: string) {
  let kEnd = cntP@S@.len
  for n in 1..kEnd {
    let p = cntP@S@[n]
    let y = cntY@S@[n]
    let tt = cntT@S@[n]
    let p0 = cntP@S@[n - 1]
    let t0 = cntT@S@[n - 1]
    if p != null && y != null && tt != null && p0 != null && t0 != null {
      if showInvalid {
        labels.get("L", @L@, countId@S@, n).set(tt, y, waveName@S@(n), color: colInvalid, size: @SIZE@)
        lines.get("W", @L@, countId@S@, n).set(t0, p0, tt, p, width: @W1@, color: colInvalid)
      }
    }
  }
  if !showInvalid {
    labels.clear("L", @L@, countId@S@)
    lines.clear("W", @L@, countId@S@)
  }
  if showInvalid {
    marks.get("X", @L@, countId@S@).set(t, price, shape: shape.cross, color: colBreak, size: @XSIZE@)
  }
  invalidBars@S@.push(chart.index)
  countInvalid.trigger(InvalidPayload { level: @L@, rule: rule, price: price })
  log.info(str.format("Ebene @L@, Zaehlung #{0} ungueltig: {1} @ {2:.2}", countId@S@, rule, price))
  active@S@ = false
}

// Gebrochener Impuls mit Ueberlappung in Welle 4: P0..P3 als Zigzag A-B-C
// beschriften (B nicht ueber den Start von A hinaus, C ueber das Ende von A).
// Folgt direkt nach einem A-B-C ein X-Schenkel und ein zweites A-B-C in
// dieselbe Richtung, werden W, X und Y zusaetzlich gesetzt.
fn markCorrection@S@(t: time) {
  if !showCorrections || cntP@S@.len < 4 {
    return
  }
  let bull = bull@S@
  let s = bull ? 1.0 : -1.0
  let p0 = cntP@S@[0] ?? 0.0
  let p1 = cntP@S@[1] ?? 0.0
  let p2 = cntP@S@[2] ?? 0.0
  let p3 = cntP@S@[3] ?? 0.0
  if s * (p2 - p0) < 0.0 || s * (p3 - p1) <= 0.0 {
    return
  }
  for n in 1..4 {
    let p = cntP@S@[n]
    let y = cntY@S@[n]
    let tt = cntT@S@[n]
    let pp = cntP@S@[n - 1]
    let t0 = cntT@S@[n - 1]
    if p != null && y != null && tt != null && pp != null && t0 != null {
      let yc = p + (y - p) * 2.2
      let name = n == 1 ? "@NA@" : n == 2 ? "@NB@" : "@NC@"
      labels.get("C", @L@, countId@S@, n).set(tt, yc, name, color: colCorr, size: @SIZE@)
      lines.get("CW", @L@, countId@S@, n).set(t0, pp, tt, p, width: @W2@, color: colCorr, zIndex: 1)
    }
  }
  let dirTxt = bull ? "aufwaerts" : "abwaerts"
  let seq0 = cntS@S@[0] ?? 0
  let t3 = cntT@S@[3]
  let y3 = cntY@S@[3]
  let t0c = cntT@S@[0]
  let isCombo = pcActive@S@ && pcBull@S@ == bull && seq0 == pcEndSeq@S@ + 1 && s * (p0 - pcStartP@S@) > 0.0
  if isCombo {
    let wt = pcEndT@S@
    if wt != null && t3 != null && y3 != null && t0c != null {
      // X liegt auf P0 der zweiten Korrektur; Label auf der Gegenseite
      let off = math.abs(pcEndY@S@ - pcEndP@S@)
      let yx = bull ? p0 - off * 2.2 : p0 + off * 2.2
      labels.get("WXY", @L@, pcId@S@, 1).set(wt, pcEndP@S@ + (pcEndY@S@ - pcEndP@S@) * 3.6, "@NW@", color: colCombo, size: @SIZE@ + 2.0)
      labels.get("WXY", @L@, pcId@S@, 2).set(t0c, yx, "@NX@", color: colCombo, size: @SIZE@ + 2.0)
      labels.get("WXY", @L@, pcId@S@, 3).set(t3, p3 + (y3 - p3) * 3.6, "@NY@", color: colCombo, size: @SIZE@ + 2.0)
      lastPattern@S@ = str.concat("W-X-Y ", dirTxt)
      patternDone.trigger(PatternPayload { level: @L@, pattern: "W-X-Y", price: p3, direction: dirTxt })
    }
    pcActive@S@ = false
    return
  }
  pcActive@S@ = true
  pcBull@S@ = bull
  pcStartP@S@ = p0
  pcEndSeq@S@ = cntS@S@[3] ?? 0
  pcEndP@S@ = p3
  pcEndT@S@ = t3
  pcEndY@S@ = y3 ?? p3
  pcId@S@ = countId@S@
  lastPattern@S@ = str.concat("A-B-C ", dirTxt)
  patternDone.trigger(PatternPayload { level: @L@, pattern: "A-B-C", price: p3, direction: dirTxt })
}

// Neuer bestaetigter Pivot: als naechste Welle der laufenden Zaehlung pruefen.
fn onPivot@S@(p: float, t: time, i: int, isHigh: bool, atr: float, seq: int) {
  if !active@S@ {
    startCount@S@(p, t, i, isHigh, seq)
    return
  }
  let s = bull@S@ ? 1.0 : -1.0
  let n = cntP@S@.len
  let p0 = cntP@S@[0] ?? p
  let p1 = cntP@S@[1] ?? p
  let p2 = cntP@S@[2] ?? p
  let p3 = cntP@S@[3] ?? p
  let p4 = cntP@S@[4] ?? p
  let i1 = cntI@S@[1] ?? i
  let i3 = cntI@S@[3] ?? i

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
    invalidate@S@(t, p, broken)
    if n == 4 {
      markCorrection@S@(t)
    }
    startCount@S@(p, t, i, isHigh, seq)
    return
  }

  // --- Label festschreiben ---
  let y = isHigh ? p + atr * @OFF@ : p - atr * @OFF@
  cntP@S@.push(p)
  cntY@S@.push(y)
  cntT@S@.push(t)
  cntI@S@.push(i)
  cntS@S@.push(seq)
  let prevP = cntP@S@[n - 1] ?? p
  let prevT = cntT@S@[n - 1] ?? t
  labels.get("L", @L@, countId@S@, n).set(t, y, waveName@S@(n), color: waveColor(n), size: @SIZE@)
  lines.get("W", @L@, countId@S@, n).set(prevT, prevP, t, p, width: @W2@, color: waveColor(n))
  waveDone.trigger(WavePayload { level: @L@, wave: waveName@S@(n), price: p, direction: bull@S@ ? "bull" : "bear" })

  // --- Score (nur Richtwerte) ---
  if n == 2 {
    let w1 = math.abs(p1 - p0)
    r2@S@ = math.safeDiv(math.abs(p - p1), w1, 0.0) ?? 0.0
    d2@S@ = i - i1
    scorePts@S@ += bandScore(r2@S@, 0.5, 0.786, 0.236, 25.0)
    scoreMax@S@ += 25.0
  }
  if n == 3 {
    let ext = math.safeDiv(math.abs(p - p2), math.abs(p1 - p0), 0.0) ?? 0.0
    scorePts@S@ += ext >= 1.618 ? 25.0 : math.max(0.0, 25.0 * (ext - 1.0) / 0.618)
    scoreMax@S@ += 25.0
  }
  if n == 4 {
    let r4 = math.safeDiv(math.abs(p - p3), math.abs(p3 - p2), 0.0) ?? 0.0
    scorePts@S@ += bandScore(r4, 0.236, 0.382, 0.236, 25.0)
    scoreMax@S@ += 25.0
    // Alternation: Tiefe (12.5) und Dauer (12.5)
    let d4 = i - i3
    let depthDiff = math.abs(r2@S@ - r4)
    scorePts@S@ += math.min(12.5, 12.5 * depthDiff / 0.2)
    let dMin = math.max(1, math.min(d2@S@, d4))
    let dMax = math.max(d2@S@, d4)
    let ratio = float(dMax) / float(dMin)
    scorePts@S@ += math.min(12.5, math.max(0.0, 12.5 * (ratio - 1.0) / 0.5))
    scoreMax@S@ += 25.0
  }

  // --- Nach c: Zaehlung abgeschlossen, neue Suche ab c ---
  if n == 8 {
    active@S@ = false
    startCount@S@(p, t, i, isHigh, seq)
  }
}

// Harte Regeln, die schon waehrend eines laufenden Schenkels brechen koennen.
fn checkRunning@S@(t: time, lo: float, hi: float) {
  if !active@S@ {
    return
  }
  let k = cntP@S@.len - 1
  let s = bull@S@ ? 1.0 : -1.0
  let adverse = bull@S@ ? lo : hi
  let favor = bull@S@ ? hi : lo
  let p0 = cntP@S@[0] ?? 0.0
  let p1 = cntP@S@[1] ?? 0.0
  let p2 = cntP@S@[2] ?? 0.0
  let p3 = cntP@S@[3] ?? 0.0
  let p4 = cntP@S@[4] ?? 0.0
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
    invalidate@S@(t, at, broken)
    if k == 3 {
      markCorrection@S@(t)
    }
    if hasLast@S@ {
      let lt = lastT@S@
      if lt != null {
        startCount@S@(lastP@S@, lt, lastI@S@, lastIsHigh@S@, lastSeq@S@)
      }
    }
  }
}

fn invalidationLevel@S@() -> float? {
  if !active@S@ {
    return null
  }
  let k = cntP@S@.len - 1
  if k <= 1 {
    return cntP@S@[0]
  }
  if k <= 3 {
    return cntP@S@[1]
  }
  if k == 4 {
    return cntP@S@[4]
  }
  return null
}

// Ein bestaetigter Bar fuer diese Ebene: ZigZag, Zaehlung, vorlaeufiger Schenkel.
fn step@S@(t: time, h: float, l: float, i: int, atrV: float) {
  let thr = atrV * @MULT@

  // ================= ZigZag =================
  let newPivot = false
  let pvP = 0.0
  let pvT = t
  let pvI = 0
  let pvHigh = false
  if zzDir@S@ == 0 {
    if initHiT@S@ == null || h > initHiP@S@ {
      initHiP@S@ = h
      initHiT@S@ = t
      initHiI@S@ = i
    }
    if initLoT@S@ == null || l < initLoP@S@ {
      initLoP@S@ = l
      initLoT@S@ = t
      initLoI@S@ = i
    }
    let ht = initHiT@S@
    let lt = initLoT@S@
    if ht != null && lt != null {
      if initHiP@S@ - initLoP@S@ >= thr {
        if initLoI@S@ < initHiI@S@ {
          // erst Tief, dann Hoch: Tief bestaetigt, Schenkel steigt
          newPivot = true
          pvP = initLoP@S@
          pvT = lt
          pvI = initLoI@S@
          pvHigh = false
          zzDir@S@ = 1
          extP@S@ = initHiP@S@
          extT@S@ = ht
          extI@S@ = initHiI@S@
        } else {
          newPivot = true
          pvP = initHiP@S@
          pvT = ht
          pvI = initHiI@S@
          pvHigh = true
          zzDir@S@ = -1
          extP@S@ = initLoP@S@
          extT@S@ = lt
          extI@S@ = initLoI@S@
        }
      }
    }
  } else {
    let up = zzDir@S@ == 1
    let et = extT@S@
    if et != null {
      let newExt = up ? (h > extP@S@) : (l < extP@S@)
      if newExt {
        extP@S@ = up ? h : l
        extT@S@ = t
        extI@S@ = i
        hasOpp@S@ = false
        hasOpp2@S@ = false
      } else {
        let v = up ? l : h
        let better = !hasOpp@S@ || (up ? (v < oppP@S@) : (v > oppP@S@))
        if better {
          oppP@S@ = v
          oppT@S@ = t
          oppI@S@ = i
          hasOpp@S@ = true
          hasOpp2@S@ = false
        } else {
          let w = up ? h : l
          if !hasOpp2@S@ || (up ? (w > opp2P@S@) : (w < opp2P@S@)) {
            opp2P@S@ = w
            opp2T@S@ = t
            opp2I@S@ = i
            hasOpp2@S@ = true
          }
        }
      }
      // Umkehr bestaetigt, sobald die Gegenbewegung die Schwelle erreicht
      let ot = oppT@S@
      let rev = up ? extP@S@ - oppP@S@ : oppP@S@ - extP@S@
      if !newExt && hasOpp@S@ && ot != null && rev >= thr {
        newPivot = true
        pvP = extP@S@
        pvT = et
        pvI = extI@S@
        pvHigh = up
        zzDir@S@ = up ? -1 : 1
        extP@S@ = oppP@S@
        extT@S@ = ot
        extI@S@ = oppI@S@
        hasOpp@S@ = hasOpp2@S@
        oppP@S@ = opp2P@S@
        oppT@S@ = opp2T@S@
        oppI@S@ = opp2I@S@
        hasOpp2@S@ = false
      }
    }
  }

  // ================= Zaehlung =================
  if newPivot {
    hasLast@S@ = true
    lastP@S@ = pvP
    lastT@S@ = pvT
    lastI@S@ = pvI
    lastIsHigh@S@ = pvHigh
    pivSeq@S@ += 1
    lastSeq@S@ = pivSeq@S@
    onPivot@S@(pvP, pvT, pvI, pvHigh, atrV, pivSeq@S@)
  }
  checkRunning@S@(t, l, h)

  // ================= Vorlaeufiger Schenkel =================
  let lt = lastT@S@
  let et = extT@S@
  if hasLast@S@ && lt != null && et != null {
    let nextN = active@S@ ? cntP@S@.len : 0
    let txt = nextN >= 1 && nextN <= 8 ? str.concat("(", waveName@S@(nextN), ")") : "(?)"
    let col = nextN >= 1 && nextN <= 8 ? waveColor(nextN) : colInvalid
    let yOff = zzDir@S@ == 1 ? extP@S@ + atrV * @OFF@ : extP@S@ - atrV * @OFF@
    provLine.get(@L@).set(lt, lastP@S@, et, extP@S@, width: @W1@, color: col, style: linestyle.dashed)
    provLabel.get(@L@).set(et, yOff, txt, color: col, size: @SIZE@)
  }
}

// Drei Zeilen Statusanzeige fuer diese Ebene ab Zeile `row`, Hoehe `y0` in px.
fn status@S@(i: int, row: int, y0: float) {
  let invCount = 0
  for b in invalidBars@S@ {
    if b > i - invalidWindow {
      invCount += 1
    }
  }
  let k = active@S@ ? cntP@S@.len - 1 : 0
  let dirTxt = active@S@ ? (bull@S@ ? "Bull" : "Bear") : "-"
  let waveTxt = !active@S@ ? "Suche" :
    k == 0 ? str.concat(waveName@S@(1), " laeuft") :
    k >= 8 ? str.concat(waveName@S@(8), " fertig") :
    str.concat(waveName@S@(k), " fertig, ", waveName@S@(k + 1), " laeuft")
  let lvl = invalidationLevel@S@()
  let lvlTxt = lvl != null ? str.format("{0:.2}", lvl) : "-"
  let scoreTxt = scoreMax@S@ > 0.0 ?
    str.format("{0:.0}/100 ({1:.0} von 4)", scorePts@S@ / scoreMax@S@ * 100.0, scoreMax@S@ / 25.0) :
    "-"
  hud.get(row).set(12.0, y0, str.concat("@LNAME@ · ", dirTxt, " · Welle ", waveTxt), size: 12.0, font: font.mono)
  hud.get(row + 1).set(12.0, y0 + 16.0, str.concat("Invalidierung ", lvlTxt, " · Score ", scoreTxt), size: 12.0, font: font.mono)
  hud.get(row + 2).set(12.0, y0 + 32.0, str.format("Ungueltig {0} (letzte {1} Bars) · Korrektur {2}", invCount, invalidWindow, lastPattern@S@), size: 12.0, font: font.mono)
}
