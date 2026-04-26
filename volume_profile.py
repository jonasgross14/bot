"""
Volume Profile.

Berechnet aus OHLCV-Daten ein horizontales Volumen-Profil:
- POC  (Point of Control)
- VAH / VAL  (Value Area High / Low) ueber prozentualen Volumenanteil
- High Volume Nodes (HVN) und Low Volume Nodes (LVN)

Volumen pro Kerze wird linear ueber ihren Range (high - low) verteilt.
Das ist der ueblichste, robuste Approximations-Ansatz, wenn keine
Tick-Daten vorliegen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np
import pandas as pd


@dataclass
class VolumeProfileResult:
    bins: np.ndarray                 # untere Kanten der Preis-Bins
    bin_size: float
    volume_per_bin: np.ndarray
    poc: float
    vah: float
    val: float
    hvn: List[float] = field(default_factory=list)
    lvn: List[float] = field(default_factory=list)
    total_volume: float = 0.0
    value_area_volume: float = 0.0

    def as_dict(self) -> dict:
        return {
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "hvn": list(self.hvn),
            "lvn": list(self.lvn),
            "total_volume": self.total_volume,
            "value_area_volume": self.value_area_volume,
            "bin_size": self.bin_size,
        }


class VolumeProfile:
    """Volume-Profile-Rechner."""

    def __init__(
        self,
        num_bins: int = 80,
        value_area_percent: float = 0.70,
        hvn_threshold: float = 1.5,
        lvn_threshold: float = 0.4,
    ) -> None:
        self.num_bins = num_bins
        self.value_area_percent = value_area_percent
        self.hvn_threshold = hvn_threshold
        self.lvn_threshold = lvn_threshold

    # ------------------------------------------------------------------
    def compute(self, ohlcv: pd.DataFrame) -> VolumeProfileResult:
        if ohlcv is None or ohlcv.empty:
            raise ValueError("VolumeProfile.compute: leerer OHLCV-DataFrame")

        price_min = float(ohlcv["low"].min())
        price_max = float(ohlcv["high"].max())
        if price_max <= price_min:
            price_max = price_min + 1e-6

        bin_edges = np.linspace(price_min, price_max, self.num_bins + 1)
        bin_size = bin_edges[1] - bin_edges[0]
        volume_per_bin = np.zeros(self.num_bins)

        # Volumen linear ueber Kerzen-Range verteilen
        for _, row in ohlcv.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            vol = float(row["volume"])
            if vol <= 0 or high <= low:
                continue
            start_idx = int(np.clip((low - price_min) / bin_size, 0, self.num_bins - 1))
            end_idx = int(np.clip((high - price_min) / bin_size, 0, self.num_bins - 1))
            if end_idx == start_idx:
                volume_per_bin[start_idx] += vol
                continue
            # Anteil pro Bin
            covered_bins = end_idx - start_idx + 1
            vol_per_step = vol / covered_bins
            volume_per_bin[start_idx : end_idx + 1] += vol_per_step

        total_volume = float(volume_per_bin.sum())
        if total_volume <= 0:
            raise ValueError("VolumeProfile.compute: Gesamt-Volumen ist 0")

        # POC = Bin mit hoechstem Volumen (Mittelpunkt)
        poc_idx = int(np.argmax(volume_per_bin))
        poc = float(bin_edges[poc_idx] + bin_size / 2)

        # Value Area um POC herum aufbauen
        vah, val = self._compute_value_area(bin_edges, volume_per_bin, poc_idx, total_volume, bin_size)

        # HVN / LVN identifizieren
        mean_vol = volume_per_bin.mean()
        hvn = [
            float(bin_edges[i] + bin_size / 2)
            for i, v in enumerate(volume_per_bin)
            if v >= mean_vol * self.hvn_threshold
        ]
        lvn = [
            float(bin_edges[i] + bin_size / 2)
            for i, v in enumerate(volume_per_bin)
            if 0 < v <= mean_vol * self.lvn_threshold
        ]

        # Cluster zu unterscheidbaren Levels zusammenfuehren
        hvn = _cluster_levels(hvn, bin_size * 1.5)
        lvn = _cluster_levels(lvn, bin_size * 1.5)

        value_area_volume = float(
            volume_per_bin[
                (bin_edges[:-1] + bin_size / 2 >= val)
                & (bin_edges[:-1] + bin_size / 2 <= vah)
            ].sum()
        )

        return VolumeProfileResult(
            bins=bin_edges[:-1],
            bin_size=bin_size,
            volume_per_bin=volume_per_bin,
            poc=poc,
            vah=vah,
            val=val,
            hvn=hvn,
            lvn=lvn,
            total_volume=total_volume,
            value_area_volume=value_area_volume,
        )

    # ------------------------------------------------------------------
    def _compute_value_area(
        self,
        bin_edges: np.ndarray,
        vol: np.ndarray,
        poc_idx: int,
        total: float,
        bin_size: float,
    ) -> Tuple[float, float]:
        target = total * self.value_area_percent
        included = vol[poc_idx]
        lo, hi = poc_idx, poc_idx
        n = len(vol)
        while included < target and (lo > 0 or hi < n - 1):
            up_pair = vol[hi + 1 : hi + 3].sum() if hi + 1 < n else -1
            dn_pair = vol[max(0, lo - 2) : lo].sum() if lo > 0 else -1
            if up_pair >= dn_pair and hi + 1 < n:
                hi = min(hi + 2, n - 1)
                included = vol[lo : hi + 1].sum()
            elif lo > 0:
                lo = max(lo - 2, 0)
                included = vol[lo : hi + 1].sum()
            else:
                break
        vah = float(bin_edges[hi] + bin_size)
        val = float(bin_edges[lo])
        return vah, val


# ----------------------------------------------------------------------
def _cluster_levels(levels: List[float], tolerance: float) -> List[float]:
    if not levels:
        return []
    levels = sorted(levels)
    clusters: List[List[float]] = [[levels[0]]]
    for lvl in levels[1:]:
        if abs(lvl - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(lvl)
        else:
            clusters.append([lvl])
    return [float(np.mean(c)) for c in clusters]
