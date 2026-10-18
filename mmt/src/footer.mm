
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
