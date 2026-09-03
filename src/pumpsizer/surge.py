"""Water-hammer (hydraulic transient) PRE-SIZING.

Rule-of-thumb / energy-balance estimates only - enough to decide whether a
pumping main needs surge protection and to size an air vessel or flywheel to
+/- a factor of ~2 for a budget and layout.  A detailed method-of-
characteristics transient analysis is still required for final design
(KSB "Water Hammer", secs. 5-7).

References: Joukowsky; Michaud/Allievi slow-closure bound; KSB "Water Hammer"
sec. 8 (energy storage).  All SI: m, s, m/s, m3, Pa unless noted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .constants import G

WATER_BULK_MODULUS = 2.19e9      # Pa, ~20 degC
ATM_HEAD_M = 10.33               # atmospheric pressure as head of water


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------
def wave_celerity(diameter_m: float, wall_thickness_m: float,
                  youngs_modulus_pa: float, *, rho: float = 1000.0,
                  bulk_modulus_pa: float = WATER_BULK_MODULUS,
                  restraint: float = 1.0) -> float:
    """Pressure-wave speed a [m/s] in a thin-walled liquid-filled pipe:

        a = sqrt( (K/rho) / (1 + (K/E)*(D/e)*c) )

    ``restraint`` c ~ 1 for a thin-walled pipe with expansion joints; use
    (1 - nu^2) ~ 0.91 for a pipe anchored against axial movement throughout.
    For a very rigid pipe (E -> inf) a -> sqrt(K/rho) ~ 1480 m/s.
    """
    if wall_thickness_m <= 0 or youngs_modulus_pa <= 0:
        return math.sqrt(bulk_modulus_pa / rho)
    denom = 1.0 + (bulk_modulus_pa / youngs_modulus_pa) * (diameter_m / wall_thickness_m) * restraint
    return math.sqrt((bulk_modulus_pa / rho) / denom)


def pipe_period(length_m: float, celerity_m_s: float) -> float:
    """Critical time / pipe period  Tc = 2 L / a  [s].  A flow change completed
    within Tc produces the full Joukowsky surge at the origin."""
    return 2.0 * length_m / celerity_m_s if celerity_m_s > 0 else math.inf


def joukowsky_head(celerity_m_s: float, delta_velocity_m_s: float,
                   g: float = G) -> float:
    """Head rise (or drop) for a rapid velocity change |dv|:  dh = a*dv/g  [m]."""
    return celerity_m_s * abs(delta_velocity_m_s) / g


def slow_closure_head(length_m: float, velocity_m_s: float, closure_time_s: float,
                      g: float = G) -> float:
    """Michaud/Allievi upper bound for a uniform valve closure slower than the
    pipe period:  dh ~ 2 L v / (g T).  Use only when ``closure_time_s`` > Tc."""
    if closure_time_s <= 0:
        return math.inf
    return 2.0 * length_m * abs(velocity_m_s) / (g * closure_time_s)


def surge_head(length_m: float, velocity_m_s: float, celerity_m_s: float, *,
               closure_time_s: float | None = None, g: float = G) -> tuple[float, str]:
    """Best rule-of-thumb surge head [m] and which rule was used.
    Rapid (or unspecified) closure -> Joukowsky.  Slow closure -> the lesser of
    Joukowsky and the Michaud bound."""
    jouk = joukowsky_head(celerity_m_s, velocity_m_s, g)
    tc = pipe_period(length_m, celerity_m_s)
    if closure_time_s is None:
        return jouk, f"Joukowsky (closure time unspecified -> assume rapid; Tc={tc:.2f}s)"
    if closure_time_s <= tc:
        return jouk, f"Joukowsky (rapid: T_close={closure_time_s:.1f}s <= Tc={tc:.2f}s)"
    michaud = slow_closure_head(length_m, velocity_m_s, closure_time_s, g)
    return (michaud, f"Michaud slow-closure (T_close={closure_time_s:.1f}s > Tc={tc:.2f}s)") \
        if michaud < jouk else (jouk, "Joukowsky (Michaud bound not lower)")


# ---------------------------------------------------------------------------
# protection pre-sizing
# ---------------------------------------------------------------------------
def air_vessel_prelim(*, pipe_area_m2: float, length_m: float, velocity_m_s: float,
                      static_head_m: float, allowable_max_head_m: float,
                      allowable_min_head_m: float, rho: float = 1000.0,
                      g: float = G, gas_law_n: float = 1.2,
                      normal_gas_fraction: float = 0.5) -> dict:
    """Preliminary air-vessel (hydro-pneumatic tank) size by an energy balance:
    the kinetic energy of the water column is absorbed by compressing the gas
    cushion within the allowable pressure rise.

        KE = 1/2 * rho * (A L) * v^2
        W_gas = p0 Vg0 / (n-1) * [ (p0/pmax)^((n-1)/n) - 1 ]  (polytropic)  ~ p0 Vg0 ln(pmax/p0)

    Returns the minimum normal gas volume, the expanded gas volume at the
    down-surge, and a suggested gross vessel volume.  Order-of-magnitude only.
    """
    ke = 0.5 * rho * pipe_area_m2 * length_m * velocity_m_s ** 2
    p_atm = ATM_HEAD_M * rho * g
    p0 = (static_head_m + ATM_HEAD_M) * rho * g            # absolute, normal
    pmax = (allowable_max_head_m + ATM_HEAD_M) * rho * g
    pmin = max((allowable_min_head_m + ATM_HEAD_M) * rho * g, 0.05 * p_atm)

    # isothermal work per unit initial gas volume between p0 and pmax
    w_per_vol = p0 * math.log(pmax / p0) if pmax > p0 else math.inf
    vg0 = ke / w_per_vol if math.isfinite(w_per_vol) and w_per_vol > 0 else math.inf

    # down-surge: gas expands (polytropic) from p0,Vg0 to pmin
    vg_max = vg0 * (p0 / pmin) ** (1.0 / gas_law_n)
    gross = vg_max / max(normal_gas_fraction, 0.1)          # keep some liquid seal

    return {
        "column_kinetic_energy_J": round(ke, 1),
        "p0_abs_bar": round(p0 / 1e5, 3),
        "pmax_abs_bar": round(pmax / 1e5, 3),
        "pmin_abs_bar": round(pmin / 1e5, 3),
        "min_normal_gas_volume_m3": round(vg0, 3) if math.isfinite(vg0) else None,
        "expanded_gas_volume_m3": round(vg_max, 3) if math.isfinite(vg_max) else None,
        "suggested_gross_vessel_m3": round(gross, 3) if math.isfinite(gross) else None,
        "assumptions": "isothermal compression for sizing, polytropic n="
                       f"{gas_law_n} for expansion, normal gas fraction "
                       f"{normal_gas_fraction:.0%}; confirm with a transient model",
    }


def flywheel_prelim(*, shaft_power_kw: float, speed_rpm: float,
                    target_stop_time_s: float, pump_motor_inertia_kgm2: float | None = None,
                    radius_of_gyration_m: float = 0.3, efficiency: float = 0.75) -> dict:
    """Additional flywheel inertia so the pump run-down time reaches
    ``target_stop_time_s`` (commonly >= the pipe period 2L/a).

        E_rot = 1/2 I omega0^2      P_shaft ~ hydraulic power / eff
        stop_time ~ E_rot / P_shaft   ->   I_req = 2 P_shaft t_stop / omega0^2

    ``pump_motor_inertia_kgm2`` defaults to a rough correlation
    I_pm ~ 0.03 * P_kW * (1000/n)^2 (state it explicitly for real work).
    """
    omega0 = 2.0 * math.pi * speed_rpm / 60.0
    p_shaft = shaft_power_kw * 1000.0
    i_total_req = 2.0 * p_shaft * target_stop_time_s / omega0 ** 2 if omega0 > 0 else math.inf
    i_pm = pump_motor_inertia_kgm2
    if i_pm is None:
        i_pm = 0.03 * shaft_power_kw * (1000.0 / max(speed_rpm, 1.0)) ** 2
    i_flywheel = max(i_total_req - i_pm, 0.0)
    m_flywheel = i_flywheel / radius_of_gyration_m ** 2 if radius_of_gyration_m > 0 else math.inf
    return {
        "omega0_rad_s": round(omega0, 2),
        "required_total_inertia_kgm2": round(i_total_req, 2),
        "assumed_pump_motor_inertia_kgm2": round(i_pm, 2),
        "additional_flywheel_inertia_kgm2": round(i_flywheel, 2),
        "flywheel_mass_kg": round(m_flywheel, 1) if math.isfinite(m_flywheel) else None,
        "radius_of_gyration_m": radius_of_gyration_m,
        "note": "energy/power estimate of run-down time; a flywheel is only "
                "practical up to ~a few hundred kg*m2 and modest pipe lengths",
    }


# ---------------------------------------------------------------------------
# assessment bundle
# ---------------------------------------------------------------------------
@dataclass
class SurgeAssessment:
    length_m: float
    diameter_m: float
    wall_thickness_mm: float
    celerity_m_s: float
    pipe_period_s: float
    steady_velocity_m_s: float
    static_head_m: float
    surge_head_m: float
    surge_rule: str
    max_head_m: float
    min_head_m: float
    column_separation_risk: bool
    exceeds_rating: bool | None
    pipe_rating_head_m: float | None
    protection_needed: bool
    recommendations: list[str] = field(default_factory=list)
    air_vessel: dict | None = None
    flywheel: dict | None = None

    def as_dict(self) -> dict:
        d = {k: (round(v, 3) if isinstance(v, float) else v)
             for k, v in self.__dict__.items()}
        return d


def assess(*, length_m: float, diameter_m: float, wall_thickness_m: float,
           youngs_modulus_pa: float, steady_velocity_m_s: float,
           static_head_m: float, rho: float = 1000.0,
           closure_time_s: float | None = None,
           pipe_rating_head_m: float | None = None,
           restraint: float = 1.0,
           shaft_power_kw: float | None = None, speed_rpm: float = 1480.0,
           allowable_max_head_m: float | None = None,
           allowable_min_head_m: float = 0.0) -> SurgeAssessment:
    """Full rule-of-thumb assessment for one pumping main + protection pre-size."""
    a = wave_celerity(diameter_m, wall_thickness_m, youngs_modulus_pa, rho=rho,
                      restraint=restraint)
    tc = pipe_period(length_m, a)
    dh, rule = surge_head(length_m, steady_velocity_m_s, a,
                          closure_time_s=closure_time_s)
    h_max = static_head_m + dh
    h_min = static_head_m - dh
    sep_risk = h_min <= -ATM_HEAD_M + 0.5           # near full vacuum -> vapour column
    exceeds = None if pipe_rating_head_m is None else h_max > pipe_rating_head_m
    needs = bool(sep_risk or exceeds)

    recs: list[str] = []
    if sep_risk:
        recs.append("down-surge approaches vapour pressure - column separation "
                    "likely; provide an air vessel, one-way surge tank or air valves")
    if exceeds:
        recs.append(f"up-surge {h_max:.1f} m exceeds pipe rating "
                    f"{pipe_rating_head_m:.1f} m - protection or a higher class needed")
    if not needs:
        recs.append("rule-of-thumb surge within limits; a transient check is still "
                    "advised for pipelines over ~a few hundred metres")

    area = math.pi * diameter_m ** 2 / 4.0
    av = None
    if allowable_max_head_m is None and pipe_rating_head_m is not None:
        allowable_max_head_m = pipe_rating_head_m
    if needs and allowable_max_head_m is not None:
        av = air_vessel_prelim(
            pipe_area_m2=area, length_m=length_m, velocity_m_s=steady_velocity_m_s,
            static_head_m=static_head_m, allowable_max_head_m=allowable_max_head_m,
            allowable_min_head_m=max(allowable_min_head_m, 2.0), rho=rho)
    fw = None
    if needs and shaft_power_kw:
        fw = flywheel_prelim(shaft_power_kw=shaft_power_kw, speed_rpm=speed_rpm,
                             target_stop_time_s=max(tc, 1.0))

    return SurgeAssessment(
        length_m=length_m, diameter_m=diameter_m,
        wall_thickness_mm=wall_thickness_m * 1000.0,
        celerity_m_s=a, pipe_period_s=tc,
        steady_velocity_m_s=steady_velocity_m_s, static_head_m=static_head_m,
        surge_head_m=dh, surge_rule=rule, max_head_m=h_max, min_head_m=h_min,
        column_separation_risk=sep_risk, exceeds_rating=exceeds,
        pipe_rating_head_m=pipe_rating_head_m, protection_needed=needs,
        recommendations=recs, air_vessel=av, flywheel=fw,
    )
