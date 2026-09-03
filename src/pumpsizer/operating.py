"""Operating-point solver: intersection of a pump curve and a system curve.

Covers single pumps, N pumps in parallel, and variable-speed operation
(find the speed that meets a target flow, subject to a minimum-speed limit).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from .pumpcurve import PumpCurve
from .system import SystemCurve


@dataclass
class OperatingPoint:
    flow_m3s: float
    head_m: float
    efficiency_pct: float
    npshr_m: float
    hydraulic_power_kw: float
    shaft_power_kw: float
    speed_ratio: float
    n_pumps: int
    flow_per_pump_m3s: float
    system_label: str
    pump_label: str
    note: str = ""

    @property
    def flow_lps(self) -> float:
        return self.flow_m3s * 1000.0

    @property
    def flow_m3h(self) -> float:
        return self.flow_m3s * 3600.0

    def as_dict(self) -> dict:
        return {
            "flow_lps": round(self.flow_lps, 3),
            "flow_m3h": round(self.flow_m3h, 2),
            "head_m": round(self.head_m, 3),
            "efficiency_pct": None if np.isnan(self.efficiency_pct) else round(self.efficiency_pct, 2),
            "npshr_m": None if np.isnan(self.npshr_m) else round(self.npshr_m, 3),
            "hydraulic_power_kw": round(self.hydraulic_power_kw, 3),
            "shaft_power_kw": round(self.shaft_power_kw, 3),
            "speed_ratio": round(self.speed_ratio, 4),
            "n_pumps": self.n_pumps,
            "flow_per_pump_lps": round(self.flow_per_pump_m3s * 1000.0, 3),
            "system": self.system_label,
            "pump": self.pump_label,
            "note": self.note,
        }


def _intersect(pump: PumpCurve, system: SystemCurve, q_hi: float) -> float:
    """Flow where pump.head(Q) == system.head(Q) on (0, q_hi]."""
    def diff(q):
        return float(pump.head(q) - system.head(q))

    lo, hi = 1e-6, max(q_hi, 1e-5)
    d_lo, d_hi = diff(lo), diff(hi)
    if d_lo < 0:
        # pump cannot even meet static head + losses near zero flow
        raise ValueError("pump shut-off head is below the system static head; "
                         "no operating point exists")
    if d_lo * d_hi > 0:
        # scan for a bracket
        qs = np.linspace(lo, hi, 200)
        ds = np.array([diff(q) for q in qs])
        sign_change = np.where(np.diff(np.sign(ds)) != 0)[0]
        if len(sign_change) == 0:
            raise ValueError("no operating point found in the search range")
        lo, hi = qs[sign_change[0]], qs[sign_change[0] + 1]
    return float(brentq(diff, lo, hi, xtol=1e-9, rtol=1e-10, maxiter=200))


def _make_point(pump: PumpCurve, system: SystemCurve, q_total: float,
                n_pumps: int, speed_ratio: float, rho: float, g: float,
                note: str = "") -> OperatingPoint:
    head = float(system.head(q_total))
    q_pp = q_total / n_pumps
    eff = float(pump.efficiency(q_pp))
    npshr = float(pump.npshr(q_pp))
    p_hyd = rho * g * q_total * head / 1000.0
    eff_frac = (eff / 100.0) if not np.isnan(eff) else 1.0
    p_shaft = p_hyd / max(eff_frac, 1e-3)
    return OperatingPoint(
        flow_m3s=q_total, head_m=head, efficiency_pct=eff, npshr_m=npshr,
        hydraulic_power_kw=p_hyd, shaft_power_kw=p_shaft,
        speed_ratio=speed_ratio, n_pumps=n_pumps, flow_per_pump_m3s=q_pp,
        system_label=system.label, pump_label=pump.name, note=note,
    )


def solve_operating_point(pump: PumpCurve, system: SystemCurve, *,
                          rho: float = 1000.0, g: float = 9.81) -> OperatingPoint:
    """Single-pump operating point."""
    q = _intersect(pump, system, pump.max_flow())
    return _make_point(pump, system, q, n_pumps=1,
                       speed_ratio=pump.speed_ratio, rho=rho, g=g)


def solve_parallel(pump: PumpCurve, system: SystemCurve, n_pumps: int, *,
                   rho: float = 1000.0, g: float = 9.81) -> OperatingPoint:
    """Operating point with ``n_pumps`` identical pumps running in parallel."""
    if n_pumps == 1:
        return solve_operating_point(pump, system, rho=rho, g=g)
    combined = PumpCurve.parallel([pump] * n_pumps)
    q = _intersect(combined, system, combined.max_flow())
    pt = _make_point(pump, system, q, n_pumps=n_pumps,
                     speed_ratio=pump.speed_ratio, rho=rho, g=g,
                     note=f"{n_pumps} pumps in parallel")
    # efficiency/NPSHr evaluated at per-pump flow (already handled in _make_point)
    return pt


def solve_vfd_speed(pump: PumpCurve, system: SystemCurve, target_flow_m3s: float, *,
                    min_speed_ratio: float = 0.5, n_pumps: int = 1,
                    rho: float = 1000.0, g: float = 9.81) -> OperatingPoint:
    """Find the relative speed at which the (parallel set of) pump(s) delivers
    ``target_flow_m3s`` against ``system``.  Clamped to ``min_speed_ratio``..1.0.

    Note: uses the affinity law H ~ n^2 on the pump curve.  The true VFD locus
    is slightly different because the static-head part of the system curve does
    not scale with speed; this solver accounts for that by intersecting the
    *speed-scaled* pump curve with the *unscaled* system curve.
    """
    base = pump.scaled(speed_ratio=1.0)

    def flow_error(s: float) -> float:
        trial = base.scaled(speed_ratio=s)
        combined = trial if n_pumps == 1 else PumpCurve.parallel([trial] * n_pumps)
        try:
            q = _intersect(combined, system, combined.max_flow())
        except ValueError:
            return -target_flow_m3s        # too slow to reach static head
        return q - target_flow_m3s

    e_min, e_max = flow_error(min_speed_ratio), flow_error(1.0)
    if e_min > 0:
        s = min_speed_ratio
        note = f"target flow reached below minimum speed; clamped to {min_speed_ratio:.0%}"
    elif e_max < 0:
        s = 1.0
        note = "full speed cannot meet the target flow"
    else:
        s = float(brentq(flow_error, min_speed_ratio, 1.0, xtol=1e-6, maxiter=200))
        note = f"VFD trimmed to {s:.1%} speed"

    trial = base.scaled(speed_ratio=s)
    combined = trial if n_pumps == 1 else PumpCurve.parallel([trial] * n_pumps)
    q = _intersect(combined, system, combined.max_flow())
    return _make_point(trial, system, q, n_pumps=n_pumps, speed_ratio=s,
                       rho=rho, g=g, note=note)
