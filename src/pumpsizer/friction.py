"""Pipe-friction models.

Two head-loss methods are supported:

* ``"DW"``  Darcy-Weisbach with the Colebrook-White friction factor
            (the method used by the source workbook).  Solved iteratively;
            Haaland's explicit formula is the first guess.
* ``"HW"``  Hazen-Williams.  Provided so a stand-alone system curve can be
            made to match an EPANET model that uses the (default) H-W method.

All quantities are SI: Q [m3/s], D [m], L [m], v [m/s], hf [m].
"""

from __future__ import annotations

import math

LAMINAR_RE = 2300.0
TURBULENT_RE = 4000.0


def reynolds(v: float, d: float, nu: float) -> float:
    """Reynolds number for full-bore circular pipe flow."""
    if d <= 0 or nu <= 0:
        return 0.0
    return abs(v) * d / nu


def _haaland(re: float, rel_rough: float) -> float:
    """Explicit Haaland approximation of the Colebrook-White factor."""
    return (-1.8 * math.log10((rel_rough / 3.7) ** 1.11 + 6.9 / re)) ** -2


def colebrook_white(re: float, rel_rough: float, tol: float = 1e-10, max_iter: int = 100) -> float:
    """Darcy friction factor from the implicit Colebrook-White equation.

    ``rel_rough`` is the relative roughness e/D (both in the same unit).
    Laminar (Re < 2300): f = 64/Re.  The 2300-4000 transition is blended
    linearly between the laminar value and the turbulent Colebrook value.
    """
    if re <= 0:
        return 0.0
    if re < LAMINAR_RE:
        return 64.0 / re

    def turbulent(reynolds_number: float) -> float:
        f = _haaland(reynolds_number, rel_rough)
        for _ in range(max_iter):
            rhs = -2.0 * math.log10(rel_rough / 3.7 + 2.51 / (reynolds_number * math.sqrt(f)))
            f_new = 1.0 / (rhs * rhs)
            if abs(f_new - f) <= tol:
                return f_new
            f = f_new
        return f

    if re < TURBULENT_RE:  # transitional blend
        f_lam = 64.0 / LAMINAR_RE
        f_turb = turbulent(TURBULENT_RE)
        w = (re - LAMINAR_RE) / (TURBULENT_RE - LAMINAR_RE)
        return f_lam + w * (f_turb - f_lam)

    return turbulent(re)


def friction_factor(v: float, d: float, roughness: float, nu: float) -> float:
    """Convenience wrapper: Darcy friction factor from primitive quantities.

    ``roughness`` and ``d`` must share a unit (e.g. both mm or both m).
    """
    re = reynolds(v, d, nu)
    if re == 0.0:
        return 0.0
    return colebrook_white(re, roughness / d)


def darcy_weisbach_hf(f: float, length: float, d: float, v: float, g: float = 9.81) -> float:
    """Darcy-Weisbach friction head loss [m]:  hf = f * (L/D) * v^2 / (2 g)."""
    if d <= 0:
        return 0.0
    return f * (length / d) * v * v / (2.0 * g)


def hazen_williams_hf(q: float, length: float, d: float, c: float) -> float:
    """Hazen-Williams friction head loss [m] (SI form).

        hf = 10.67 * L * Q^1.852 / (C^1.852 * D^4.8704)

    Q [m3/s], L [m], D [m], C dimensionless.  This is the same constant EPANET
    uses for SI flow units.
    """
    if d <= 0 or c <= 0 or q == 0:
        return 0.0
    return 10.67 * length * abs(q) ** 1.852 / (c**1.852 * d**4.8704)


def velocity(q: float, d: float) -> float:
    """Mean full-bore velocity [m/s] for flow ``q`` [m3/s] in diameter ``d`` [m]."""
    if d <= 0:
        return 0.0
    return 4.0 * q / (math.pi * d * d)
