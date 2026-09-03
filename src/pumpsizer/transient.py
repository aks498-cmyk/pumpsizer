"""Method-of-characteristics (MOC) transient solver for a single pumping main.

Handles the classic power-failure case:

    constant-head SUMP -> PUMP (+ optional AIR VESSEL) -> rising main -> constant-head RESERVOIR

* pipeline discretised into ``reaches`` segments, Courant number 1
  (dt = dx / a), steady friction lumped per reach;
* pump modelled by its rated H-Q curve with affinity scaling H = w^2 * Hr(Q/w),
  speed ``w`` decaying from a rotating-inertia torque balance, and a check
  valve that shuts on flow reversal;
* discrete vapour-cavity model (DVCM) at every interior node - if the head
  falls to the local vapour level a cavity opens and later collapses;
* optional simple hydro-pneumatic air vessel at the pump discharge
  (polytropic gas law; vessel water-level change and throttle loss neglected
  in this version - stated so you can judge conservatism).

Pragmatic engineering model (Wylie & Streeter / Chaudhry formulation) - not a
substitute for a specialist package on a complex network, but it turns the
Phase-4 rule-of-thumb numbers into an actual pressure envelope and lets you
check whether a proposed air vessel is enough.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from .constants import G
from .pumpcurve import PumpCurve
from .surge import ATM_HEAD_M, wave_celerity


@dataclass
class Pipeline:
    length_m: float
    diameter_m: float
    wave_speed_m_s: float
    friction_factor: float = 0.018
    pump_elevation_m: float = 0.0
    reservoir_elevation_m: float = 0.0
    reaches: int = 20

    @property
    def area_m2(self) -> float:
        return math.pi * self.diameter_m ** 2 / 4.0

    def node_elevations(self) -> np.ndarray:
        return np.linspace(self.pump_elevation_m, self.reservoir_elevation_m,
                           self.reaches + 1)

    @classmethod
    def from_pipe(cls, *, length_m: float, diameter_mm: float, wall_thickness_mm: float,
                  youngs_modulus_pa: float, friction_factor: float = 0.018,
                  pump_elevation_m: float = 0.0, reservoir_elevation_m: float = 0.0,
                  reaches: int = 20, rho: float = 1000.0) -> Pipeline:
        a = wave_celerity(diameter_mm / 1000.0, wall_thickness_mm / 1000.0,
                          youngs_modulus_pa, rho=rho)
        return cls(length_m, diameter_mm / 1000.0, a, friction_factor,
                   pump_elevation_m, reservoir_elevation_m, reaches)


@dataclass
class PumpInertia:
    """Rated point + rotating inertia for the pump-rundown boundary."""
    rated_speed_rpm: float
    rated_flow_m3s: float
    rated_head_m: float
    total_inertia_kgm2: float
    rated_efficiency: float = 0.80
    curve: PumpCurve | None = None          # rated-speed H-Q; synthesised if None

    def __post_init__(self):
        if self.curve is None:
            self.curve = PumpCurve.synthetic(self.rated_flow_m3s, self.rated_head_m,
                                             eff_bep=self.rated_efficiency * 100.0)

    def head(self, q_m3s: float, w: float) -> float:
        if w <= 1e-6:
            return 0.0
        return w * w * float(self.curve.head(max(q_m3s, 0.0) / w))

    def flow_for_head(self, dh_m: float, w: float) -> float:
        """Invert the (affinity-scaled) pump curve: flow that produces head
        rise ``dh_m`` at relative speed ``w`` (>= 0, 0 if it cannot)."""
        if w <= 1e-4 or dh_m <= 0:
            return 0.0
        hi = self.curve.max_flow() * w
        if self.head(0.0, w) < dh_m:
            return 0.0
        if self.head(hi, w) > dh_m:
            return hi
        try:
            return float(brentq(lambda q: self.head(q, w) - dh_m, 0.0, hi, maxiter=100))
        except ValueError:
            return 0.0

    @property
    def omega0(self) -> float:
        return 2.0 * math.pi * self.rated_speed_rpm / 60.0


@dataclass
class AirVessel:
    gas_volume_m3: float                  # initial (normal-operation) gas volume
    polytropic_n: float = 1.2


@dataclass
class TransientResult:
    time_s: np.ndarray
    head_pump_m: np.ndarray
    flow_pump_m3s: np.ndarray
    speed_frac: np.ndarray
    head_midpoint_m: np.ndarray
    envelope_max_m: np.ndarray
    envelope_min_m: np.ndarray
    node_x_m: np.ndarray
    node_elevation_m: np.ndarray
    vapour_anywhere: bool
    max_head_m: float
    min_head_m: float
    air_vessel_gas_volume_m3: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        i_lo = int(np.argmin(self.envelope_min_m))
        i_hi = int(np.argmax(self.envelope_max_m))
        return {
            "duration_s": round(float(self.time_s[-1]), 2),
            "max_head_m": round(self.max_head_m, 2),
            "max_head_at_x_m": round(float(self.node_x_m[i_hi]), 1),
            "min_head_m": round(self.min_head_m, 2),
            "min_head_at_x_m": round(float(self.node_x_m[i_lo]), 1),
            "min_gauge_pressure_head_m": round(
                float(np.min(self.envelope_min_m - self.node_elevation_m)), 2),
            "vapour_separation": self.vapour_anywhere,
            "air_vessel_max_gas_volume_m3": (
                None if self.air_vessel_gas_volume_m3 is None
                else round(float(self.air_vessel_gas_volume_m3.max()), 3)),
            "notes": self.notes,
        }


def simulate_pump_trip(pipe: Pipeline, pump: PumpInertia, *,
                       sump_level_m: float, reservoir_level_m: float,
                       duration_s: float | None = None, rho: float = 1000.0,
                       air_vessel: AirVessel | None = None,
                       vapour_head_m: float = 0.24) -> TransientResult:
    """Simulate a total power failure (pump torque -> 0 at t=0)."""
    n = pipe.reaches
    a, A = pipe.wave_speed_m_s, pipe.area_m2
    dx = pipe.length_m / n
    dt = dx / a
    if duration_s is None:
        duration_s = 20.0 * pipe.length_m / a
    steps = int(round(duration_s / dt))
    B = a / (G * A)
    R = pipe.friction_factor * dx / (2.0 * G * pipe.diameter_m * A * A)
    z = pipe.node_elevations()
    x = np.linspace(0.0, pipe.length_m, n + 1)
    vap_level = z - ATM_HEAD_M + vapour_head_m

    # --- steady state -------------------------------------------------
    def steady_residual(q):
        hf = pipe.friction_factor * pipe.length_m / pipe.diameter_m * (q / A) ** 2 / (2 * G)
        return pump.head(q, 1.0) - ((reservoir_level_m - sump_level_m) + hf)

    try:
        Q0 = brentq(steady_residual, 1e-4, pump.curve.max_flow(), maxiter=200)
    except ValueError:
        Q0 = pump.rated_flow_m3s
    H = np.zeros(n + 1)
    Q = np.full(n + 1, Q0)
    hf_reach = R * Q0 * abs(Q0)
    H[0] = sump_level_m + pump.head(Q0, 1.0)
    for i in range(1, n + 1):
        H[i] = H[i - 1] - hf_reach

    w = 1.0
    cav = np.zeros(n + 1)
    env_max, env_min = H.copy(), H.copy()
    t = np.zeros(steps + 1)
    hp = np.zeros(steps + 1); hp[0] = H[0]
    qp = np.zeros(steps + 1); qp[0] = Q[0]
    wf = np.zeros(steps + 1); wf[0] = 1.0
    hmid = np.zeros(steps + 1); hmid[0] = H[n // 2]
    gasv = np.zeros(steps + 1)
    vapour_anywhere = False
    check_valve_shut = False

    if air_vessel is not None:
        Vg = air_vessel.gas_volume_m3
        Hgas_abs0 = H[0] - z[0] + ATM_HEAD_M
        gas_C = Hgas_abs0 * Vg ** air_vessel.polytropic_n
    else:
        Vg = gas_C = 0.0
    gasv[0] = Vg

    Hn, Qn = H.copy(), Q.copy()
    for s in range(1, steps + 1):
        # -- interior nodes (with DVCM) --
        for i in range(1, n):
            Cp = H[i - 1] + Q[i - 1] * (B - R * abs(Q[i - 1]))
            Cm = H[i + 1] - Q[i + 1] * (B - R * abs(Q[i + 1]))
            Hi = 0.5 * (Cp + Cm)
            if Hi < vap_level[i] or cav[i] > 0:
                Hi = vap_level[i]
                Qup = (Cp - Hi) / B
                Qdn = (Hi - Cm) / B
                cav[i] += (Qdn - Qup) * dt
                if cav[i] <= 0:
                    cav[i] = 0.0
                    Hi = 0.5 * (Cp + Cm)
                    Qi = (Cp - Cm) / (2.0 * B)
                else:
                    vapour_anywhere = True
                    Qi = 0.5 * (Qup + Qdn)
            else:
                Qi = (Cp - Cm) / (2.0 * B)
            Hn[i], Qn[i] = Hi, Qi

        # -- downstream: constant-head reservoir --
        Cp_end = H[n - 1] + Q[n - 1] * (B - R * abs(Q[n - 1]))
        Hn[n] = reservoir_level_m
        Qn[n] = (Cp_end - Hn[n]) / B

        # -- pump rundown (explicit, from previous operating point) --
        if not check_valve_shut and w > 1e-4:
            H_p = pump.head(Q[0], w)
            P_hyd = rho * G * max(Q[0], 0.0) * max(H_p, 0.0)
            torque = P_hyd / (pump.rated_efficiency * w * pump.omega0)
            w = max(w - torque / pump.total_inertia_kgm2 * dt / pump.omega0, 0.0)

        # -- upstream boundary --
        Cm0 = H[1] - Q[1] * (B - R * abs(Q[1]))
        if air_vessel is not None:
            for _ in range(12):
                Hgas_abs = gas_C / max(Vg, 1e-9) ** air_vessel.polytropic_n
                H0 = Hgas_abs - ATM_HEAD_M + z[0]
                Q_pipe = (H0 - Cm0) / B
                Q_pump = 0.0 if check_valve_shut else pump.flow_for_head(H0 - sump_level_m, w)
                Vg_new = Vg - (Q_pump - Q_pipe) * dt
                Vg_new = max(Vg_new, 1e-6)
                if abs(Vg_new - Vg) < 1e-10:
                    Vg = Vg_new
                    break
                Vg = Vg_new
            if not check_valve_shut and Q_pump <= 0.0:
                check_valve_shut = True
            Hn[0] = H0
            Qn[0] = (H0 - Cm0) / B
        elif check_valve_shut:
            Qn[0] = 0.0
            Hn[0] = Cm0
        else:
            Q_up = _solve_pump_flow(pump, w, Cm0, B, sump_level_m)
            if Q_up <= 0.0:
                check_valve_shut = True
                Qn[0] = 0.0
                Hn[0] = Cm0
            else:
                Qn[0] = Q_up
                Hn[0] = Cm0 + Q_up * B

        H, Q = Hn.copy(), Qn.copy()
        env_max = np.maximum(env_max, H)
        env_min = np.minimum(env_min, H)
        t[s] = s * dt
        hp[s], qp[s], wf[s], hmid[s], gasv[s] = H[0], Q[0], w, H[n // 2], Vg

    notes: list[str] = []
    if check_valve_shut:
        notes.append("check valve shut on flow reversal at the pump")
    if vapour_anywhere:
        notes.append("vapour column separation - cavity collapse can cause a "
                     "secondary spike; protection required")

    return TransientResult(
        time_s=t, head_pump_m=hp, flow_pump_m3s=qp, speed_frac=wf,
        head_midpoint_m=hmid, envelope_max_m=env_max, envelope_min_m=env_min,
        node_x_m=x, node_elevation_m=z, vapour_anywhere=vapour_anywhere,
        max_head_m=float(env_max.max()), min_head_m=float(env_min.min()),
        air_vessel_gas_volume_m3=(gasv if air_vessel is not None else None),
        notes=notes,
    )


def _solve_pump_flow(pump: PumpInertia, w: float, Cm: float, B: float, sump: float) -> float:
    """Solve  sump + w^2*Hr(Q/w) = Cm + Q*B  for Q >= 0."""
    if w <= 1e-4:
        return 0.0

    def f(q):
        return sump + pump.head(q, w) - (Cm + q * B)

    hi = max(pump.curve.max_flow() * w, 1e-3)
    flo, fhi = f(0.0), f(hi)
    if flo * fhi > 0:
        return 0.0 if flo < 0 else hi
    try:
        return float(brentq(f, 0.0, hi, maxiter=100))
    except ValueError:
        return 0.0
