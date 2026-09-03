"""Pump characteristic curves: head, efficiency, NPSHr, power, affinity scaling.

The head curve is stored either as

* a fitted **H = A - B * Q^C** law (EPANET's functional form), or
* a **multi-point** piecewise-linear table (used when < 3 points are given,
  when the fit is poor, or when the caller asks for it).

Q is always m3/s and H metres internally.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit


def _abc(q, a, b, c):
    return a - b * np.power(np.maximum(q, 0.0), c)


@dataclass
class PumpCurve:
    """A single pump's performance at a reference speed / impeller diameter."""

    q_pts: np.ndarray                     # m3/s, ascending
    h_pts: np.ndarray                     # m
    eff_q_pts: np.ndarray | None = None   # m3/s
    eff_pts: np.ndarray | None = None     # percent (0-100)
    npshr_q_pts: np.ndarray | None = None
    npshr_pts: np.ndarray | None = None   # m
    speed_ratio: float = 1.0              # relative to the reference speed
    diameter_ratio: float = 1.0
    design_q_m3s: float | None = None     # nameplate duty flow, if the curve was
    #                                      built from / around one
    name: str = "pump"
    model: str = "multipoint"             # "abc" or "multipoint"
    abc: tuple[float, float, float] | None = None
    _fit_rms: float = field(default=0.0, repr=False)

    # ------------------------------------------------------------------
    # constructors
    # ------------------------------------------------------------------
    @classmethod
    def from_points(cls, q_m3s, h_m, *, eff=None, eff_q=None, npshr=None,
                    npshr_q=None, name="pump", prefer="auto") -> PumpCurve:
        q = np.asarray(q_m3s, dtype=float)
        h = np.asarray(h_m, dtype=float)
        order = np.argsort(q)
        q, h = q[order], h[order]
        curve = cls(
            q_pts=q, h_pts=h,
            eff_q_pts=np.asarray(eff_q, dtype=float) if eff_q is not None else (q if eff is not None else None),
            eff_pts=np.asarray(eff, dtype=float) if eff is not None else None,
            npshr_q_pts=np.asarray(npshr_q, dtype=float) if npshr_q is not None else (q if npshr is not None else None),
            npshr_pts=np.asarray(npshr, dtype=float) if npshr is not None else None,
            name=name,
        )
        if prefer in ("auto", "abc") and len(q) >= 3:
            curve._try_fit_abc(force=(prefer == "abc"))
        return curve

    @classmethod
    def from_single_point(cls, q_design_m3s: float, h_design_m: float, *,
                          shutoff_ratio: float = 1.33, runout_flow_ratio: float = 2.0,
                          name="pump") -> PumpCurve:
        """Synthesise a curve from one duty point using EPANET's rule:
        shut-off head = ``shutoff_ratio`` x design head at Q = 0, and
        zero head at Q = ``runout_flow_ratio`` x design flow.  Fitted as A-B*Q^C.
        """
        q = np.array([0.0, q_design_m3s, runout_flow_ratio * q_design_m3s])
        h = np.array([shutoff_ratio * h_design_m, h_design_m, 0.0])
        curve = cls.from_points(q, h, name=name, prefer="abc")
        curve.design_q_m3s = q_design_m3s
        return curve

    @classmethod
    def synthetic(cls, q_design_m3s: float, h_design_m: float, *,
                  shutoff_ratio: float = 1.20, runout_flow_ratio: float = 1.9,
                  eff_bep: float = 82.0, name="pump") -> PumpCurve:
        """A fuller synthetic curve (5 head points + parabolic efficiency +
        rising NPSHr) for when no manufacturer data exists yet.  ``shutoff_ratio``
        of 1.10-1.25 suits medium specific-speed water pumps."""
        r = np.array([0.0, 0.4, 0.75, 1.0, 1.3, runout_flow_ratio])
        h0 = shutoff_ratio * h_design_m
        hq = np.array([h0,
                       h0 - (h0 - h_design_m) * (0.4 / 1.0) ** 2,
                       h0 - (h0 - h_design_m) * (0.75 / 1.0) ** 2,
                       h_design_m,
                       h_design_m * 0.82,
                       max(h_design_m * 0.45, 0.05)])
        q = r * q_design_m3s
        eff = eff_bep * (2.0 * (r) - r ** 2)
        eff = np.clip(eff, 1.0, eff_bep)
        npshr = 1.5 + 4.0 * r ** 2          # generic rising NPSHr [m]
        curve = cls.from_points(q, hq, eff=eff, eff_q=q, npshr=npshr, npshr_q=q,
                                name=name, prefer="abc")
        curve.design_q_m3s = q_design_m3s
        return curve

    # ------------------------------------------------------------------
    # fitting
    # ------------------------------------------------------------------
    def _try_fit_abc(self, force: bool = False) -> bool:
        q, h = self.q_pts, self.h_pts
        h0 = float(max(h) * 1.05)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", OptimizeWarning)
                popt, _ = curve_fit(
                    _abc, q, h,
                    p0=[h0, max((h0 - min(h)) / (max(q) ** 2 + 1e-9), 1e-6), 2.0],
                    bounds=([max(h) * 0.9, 0.0, 0.5], [h0 * 1.8, np.inf, 6.0]),
                    maxfev=20000,
                )
        except Exception:
            return False
        rms = float(np.sqrt(np.mean((_abc(q, *popt) - h) ** 2)))
        rel = rms / (np.mean(h) + 1e-9)
        if force or rel <= 0.03:
            self.model = "abc"
            self.abc = (float(popt[0]), float(popt[1]), float(popt[2]))
            self._fit_rms = rms
            return True
        return False

    # ------------------------------------------------------------------
    # evaluation (all honour speed_ratio & diameter_ratio via affinity)
    # ------------------------------------------------------------------
    @property
    def _scale_q(self) -> float:
        # speed: Q ~ n   |   impeller trim: Q ~ (D2/D1)^2  (KSB 3.4.6 turn-down rule,
        # which keeps H/Q^2 constant so the trimmed curve slides along a
        # system-curve-shaped locus)
        return self.speed_ratio * self.diameter_ratio ** 2

    @property
    def _scale_h(self) -> float:
        return self.speed_ratio ** 2 * self.diameter_ratio ** 2

    def head(self, q_m3s):
        q = np.asarray(q_m3s, dtype=float)
        q_ref = q / self._scale_q
        if self.model == "abc" and self.abc is not None:
            a, b, c = self.abc
            h_ref = _abc(q_ref, a, b, c)
        else:
            h_ref = np.interp(q_ref, self.q_pts, self.h_pts,
                              left=self.h_pts[0], right=self.h_pts[-1])
        h = h_ref * self._scale_h
        return float(h) if np.ndim(q_m3s) == 0 else h

    def efficiency(self, q_m3s):
        if self.eff_pts is None:
            return np.nan if np.ndim(q_m3s) == 0 else np.full(np.shape(q_m3s), np.nan)
        q = np.asarray(q_m3s, dtype=float) / self._scale_q
        e = np.interp(q, self.eff_q_pts, self.eff_pts,
                      left=self.eff_pts[0], right=self.eff_pts[-1])
        return float(e) if np.ndim(q_m3s) == 0 else e

    def npshr(self, q_m3s):
        if self.npshr_pts is None:
            return np.nan if np.ndim(q_m3s) == 0 else np.full(np.shape(q_m3s), np.nan)
        # NPSHr scales roughly with speed^2 (and weakly with capacity)
        q = np.asarray(q_m3s, dtype=float) / self._scale_q
        n = np.interp(q, self.npshr_q_pts, self.npshr_pts,
                      left=self.npshr_pts[0], right=self.npshr_pts[-1])
        n = n * self.speed_ratio ** 2
        return float(n) if np.ndim(q_m3s) == 0 else n

    def hydraulic_power(self, q_m3s, rho: float = 1000.0, g: float = 9.81):
        """Water power  rho g Q H  [W]."""
        return rho * g * np.asarray(q_m3s, dtype=float) * self.head(q_m3s)

    def shaft_power(self, q_m3s, rho: float = 1000.0, g: float = 9.81):
        """Shaft (brake) power [W] = water power / efficiency."""
        eff = self.efficiency(q_m3s)
        eff = np.where(np.isnan(eff), 100.0, eff) / 100.0
        return self.hydraulic_power(q_m3s, rho, g) / np.maximum(eff, 1e-3)

    # ------------------------------------------------------------------
    # characteristic points
    # ------------------------------------------------------------------
    def shutoff_head(self) -> float:
        return self.head(0.0)

    def max_flow(self) -> float:
        """Flow at H = 0 (curve runout), scaled for current speed/diameter."""
        if self.model == "abc" and self.abc is not None:
            a, b, c = self.abc
            q_ref = (a / b) ** (1.0 / c) if b > 0 else self.q_pts[-1]
        else:
            q_ref = float(self.q_pts[-1])
            if self.h_pts[-1] > 0 and len(self.q_pts) >= 2:
                slope = (self.h_pts[-1] - self.h_pts[-2]) / (self.q_pts[-1] - self.q_pts[-2])
                if slope < 0:
                    q_ref += -self.h_pts[-1] / slope
        return q_ref * self._scale_q

    def bep(self) -> tuple[float, float, float]:
        """Best-efficiency point as (Q [m3/s], H [m], eff [%]).
        If no efficiency data, returns the mid-curve point."""
        if self.eff_pts is not None:
            qq = np.linspace(self.eff_q_pts[0], self.eff_q_pts[-1], 200) * self._scale_q
            ee = self.efficiency(qq)
            i = int(np.nanargmax(ee))
            return float(qq[i]), float(self.head(qq[i])), float(ee[i])
        if self.design_q_m3s is not None:
            q_d = self.design_q_m3s * self._scale_q
            return q_d, float(self.head(q_d)), float("nan")
        q_mid = 0.6 * self.max_flow()
        return q_mid, float(self.head(q_mid)), float("nan")

    # ------------------------------------------------------------------
    # affinity & combination
    # ------------------------------------------------------------------
    def scaled(self, speed_ratio: float = 1.0, diameter_ratio: float = 1.0) -> PumpCurve:
        c = PumpCurve(**{**self.__dict__})
        c.speed_ratio = self.speed_ratio * speed_ratio
        c.diameter_ratio = self.diameter_ratio * diameter_ratio
        return c

    def sample(self, n: int = 25, q_max: float | None = None):
        q_max = q_max if q_max is not None else self.max_flow()
        q = np.linspace(0.0, q_max, n)
        return q, self.head(q)

    @staticmethod
    def parallel(pumps: list[PumpCurve], n: int = 40) -> PumpCurve:
        """Combined curve of pumps in parallel (flows add at equal head)."""
        h_lo = max(min(p.head(p.max_flow() * 0.999) for p in pumps), 0.0)
        h_hi = min(p.shutoff_head() for p in pumps)
        heads = np.linspace(h_hi, h_lo, n)
        q_tot = np.zeros_like(heads)
        for p in pumps:
            qs, hs = p.sample(200)
            q_tot += np.interp(heads, hs[::-1], qs[::-1], left=0.0, right=qs[-1])
        order = np.argsort(q_tot)
        return PumpCurve.from_points(q_tot[order], heads[order],
                                     name=f"{len(pumps)}x {pumps[0].name} (parallel)",
                                     prefer="multipoint")

    @staticmethod
    def series(pumps: list[PumpCurve], n: int = 40) -> PumpCurve:
        """Combined curve of pumps/stages in series (heads add at equal flow)."""
        q_hi = min(p.max_flow() for p in pumps)
        q = np.linspace(0.0, q_hi, n)
        h = np.zeros_like(q)
        for p in pumps:
            h += p.head(q)
        return PumpCurve.from_points(q, h,
                                     name=f"{len(pumps)}x {pumps[0].name} (series)",
                                     prefer="abc")

    # ------------------------------------------------------------------
    def summary(self) -> dict:
        qb, hb, eb = self.bep()
        return {
            "name": self.name,
            "model": self.model,
            "abc": self.abc,
            "fit_rms_m": round(self._fit_rms, 4),
            "shutoff_head_m": round(self.shutoff_head(), 3),
            "max_flow_lps": round(self.max_flow() * 1000.0, 2),
            "bep_flow_lps": round(qb * 1000.0, 2),
            "bep_head_m": round(hb, 3),
            "bep_efficiency_pct": None if np.isnan(eb) else round(eb, 2),
            "speed_ratio": self.speed_ratio,
            "diameter_ratio": self.diameter_ratio,
        }
