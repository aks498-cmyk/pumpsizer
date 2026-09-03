"""Pump selection & ranking against a duty point (and, optionally, the real
system curve).

For every catalogue model the engine tries, in order:

* **fixed speed / full impeller** - does the published curve pass at or above
  the duty head at the duty flow?
* **impeller trim** - if the full curve overshoots, solve the diameter ratio
  D2/D1 (>= the model's trim limit) that puts the curve through the duty point;
* **variable speed** - if the model is VFD-rated, solve the speed ratio that
  puts the curve through the duty point.

Each feasible candidate is scored on efficiency at duty, proximity to BEP,
NPSH margin and how close the head is to the duty (avoid gross oversizing).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from .catalog import Catalog, PumpModel
from .constants import LPS_TO_M3S, G
from .operating import solve_operating_point
from .system import SystemCurve


@dataclass
class SelectionCriteria:
    duty_flow_m3s: float
    duty_head_m: float
    system_curve: SystemCurve | None = None
    npsh_available_m: float | None = None
    allow_trim: bool = True
    allow_vfd: bool = True
    bep_window: tuple[float, float] = (0.70, 1.20)  # acceptable Q_op / Q_bep
    max_head_margin_pct: float = 40.0  # reject if duty head is < curve by more
    weights: dict = field(
        default_factory=lambda: {"efficiency": 0.45, "bep": 0.30, "npsh": 0.15, "head_margin": 0.10}
    )

    @classmethod
    def from_duty(cls, flow_lps: float, head_m: float, **kw) -> SelectionCriteria:
        return cls(duty_flow_m3s=flow_lps * LPS_TO_M3S, duty_head_m=head_m, **kw)


@dataclass
class Candidate:
    model: PumpModel
    feasible: bool
    method: str  # "fixed" | "trim" | "vfd" | "infeasible"
    trim_ratio: float
    speed_ratio: float
    operating_flow_m3s: float
    operating_head_m: float
    efficiency_pct: float
    npshr_m: float
    npsh_margin_m: float | None
    bep_flow_m3s: float
    bep_ratio: float  # Q_op / Q_bep
    within_bep_window: bool
    head_margin_pct: float  # (curve head at duty flow, full size) vs duty head
    shaft_power_kw: float
    score: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "pump": self.model.key,
            "feasible": self.feasible,
            "method": self.method,
            "trim_ratio": round(self.trim_ratio, 4),
            "speed_ratio": round(self.speed_ratio, 4),
            "operating_flow_lps": round(self.operating_flow_m3s * 1000, 2),
            "operating_head_m": round(self.operating_head_m, 2),
            "efficiency_pct": None
            if np.isnan(self.efficiency_pct)
            else round(self.efficiency_pct, 1),
            "npshr_m": None if np.isnan(self.npshr_m) else round(self.npshr_m, 2),
            "npsh_margin_m": None if self.npsh_margin_m is None else round(self.npsh_margin_m, 2),
            "bep_flow_lps": round(self.bep_flow_m3s * 1000, 2),
            "bep_ratio": round(self.bep_ratio, 3),
            "within_bep_window": self.within_bep_window,
            "head_margin_pct": round(self.head_margin_pct, 1),
            "shaft_power_kw": round(self.shaft_power_kw, 2),
            "score": round(self.score, 4),
            "reasons": self.reasons,
        }


def _trim_efficiency_penalty_pts(trim_ratio: float) -> float:
    """~2 efficiency points lost per 10% of impeller diameter trimmed."""
    return max(0.0, (1.0 - trim_ratio) * 20.0)


def evaluate(model: PumpModel, c: SelectionCriteria) -> Candidate:
    reasons: list[str] = []
    qd, hd = c.duty_flow_m3s, c.duty_head_m
    base = model.to_pump_curve()

    h_full_at_duty = float(base.head(qd))
    head_margin_pct = (h_full_at_duty - hd) / hd * 100.0 if hd > 0 else 0.0

    method, trim, speed = "infeasible", 1.0, 1.0
    curve = base
    head_tol = 0.03  # curve-reading precision: accept +/-3%
    rel = (h_full_at_duty - hd) / hd if hd > 0 else 0.0

    if rel >= -head_tol:
        method, curve = "fixed", base
        if rel < 0:
            reasons.append(f"curve {abs(rel) * 100:.1f}% under duty head (within tolerance)")
        elif c.allow_trim and rel > 0.01:
            lo = model.trim_limit_ratio
            try:
                if base.scaled(diameter_ratio=lo).head(qd) <= hd:
                    trim = brentq(
                        lambda dd: base.scaled(diameter_ratio=dd).head(qd) - hd,
                        lo,
                        1.0,
                        xtol=1e-5,
                        maxiter=100,
                    )
                    if trim >= 0.995:
                        trim, method, curve = 1.0, "fixed", base
                    else:
                        method, curve = "trim", base.scaled(diameter_ratio=trim)
                        reasons.append(f"impeller trimmed to {trim * 100:.0f}% dia")
                else:
                    method, trim = "trim", lo
                    curve = base.scaled(diameter_ratio=lo)
                    reasons.append(
                        f"trimmed to min {lo * 100:.0f}% dia; still "
                        f"+{(curve.head(qd) - hd) / hd * 100:.0f}% head (throttle)"
                    )
            except ValueError:
                pass
        if method == "fixed" and rel * 100.0 > c.max_head_margin_pct:
            reasons.append(f"oversized: +{rel * 100:.0f}% head at duty flow (no trim)")
    elif c.allow_vfd and model.max_speed_ratio > 1.0:
        try:
            speed = brentq(
                lambda s: base.scaled(speed_ratio=s).head(qd) - hd,
                1.0,
                model.max_speed_ratio,
                xtol=1e-5,
                maxiter=100,
            )
            method, curve = "vfd", base.scaled(speed_ratio=speed)
            reasons.append(f"VFD boosted to {speed * 100:.0f}% speed")
        except ValueError:
            reasons.append("curve below duty head even at max speed")
    else:
        reasons.append("curve below duty head at reference speed")

    feasible = method != "infeasible"

    # operating point: true intersection with the system curve if provided,
    # else the duty point itself
    if feasible and c.system_curve is not None:
        try:
            op = solve_operating_point(curve, c.system_curve)
            q_op, h_op = op.flow_m3s, op.head_m
            p_shaft = op.shaft_power_kw
        except ValueError as exc:
            feasible = False
            reasons.append(f"no operating point vs system curve ({exc})")
            q_op, h_op, p_shaft = qd, hd, float("nan")
    else:
        q_op, h_op = qd, hd
        eff_here = curve.efficiency(qd)
        eff_frac = (eff_here / 100.0) if not np.isnan(eff_here) else 0.8
        p_shaft = 1000.0 * G * qd * hd / max(eff_frac, 1e-3) / 1000.0

    eff = float(curve.efficiency(q_op))
    if not np.isnan(eff):
        eff -= _trim_efficiency_penalty_pts(trim)
    npshr = float(curve.npshr(q_op))
    npsh_margin = None
    if c.npsh_available_m is not None and not np.isnan(npshr):
        npsh_margin = c.npsh_available_m - npshr
        if npsh_margin < max(0.5, 0.1 * npshr):
            reasons.append(f"low NPSH margin {npsh_margin:.2f} m")

    q_bep, _, _ = curve.bep()
    bep_ratio = q_op / q_bep if q_bep > 0 else float("nan")
    within = c.bep_window[0] <= bep_ratio <= c.bep_window[1]
    if not within and feasible:
        reasons.append(f"operates at {bep_ratio * 100:.0f}% of BEP flow")

    score = _score(c, eff, bep_ratio, npsh_margin, npshr, head_margin_pct, feasible, within)
    page = f" p.{model.datasheet_page}" if getattr(model, "datasheet_page", None) else ""
    if feasible and getattr(model, "envelope_only", False):
        reasons.append(f"envelope match - confirm curve from {model.series} booklet{page}")
        score *= 0.88
    elif feasible and getattr(model, "digitised", False) and not model.verified:
        reasons.append(f"curve machine-digitised - confirm against datasheet{page}")
        score *= 0.94
    elif feasible and not model.verified:
        score *= 0.97

    return Candidate(
        model=model,
        feasible=feasible,
        method=method,
        trim_ratio=trim,
        speed_ratio=speed,
        operating_flow_m3s=q_op,
        operating_head_m=h_op,
        efficiency_pct=eff,
        npshr_m=npshr,
        npsh_margin_m=npsh_margin,
        bep_flow_m3s=q_bep,
        bep_ratio=bep_ratio,
        within_bep_window=within,
        head_margin_pct=head_margin_pct,
        shaft_power_kw=p_shaft,
        score=score,
        reasons=reasons,
    )


def _score(
    c: SelectionCriteria,
    eff: float,
    bep_ratio: float,
    npsh_margin: float | None,
    npshr: float,
    head_margin_pct: float,
    feasible: bool,
    within: bool,
) -> float:
    if not feasible:
        return -1.0
    w = c.weights
    s_eff = np.clip((eff - 40.0) / 45.0, 0.0, 1.0) if not np.isnan(eff) else 0.4
    s_bep = np.clip(1.0 - abs(bep_ratio - 1.0) / 0.5, 0.0, 1.0) if not np.isnan(bep_ratio) else 0.3
    if npsh_margin is None:
        s_npsh = 0.5
    else:
        thr = max(0.5, 0.1 * (npshr if not np.isnan(npshr) else 0.0))
        s_npsh = np.clip((npsh_margin - thr) / 3.0 + 0.5, 0.0, 1.0)
    s_hm = np.clip(1.0 - max(head_margin_pct, 0.0) / 50.0, 0.0, 1.0)
    score = (
        w["efficiency"] * s_eff + w["bep"] * s_bep + w["npsh"] * s_npsh + w["head_margin"] * s_hm
    )
    if not within:
        score *= 0.85
    return float(score)


def select(
    catalog: Catalog,
    criteria: SelectionCriteria,
    *,
    top: int | None = None,
    include_infeasible: bool = False,
) -> list[Candidate]:
    cands = [evaluate(m, criteria) for m in catalog]
    if not include_infeasible:
        cands = [x for x in cands if x.feasible]
    cands.sort(key=lambda x: x.score, reverse=True)
    return cands[:top] if top else cands
