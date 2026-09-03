"""Extended-period simulation of a pumping station following a demand pattern.

A diurnal (or arbitrary-step) demand series draws down a delivery tank; a
staging controller runs 1..N identical pumps to keep the tank between its
control levels:

* ``mode="fixed"`` - lead/lag on staggered start & stop levels (fixed-speed
  pumps, so the tank cycles);
* ``mode="vfd"``   - all running pumps share one speed set to meet demand
  exactly; a pump is added when the required speed would exceed
  ``add_pump_at_speed`` and dropped below ``drop_pump_at_speed``.

Static head is recomputed each step from the tank level.  Outputs: per-step
time series plus daily energy, per-pump starts / run-hours, efficiency stats
and BEP-window compliance.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np

from .constants import G
from .motor import nominal_efficiency
from .operating import solve_operating_point, solve_parallel, solve_vfd_speed
from .pumpcurve import PumpCurve
from .system import SystemCurve

# a generic municipal diurnal demand shape (24 hourly multipliers, mean = 1.0)
DEFAULT_DIURNAL = [
    0.55, 0.48, 0.44, 0.43, 0.48, 0.62, 0.92, 1.28, 1.42, 1.22, 1.06, 1.00,
    0.98, 0.94, 0.90, 0.96, 1.12, 1.34, 1.30, 1.08, 0.88, 0.76, 0.66, 0.58,
]


@dataclass
class DemandPattern:
    multipliers: list[float]
    base_flow_m3s: float                 # flow that a multiplier of 1.0 represents
    step_hours: float = 1.0

    @classmethod
    def diurnal(cls, base_flow_m3s: float, *, kind: str = "average",
                multipliers: list[float] | None = None,
                step_hours: float = 1.0) -> "DemandPattern":
        m = list(multipliers if multipliers is not None else DEFAULT_DIURNAL)
        if kind == "peak":                # scale so the peak multiplier maps to base
            peak = max(m)
            m = [x / peak for x in m]
        else:                             # "average": normalise mean to 1.0
            avg = sum(m) / len(m)
            m = [x / avg for x in m]
        return cls(m, base_flow_m3s, step_hours)

    def demand(self, step: int) -> float:
        return self.multipliers[step % len(self.multipliers)] * self.base_flow_m3s


@dataclass
class Tank:
    plan_area_m2: float
    level_min_m: float
    level_max_m: float
    start_level_m: float | None = None    # lead pump starts here (default 20% up the band)
    stop_level_m: float | None = None     # lead pump stops here (default 90% up)
    initial_level_m: float | None = None

    def __post_init__(self):
        band = self.level_max_m - self.level_min_m
        if self.start_level_m is None:
            self.start_level_m = self.level_min_m + 0.20 * band
        if self.stop_level_m is None:
            self.stop_level_m = self.level_min_m + 0.90 * band
        if self.initial_level_m is None:
            self.initial_level_m = self.level_min_m + 0.60 * band


@dataclass
class StagingConfig:
    n_pumps_available: int
    mode: str = "vfd"                     # "fixed" | "vfd"
    vfd_min_speed: float = 0.65
    add_pump_at_speed: float = 0.99
    drop_pump_at_speed: float = 0.72
    max_starts_per_hour: float = 10.0
    bep_window: tuple[float, float] = (0.70, 1.20)
    sump_level_m: float = 0.0             # suction supply level (for static head)


@dataclass
class StagingStep:
    time_h: float
    demand_m3s: float
    tank_level_m: float
    running_pumps: int
    speed_ratio: float
    flow_delivered_m3s: float
    head_m: float
    flow_per_pump_m3s: float
    efficiency_pct: float
    shaft_power_kw: float
    input_power_kw: float


@dataclass
class StagingResult:
    steps: list[StagingStep]
    per_pump_starts: list[int]
    per_pump_run_hours: list[float]
    daily_energy_kwh: float
    daily_energy_cost: float
    efficiency_min_pct: float
    efficiency_mean_pct: float
    fraction_time_outside_bep: float
    max_starts_per_hour_seen: float
    standby_used: bool
    unmet_demand_steps: int
    warnings: list[str] = field(default_factory=list)

    # -- convenience arrays -------------------------------------------
    def array(self, name: str) -> np.ndarray:
        return np.array([getattr(s, name) for s in self.steps], dtype=float)

    def summary(self) -> dict:
        return {
            "mode_steps": len(self.steps),
            "daily_energy_kwh": round(self.daily_energy_kwh, 1),
            "daily_energy_cost": round(self.daily_energy_cost, 2),
            "efficiency_min_pct": round(self.efficiency_min_pct, 1),
            "efficiency_mean_pct": round(self.efficiency_mean_pct, 1),
            "fraction_time_outside_bep": round(self.fraction_time_outside_bep, 3),
            "per_pump_starts": self.per_pump_starts,
            "per_pump_run_hours": [round(x, 2) for x in self.per_pump_run_hours],
            "max_starts_per_hour_seen": round(self.max_starts_per_hour_seen, 2),
            "standby_used": self.standby_used,
            "unmet_demand_steps": self.unmet_demand_steps,
            "warnings": self.warnings,
        }


def _system_at_level(base: SystemCurve, tank_level_m: float, cfg: StagingConfig,
                     base_static_reference_level_m: float) -> SystemCurve:
    """Copy ``base`` with static head adjusted for the current tank level:
    static rises 1:1 with delivery-tank level above the reference."""
    delta = tank_level_m - base_static_reference_level_m
    return dataclasses.replace(base, static_head=base.static_head + delta,
                               label=f"{base.label}@{tank_level_m:.1f}m")


def simulate_staging(pump: PumpCurve, base_system: SystemCurve, tank: Tank,
                     demand: DemandPattern, cfg: StagingConfig, *,
                     rho: float = 1000.0, g: float = G, days: int = 1,
                     tariff_per_kwh: float = 0.0, motor_poles: int = 2,
                     motor_ie_class: str = "IE3",
                     base_static_reference_level_m: float | None = None
                     ) -> StagingResult:
    """Run ``days`` x one demand period.  ``base_system.static_head`` is taken to
    correspond to ``base_static_reference_level_m`` (default: tank stop level)."""
    ref = (base_static_reference_level_m if base_static_reference_level_m is not None
           else tank.stop_level_m)
    n_steps = len(demand.multipliers) * days
    dt_h = demand.step_hours
    dt_s = dt_h * 3600.0
    n_max = cfg.n_pumps_available

    # staggered control levels for fixed-speed lead/lag
    band = tank.stop_level_m - tank.start_level_m
    start_lv = [tank.start_level_m - k * 0.12 * band for k in range(n_max)]
    stop_lv = [tank.stop_level_m - k * 0.12 * band for k in range(n_max)]

    level = tank.initial_level_m
    running = 0
    starts = [0] * n_max
    run_hours = [0.0] * n_max
    lead = 0                                   # index of the current lead pump (rotates)
    steps: list[StagingStep] = []
    warnings: list[str] = []
    start_times: list[float] = []
    unmet = 0
    outside_bep = 0
    standby_used = False

    q_bep, _, _ = pump.bep()

    for k in range(n_steps):
        t_h = k * dt_h
        d = demand.demand(k)
        sysc = _system_at_level(base_system, level, cfg, ref)
        prev_running = running

        speed = 1.0
        if cfg.mode == "vfd":
            running = max(running, 1) if d > 1e-9 else 0
            # adjust pump count by the speed needed to meet demand
            for _ in range(n_max + 1):
                if running == 0:
                    speed, q_del, head, q_pp, eff = 0.0, 0.0, sysc.static_head, 0.0, np.nan
                    break
                op = solve_vfd_speed(pump, sysc, d, min_speed_ratio=cfg.vfd_min_speed,
                                     n_pumps=running, rho=rho, g=g)
                speed = op.speed_ratio
                if speed >= cfg.add_pump_at_speed and running < n_max and op.flow_m3s < d - 1e-6:
                    running += 1
                    continue
                if speed <= cfg.drop_pump_at_speed and running > 1:
                    running -= 1
                    continue
                q_del, head, q_pp, eff = op.flow_m3s, op.head_m, op.flow_per_pump_m3s, op.efficiency_pct
                break
            for j in range(prev_running, running):     # count VFD stage-ups as starts
                starts[(lead + j) % n_max] += 1
                start_times.append(t_h)
        else:  # fixed speed - lead/lag on tank level
            want = running
            if level <= start_lv[min(running, n_max - 1)] and running < n_max:
                want = running + 1
            elif running > 0 and level >= stop_lv[running - 1]:
                want = running - 1
            if want != running:
                if want > running:
                    starts[(lead + running) % n_max] += 1
                    start_times.append(t_h)
                running = want
            if running == 0:
                speed, q_del, head, q_pp, eff = 1.0, 0.0, sysc.static_head, 0.0, np.nan
            else:
                op = (solve_operating_point(pump, sysc, rho=rho, g=g) if running == 1
                      else solve_parallel(pump, sysc, running, rho=rho, g=g))
                q_del, head, q_pp, eff = op.flow_m3s, op.head_m, op.flow_per_pump_m3s, op.efficiency_pct

        # tank mass balance
        level += (q_del - d) * dt_s / tank.plan_area_m2
        if level < tank.level_min_m:
            level = tank.level_min_m
            if q_del < d - 1e-6:
                unmet += 1
        level = min(level, tank.level_max_m)

        # power
        if running > 0 and q_pp > 0:
            eff_frac = (eff / 100.0) if not np.isnan(eff) else 0.75
            p_shaft = rho * g * q_del * head / max(eff_frac, 1e-3) / 1000.0
            m_eff = nominal_efficiency(max(p_shaft / running, 0.12), poles=motor_poles,
                                       ie_class=motor_ie_class) / 100.0
            p_in = p_shaft / m_eff
            for j in range(running):
                run_hours[(lead + j) % n_max] += dt_h
        else:
            p_shaft = p_in = 0.0

        if running > 0 and not np.isnan(eff) and q_bep > 0:
            r = q_pp / q_bep
            if not (cfg.bep_window[0] <= r <= cfg.bep_window[1]):
                outside_bep += 1

        steps.append(StagingStep(
            time_h=t_h, demand_m3s=d, tank_level_m=level, running_pumps=running,
            speed_ratio=speed, flow_delivered_m3s=q_del, head_m=head,
            flow_per_pump_m3s=q_pp, efficiency_pct=eff,
            shaft_power_kw=p_shaft, input_power_kw=p_in))

        # rotate the lead pump once per period so run-hours balance
        if k > 0 and k % len(demand.multipliers) == 0:
            lead = (lead + 1) % n_max

    energy = sum(s.input_power_kw * dt_h for s in steps)
    effs = [s.efficiency_pct for s in steps if s.running_pumps > 0 and not np.isnan(s.efficiency_pct)]
    # max starts in any rolling 60-minute window
    max_sph = 0.0
    if start_times:
        st = np.array(start_times)
        max_sph = max(float(((st >= a) & (st < a + 1.0)).sum()) for a in st)
    n_duty_implied = max((s.running_pumps for s in steps), default=0)
    standby_used = n_duty_implied >= n_max and n_max > 1

    if unmet:
        warnings.append(f"{unmet} step(s) could not meet demand - station under-sized "
                        f"or tank too small")
    if max_sph > cfg.max_starts_per_hour:
        warnings.append(f"up to {max_sph:.0f} starts/hour (> limit {cfg.max_starts_per_hour:.0f}) "
                        f"- widen the tank control band or add storage")
    if effs and min(effs) < 55:
        warnings.append(f"minimum running efficiency {min(effs):.0f}% - staging drives "
                        f"a pump well off its curve")

    return StagingResult(
        steps=steps, per_pump_starts=starts, per_pump_run_hours=run_hours,
        daily_energy_kwh=energy / days, daily_energy_cost=energy / days * tariff_per_kwh,
        efficiency_min_pct=min(effs) if effs else float("nan"),
        efficiency_mean_pct=float(np.mean(effs)) if effs else float("nan"),
        fraction_time_outside_bep=outside_bep / max(len(steps), 1),
        max_starts_per_hour_seen=max_sph, standby_used=standby_used,
        unmet_demand_steps=unmet, warnings=warnings,
    )
