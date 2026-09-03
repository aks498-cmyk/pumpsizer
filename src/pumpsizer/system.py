"""System (installation) characteristic curve  H_sys(Q) = H_static + losses(Q).

A system curve is assembled from:

* a **static head** (geodetic lift +/- any pressurised end conditions),
* one or more **pipe reaches** (friction loss), and
* **minor losses**, each referenced to the bore whose velocity drives it.

Friction uses Darcy-Weisbach/Colebrook-White (``method="DW"``, the workbook
method) or Hazen-Williams (``method="HW"``, to match an EPANET model).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .constants import G
from .friction import (
    colebrook_white,
    darcy_weisbach_hf,
    hazen_williams_hf,
    reynolds,
    velocity,
)
from .pipes import PipeSegment


@dataclass(frozen=True)
class MinorLoss:
    """A lumped local loss  h = k_total * v(D)^2 / (2 g)."""

    name: str
    k_total: float
    diameter_mm: float

    def head_loss(self, q_m3s: float) -> float:
        d = self.diameter_mm / 1000.0
        if d <= 0:
            return 0.0
        v = velocity(q_m3s, d)
        return self.k_total * v * v / (2.0 * G)


@dataclass
class SystemCurve:
    """Callable installation curve.  ``head(Q)`` returns total system head [m]."""

    static_head: float
    segments: list[PipeSegment] = field(default_factory=list)
    minor_losses: list[MinorLoss] = field(default_factory=list)
    kinematic_viscosity: float = 1.0e-6
    method: str = "DW"                      # "DW" or "HW"
    roughness_condition: str = "new"        # label only, for reporting
    label: str = "system"

    # -- loss components ----------------------------------------------------
    def friction_loss(self, q_m3s: float) -> float:
        total = 0.0
        for seg in self.segments:
            d = seg.diameter_m
            if d <= 0:
                continue
            if self.method.upper() == "HW":
                total += hazen_williams_hf(q_m3s, seg.length_m, d,
                                           seg.hazen_williams_c)
            else:
                v = seg.velocity(q_m3s)
                re = reynolds(v, d, self.kinematic_viscosity)
                f = colebrook_white(re, seg.roughness_mm / seg.diameter_mm)
                total += darcy_weisbach_hf(f, seg.length_m, d, v, G)
        return total

    def minor_loss(self, q_m3s: float) -> float:
        return sum(ml.head_loss(q_m3s) for ml in self.minor_losses)

    # -- public ----------------------------------------------------------
    def head(self, q_m3s):
        """System head [m] at flow ``q_m3s`` [m3/s].  Accepts scalars or arrays."""
        arr = np.atleast_1d(np.asarray(q_m3s, dtype=float))
        out = np.empty_like(arr)
        for i, q in enumerate(arr):
            out[i] = self.static_head + self.friction_loss(q) + self.minor_loss(q)
        return float(out[0]) if np.isscalar(q_m3s) or np.ndim(q_m3s) == 0 else out

    def dynamic_loss(self, q_m3s: float) -> float:
        """Friction + minor losses only (system head minus static head)."""
        return self.friction_loss(q_m3s) + self.minor_loss(q_m3s)

    def k_resistance(self, q_ref_m3s: float) -> float:
        """Resistance coefficient K in the fitted form H ~ H_static + K * Q^2,
        evaluated at ``q_ref_m3s`` (K has units s^2/m^5)."""
        if q_ref_m3s <= 0:
            return 0.0
        return self.dynamic_loss(q_ref_m3s) / (q_ref_m3s ** 2)

    def sample(self, q_max_m3s: float, n: int = 60):
        """Return (Q, H) arrays from ~0 to ``q_max_m3s`` for plotting/EPANET."""
        q = np.linspace(1e-6, q_max_m3s, n)
        return q, self.head(q)


@dataclass
class SystemCurveSet:
    """The family of curves an installation actually spans:
    {min, max static head} x {new, used roughness}."""

    max_static_new: SystemCurve
    max_static_used: SystemCurve
    min_static_new: SystemCurve
    min_static_used: SystemCurve

    def design(self) -> SystemCurve:
        """Curve to size the pump against: highest resistance the pump must
        overcome = maximum static head with 'used' (aged) roughness."""
        return self.max_static_used

    def as_dict(self) -> dict[str, SystemCurve]:
        return {
            "max_static/new": self.max_static_new,
            "max_static/used": self.max_static_used,
            "min_static/new": self.min_static_new,
            "min_static/used": self.min_static_used,
        }
