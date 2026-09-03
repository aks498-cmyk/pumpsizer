"""Project schema + orchestrator.

``Project.from_yaml("proj.yaml").run()`` returns :class:`ProjectResults` holding
the system-curve family, the pump curve, the operating point, the NPSH check,
the motor selection, energy figures and an EPANET export object.

The schema mirrors the ``Input`` sheet of the source workbook but is cleaner and
unit-explicit.  See ``examples/potable_water_pumping_station.yaml``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .constants import LPS_TO_M3S, G
from .energy import annual_energy_cost, annual_energy_kwh, life_cycle_cost
from .epanet import build_pump_export
from .fittings import FittingCatalog
from .fluid import water_properties
from .motor import non_overloading_shaft_power_kw, size_motor
from .npsh import npsh_available
from .operating import solve_operating_point, solve_parallel, solve_vfd_speed
from .pipes import PipeDatabase, PipeSegment, select_diameter
from .pumpcurve import PumpCurve
from .system import MinorLoss, SystemCurve, SystemCurveSet


def _get(d: dict, path: str, default=None):
    cur: Any = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur or cur[key] is None:
            return default
        cur = cur[key]
    return cur


@dataclass
class ProjectResults:
    project_name: str
    water: Any
    diameters_mm: dict[str, float]
    system_set: SystemCurveSet
    design_system_head_m: float
    duty_flow_per_pump_m3s: float
    duty_head_m: float
    pump: PumpCurve
    operating_point: Any
    operating_points_extra: dict[str, Any]
    npsh: Any
    motor: Any
    energy: dict
    epanet_export: Any
    selection: list[Any] | None = None
    surge: Any = None
    staging: Any = None
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "project": self.project_name,
            "water": {
                "temperature_c": self.water.temperature_c,
                "altitude_m": self.water.altitude_m,
                "kinematic_viscosity_m2s": self.water.kinematic_viscosity,
                "vapour_pressure_head_m": round(self.water.vapour_pressure_head, 3),
                "atmospheric_head_m": round(self.water.atmospheric_pressure_head, 3),
            },
            "diameters_mm": self.diameters_mm,
            "design_system_head_m": round(self.design_system_head_m, 3),
            "duty_flow_per_pump_lps": round(self.duty_flow_per_pump_m3s * 1000, 3),
            "duty_head_m": round(self.duty_head_m, 3),
            "pump_curve": self.pump.summary(),
            "operating_point": self.operating_point.as_dict(),
            "operating_points_extra": {k: v.as_dict() for k, v in self.operating_points_extra.items()},
            "npsh": self.npsh.as_dict(),
            "motor": self.motor.as_dict(),
            "energy": self.energy,
            "selection": [c.as_dict() for c in self.selection] if self.selection else None,
            "surge": self.surge.as_dict() if self.surge else None,
            "staging": self.staging.summary() if self.staging else None,
            "warnings": self.warnings,
        }


@dataclass
class Project:
    data: dict

    # ------------------------------------------------------------------
    @classmethod
    def from_yaml(cls, path: str | Path) -> Project:
        with open(path, encoding="utf-8") as fh:
            return cls(data=yaml.safe_load(fh))

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        return cls(data=d)

    def to_yaml(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.data, fh, sort_keys=False)

    # ------------------------------------------------------------------
    def run(self, pipe_db: PipeDatabase | None = None,
            fittings: FittingCatalog | None = None) -> ProjectResults:
        d = self.data
        warnings: list[str] = []
        pipe_db = pipe_db or PipeDatabase.default()
        fittings = fittings or FittingCatalog.default()

        # -- fluid ----------------------------------------------------
        water = water_properties(
            temp_c=_get(d, "fluid.temperature_c", 20.0),
            altitude_m=_get(d, "fluid.altitude_m", 0.0),
        )
        rho = water.density

        # -- flow ---------------------------------------------------
        q_total = float(_get(d, "flow.total_demand_lps", 0.0)) * LPS_TO_M3S
        n_duty = int(_get(d, "flow.duty_pumps", 1))
        arrangement = str(_get(d, "control.arrangement", "single")).lower()

        # -- pipe material -----------------------------------------
        material = _get(d, "pipe.material", "ductile_iron")
        series = _get(d, "pipe.series")
        rough_new = pipe_db.roughness_mm(material, "new")
        rough_used = pipe_db.roughness_mm(material, "used")
        hw_c = pipe_db.hazen_williams_c(material)
        method = str(_get(d, "pipe.headloss_method", "DW")).upper()

        # -- segments & diameters --------------------------------
        seg_specs = _get(d, "segments", []) or []
        v_suc = float(_get(d, "velocity_limits.suction_max_m_s", 1.0))
        v_dis = float(_get(d, "velocity_limits.discharge_max_m_s", 2.5))
        autosize = bool(_get(d, "autosize_diameter", False))

        diameters: dict[str, float] = {}
        seg_by_group: dict[str, list[PipeSegment]] = {"suction": [], "discharge": []}
        for spec in seg_specs:
            name = spec["name"]
            group = str(spec.get("group", "discharge")).lower()
            if spec.get("diameter_mm"):
                idmm = float(spec["diameter_mm"])
            elif spec.get("dn"):
                idmm = pipe_db.internal_diameter_mm(material, spec["dn"], series)
            elif autosize:
                vlim = v_suc if group == "suction" else v_dis
                choice = select_diameter(pipe_db, material, q_total, vlim, series)
                idmm = choice.internal_diameter_mm
                warnings.append(f"segment {name!r}: auto-sized to DN{int(choice.dn)} "
                                f"(ID {idmm:.1f} mm, v={choice.velocity_at_q:.2f} m/s)")
            else:
                raise ValueError(f"segment {name!r} needs 'dn' or 'diameter_mm' "
                                 f"(or set autosize_diameter: true)")
            diameters[name] = idmm
            seg_by_group.setdefault(group, []).append(
                PipeSegment(name=name, length_m=float(spec["length_m"]),
                            diameter_mm=idmm, roughness_mm=rough_new,
                            hazen_williams_c=hw_c))

        # -- fittings (reference bore per group) -----------------
        fit_ref = _get(d, "fitting_reference", {}) or {}
        minor_by_group: dict[str, list[MinorLoss]] = {"suction": [], "discharge": []}
        for group in ("suction", "discharge"):
            items = _get(d, f"fittings.{group}", {}) or {}
            if not items:
                continue
            ref_seg = fit_ref.get(group)
            ref_d = diameters.get(ref_seg)
            if ref_d is None:
                grp_segs = seg_by_group.get(group) or []
                ref_d = grp_segs[-1].diameter_mm if grp_segs else next(iter(diameters.values()))
            for fname, qty in items.items():
                minor_by_group[group].append(
                    MinorLoss(name=f"{group}:{fname}",
                              k_total=fittings.k(fname) * float(qty),
                              diameter_mm=ref_d))

        all_segments = seg_by_group["suction"] + seg_by_group["discharge"]
        all_minor = minor_by_group["suction"] + minor_by_group["discharge"]

        # -- static head family ---------------------------------
        lv = _get(d, "levels", {}) or {}
        if {"reservoir_hwl_m", "reservoir_bwl_m", "sump_hwl_m", "sump_bwl_m"} <= set(lv):
            h_static_max = lv["reservoir_hwl_m"] - lv["sump_bwl_m"]
            h_static_min = lv["reservoir_bwl_m"] - lv["sump_hwl_m"]
        else:
            h_static_max = float(_get(d, "suction.static_head_max_m",
                                      _get(d, "suction.static_head_m", 0.0)))
            h_static_min = float(_get(d, "suction.static_head_min_m", h_static_max))

        def make_curve(h_static: float, roughness_mm: float, label: str) -> SystemCurve:
            segs = [PipeSegment(s.name, s.length_m, s.diameter_mm, roughness_mm, s.hazen_williams_c)
                    for s in all_segments]
            return SystemCurve(static_head=h_static, segments=segs, minor_losses=all_minor,
                               kinematic_viscosity=water.kinematic_viscosity,
                               method=method, roughness_condition=label.split("/")[-1],
                               label=label)

        system_set = SystemCurveSet(
            max_static_new=make_curve(h_static_max, rough_new, "max_static/new"),
            max_static_used=make_curve(h_static_max, rough_used, "max_static/used"),
            min_static_new=make_curve(h_static_min, rough_new, "min_static/new"),
            min_static_used=make_curve(h_static_min, rough_used, "min_static/used"),
        )
        design_system = system_set.design()
        design_head = float(design_system.head(q_total))

        # -- duty point per pump -------------------------------
        duty_q_pp = float(_get(d, "pump.duty.flow_lps", q_total / max(n_duty, 1) / LPS_TO_M3S)) * LPS_TO_M3S \
            if _get(d, "pump.duty.flow_lps") else q_total / max(n_duty, 1)
        duty_h = _get(d, "pump.duty.head_m")
        duty_h = float(duty_h) if duty_h else design_head

        # -- pump curve --------------------------------------
        selection = None
        src = str(_get(d, "pump.source", "synthetic")).lower()
        if src in ("catalogue", "catalog"):
            pump, selection = self._select_from_catalogue(
                d, duty_q_pp, duty_h, design_system, warnings)
        else:
            pump = self._build_pump_curve(d, duty_q_pp, duty_h, warnings)

        # -- operating point --------------------------------
        vfd = bool(_get(d, "control.vfd", False))
        n_run = n_duty
        extra: dict[str, Any] = {}
        if vfd:
            target = _get(d, "control.vfd_target_flow_lps")
            target_m3s = float(target) * LPS_TO_M3S if target else q_total
            op = solve_vfd_speed(pump, design_system, target_m3s,
                                 min_speed_ratio=float(_get(d, "control.vfd_min_speed_pct", 70)) / 100.0,
                                 n_pumps=n_run, rho=rho, g=G)
        elif arrangement == "parallel" and n_run > 1:
            op = solve_parallel(pump, design_system, n_run, rho=rho, g=G)
            extra["single_pump"] = solve_operating_point(pump, design_system, rho=rho, g=G)
        elif arrangement == "series":
            stack = PumpCurve.series([pump] * max(n_run, 1))
            op = solve_operating_point(stack, design_system, rho=rho, g=G)
        else:
            op = solve_operating_point(pump, design_system, rho=rho, g=G)

        # operating point on the light (min static / new) curve, for the envelope
        try:
            extra["min_static_new"] = solve_operating_point(pump, system_set.min_static_new, rho=rho, g=G) \
                if arrangement != "parallel" or n_run == 1 else \
                solve_parallel(pump, system_set.min_static_new, n_run, rho=rho, g=G)
        except ValueError as exc:  # pragma: no cover - depends on data
            warnings.append(f"min-static operating point: {exc}")

        # -- NPSH -----------------------------------------
        npsh = self._npsh_check(d, water, system_set, minor_by_group, seg_by_group,
                                diameters, op, warnings)

        # -- motor --------------------------------------
        basis = str(_get(d, "motor.sizing_basis", "operating_point")).lower()
        if basis.startswith("non"):
            shaft_kw = non_overloading_shaft_power_kw(pump, rho=rho, g=G)
            basis_label = "non-overloading (max on curve)"
        else:
            shaft_kw = op.shaft_power_kw / op.n_pumps
            basis_label = "operating point (per pump)"
        motor = size_motor(shaft_kw,
                           margin_pct=float(_get(d, "motor.rating_margin_pct", 15.0)),
                           poles=int(_get(d, "motor.poles", 2)),
                           ie_class=str(_get(d, "motor.ie_class", "IE3")),
                           design_basis=basis_label)

        # -- energy -------------------------------------
        hours = float(_get(d, "energy.hours_per_day", 0.0))
        tariff = float(_get(d, "energy.tariff_per_kwh", 0.0))
        energy: dict = {}
        if hours > 0:
            kwh_per_pump = annual_energy_kwh(motor.input_electrical_kw, hours)
            kwh_total = kwh_per_pump * op.n_pumps
            cost = annual_energy_cost(
                kwh_total, tariff,
                demand_charge_per_kw_month=float(_get(d, "energy.demand_charge_per_kw_month", 0.0)),
                rated_kw=motor.rated_kw * op.n_pumps)
            energy = {
                "hours_per_day": hours,
                "running_pumps": op.n_pumps,
                "input_kw_per_pump": round(motor.input_electrical_kw, 3),
                "annual_energy_kwh": round(kwh_total, 0),
                "tariff_per_kwh": tariff,
                "annual_energy_cost": round(cost, 2),
            }
            if _get(d, "energy.life_cycle_years"):
                energy["life_cycle_cost"] = life_cycle_cost(
                    float(_get(d, "energy.capital_cost", 0.0)), cost,
                    years=int(_get(d, "energy.life_cycle_years", 20)),
                    discount_rate=float(_get(d, "energy.discount_rate", 0.08)))

        # -- water hammer (rule-of-thumb pre-sizing) -----------
        surge = None
        wh = _get(d, "water_hammer", {}) or {}
        if wh.get("enabled", False):
            surge = self._surge_assessment(
                d, wh, pipe_db, material, series, seg_by_group, diameters,
                h_static_max, op, motor, rho, water, warnings)

        # -- demand-pattern multi-pump staging -----------------
        staging = None
        stg = _get(d, "staging", {}) or {}
        if stg.get("enabled", False):
            staging = self._run_staging(d, stg, pump, design_system, system_set,
                                        q_total, n_duty, lv, tariff, water, warnings)

        # -- EPANET export --------------------------
        ep = _get(d, "epanet", {}) or {}
        export = build_pump_export(
            pump, pump_id=ep.get("pump_id", "PMP1"),
            from_node=ep.get("from_node", "SUC"), to_node=ep.get("to_node", "DIS"),
            curve_id=ep.get("curve_id"),
            flow_units=ep.get("flow_units", "LPS"),
            head_points=int(ep.get("head_points", 3)),
            efficiency_points=int(ep.get("efficiency_points", 7)),
            speed=op.speed_ratio if vfd else 1.0,
            price_per_kwh=tariff or None,
        )

        return ProjectResults(
            project_name=_get(d, "project.name", "unnamed project"),
            water=water, diameters_mm={k: round(v, 2) for k, v in diameters.items()},
            system_set=system_set, design_system_head_m=design_head,
            duty_flow_per_pump_m3s=duty_q_pp, duty_head_m=duty_h,
            pump=pump, operating_point=op, operating_points_extra=extra,
            npsh=npsh, motor=motor, energy=energy, epanet_export=export,
            selection=selection, surge=surge, staging=staging, warnings=warnings,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _run_staging(d, stg, pump, design_system, system_set, q_total, n_duty,
                     lv, tariff, water, warnings):
        from .staging import DemandPattern, StagingConfig, Tank, simulate_staging

        n_avail = int(stg.get("n_pumps_available",
                              n_duty + int(_get(d, "flow.standby_pumps", 1))))
        base_lps = float(stg.get("pattern_base_lps", q_total * 1000.0))
        dp = DemandPattern.diurnal(
            base_flow_m3s=base_lps / 1000.0,
            kind=str(stg.get("pattern_kind", "peak")),
            multipliers=stg.get("demand_pattern"),
            step_hours=float(stg.get("pattern_step_hours", 1.0)))

        tcfg = stg.get("tank", {}) or {}
        level_min = float(tcfg.get("level_min_m", lv.get("reservoir_bwl_m", 0.0)))
        level_max = float(tcfg.get("level_max_m", lv.get("reservoir_hwl_m", level_min + 5.0)))
        tank = Tank(
            plan_area_m2=float(tcfg.get("plan_area_m2", 300.0)),
            level_min_m=level_min, level_max_m=level_max,
            start_level_m=tcfg.get("start_level_m"), stop_level_m=tcfg.get("stop_level_m"),
            initial_level_m=tcfg.get("initial_level_m"))
        if "plan_area_m2" not in tcfg:
            warnings.append("staging.tank.plan_area_m2 not given; assumed 300 m2")

        cfg = StagingConfig(
            n_pumps_available=n_avail, mode=str(stg.get("mode", "vfd")).lower(),
            vfd_min_speed=float(stg.get("vfd_min_speed_pct", 65)) / 100.0,
            max_starts_per_hour=float(stg.get("max_starts_per_hour", 10)),
            sump_level_m=float(lv.get("sump_bwl_m", 0.0)))

        # design_system static head corresponds to the reservoir HWL
        ref_level = float(lv.get("reservoir_hwl_m", level_max))
        return simulate_staging(
            pump, design_system, tank, dp, cfg,
            rho=water.density, days=int(stg.get("days", 1)),
            tariff_per_kwh=tariff, motor_poles=int(_get(d, "motor.poles", 2)),
            motor_ie_class=str(_get(d, "motor.ie_class", "IE3")),
            base_static_reference_level_m=ref_level)

    # ------------------------------------------------------------------
    @staticmethod
    def _surge_assessment(d, wh, pipe_db, material, series, seg_by_group,
                          diameters, h_static_max, op, motor, rho, water, warnings):
        from . import surge as _surge

        disch = seg_by_group.get("discharge") or []
        if not disch:
            warnings.append("water_hammer: no discharge segment to assess")
            return None
        rm = max(disch, key=lambda s: s.length_m)          # the rising main
        length = float(wh.get("length_m", rm.length_m))
        d_m = rm.diameter_mm / 1000.0
        e_mm = pipe_db.wall_thickness_from_id_mm(material, rm.diameter_mm, series)
        E_pa = pipe_db.youngs_modulus_gpa(material) * 1e9
        v = op.flow_per_pump_m3s * op.n_pumps / (math.pi * d_m ** 2 / 4.0)

        pn = wh.get("pipe_rating_head_m")
        if pn is None and wh.get("pressure_class_pn"):
            pn = float(wh["pressure_class_pn"]) * 10.2
        elif pn is None and _get(d, "pipe.pressure_class_pn"):
            pn = float(_get(d, "pipe.pressure_class_pn")) * 10.2

        poles = int(_get(d, "motor.poles", 2))
        rpm = {2: 2900.0, 4: 1450.0, 6: 960.0, 8: 725.0}.get(poles, 1450.0)

        result = _surge.assess(
            length_m=length, diameter_m=d_m, wall_thickness_m=e_mm / 1000.0,
            youngs_modulus_pa=E_pa, steady_velocity_m_s=v,
            static_head_m=float(h_static_max), rho=rho,
            closure_time_s=wh.get("closure_time_s"),
            pipe_rating_head_m=pn, restraint=float(wh.get("restraint", 1.0)),
            shaft_power_kw=motor.shaft_power_kw, speed_rpm=rpm,
            allowable_max_head_m=wh.get("allowable_max_head_m"),
            allowable_min_head_m=float(wh.get("allowable_min_head_m", 0.0)),
        )

        if str(wh.get("method", "rule_of_thumb")).lower() == "moc":
            from . import transient as _tr
            lv = _get(d, "levels", {}) or {}
            pump_el = float(lv.get("sump_bwl_m", 0.0))
            res_el = pump_el + float(h_static_max)
            inertia = wh.get("pump_motor_inertia_kgm2")
            if inertia is None:
                inertia = 0.03 * motor.shaft_power_kw * (1000.0 / rpm) ** 2
                warnings.append(f"water_hammer.moc: pump+motor inertia not given; "
                                f"estimated {inertia:.1f} kg.m2")
            pipe_obj = _tr.Pipeline.from_pipe(
                length_m=length, diameter_mm=rm.diameter_mm, wall_thickness_mm=e_mm,
                youngs_modulus_pa=E_pa, friction_factor=0.017,
                pump_elevation_m=pump_el, reservoir_elevation_m=res_el,
                reaches=int(wh.get("moc_reaches", 24)), rho=rho)
            pump_obj = _tr.PumpInertia(
                rated_speed_rpm=rpm, rated_flow_m3s=op.flow_per_pump_m3s,
                rated_head_m=op.head_m, total_inertia_kgm2=float(inertia),
                rated_efficiency=max((op.efficiency_pct or 80.0) / 100.0, 0.4))
            av = None
            if wh.get("air_vessel_gas_volume_m3"):
                av = _tr.AirVessel(gas_volume_m3=float(wh["air_vessel_gas_volume_m3"]),
                                   polytropic_n=float(wh.get("polytropic_n", 1.2)))
            tr = _tr.simulate_pump_trip(
                pipe_obj, pump_obj, sump_level_m=pump_el, reservoir_level_m=res_el,
                rho=rho, air_vessel=av,
                vapour_head_m=water.vapour_pressure_head)
            result.transient = tr.as_dict()
            if pn is not None:
                result.transient["exceeds_rating"] = tr.max_head_m > pn

        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _select_from_catalogue(d, duty_q, duty_h, design_system, warnings):
        from .catalog import Catalog
        from .selection import SelectionCriteria, select

        cat_path = _get(d, "pump.catalogue_path")
        cat = Catalog.from_path(cat_path) if cat_path else Catalog.bundled()
        if cat_path is None:
            warnings.append("pump.source=catalogue but no catalogue_path given; "
                            "using the bundled ILLUSTRATIVE catalogue")
        sel = _get(d, "pump.selection", {}) or {}
        crit = SelectionCriteria(
            duty_flow_m3s=duty_q, duty_head_m=duty_h,
            system_curve=design_system,
            npsh_available_m=_get(d, "pump.selection.npsh_available_m"),
            allow_trim=bool(sel.get("allow_trim", True)),
            allow_vfd=bool(sel.get("allow_vfd", True)),
        )
        ranked = select(cat, crit, include_infeasible=True)
        feasible = [c for c in ranked if c.feasible]
        if not feasible:
            raise ValueError("no catalogue pump can meet the duty "
                             f"{duty_q*1000:.0f} l/s @ {duty_h:.1f} m")
        pick_name = _get(d, "pump.model")
        chosen = next((c for c in feasible if pick_name and pick_name.lower() in c.model.key.lower()),
                      feasible[0])
        curve = chosen.model.to_pump_curve(speed_ratio=chosen.speed_ratio,
                                           diameter_ratio=chosen.trim_ratio)
        curve.design_q_m3s = duty_q
        warnings.append(f"selected {chosen.model.key} ({chosen.method}, "
                        f"score {chosen.score:.2f}); {len(feasible)} feasible of {len(cat)}")
        if not chosen.model.verified:
            warnings.append(f"{chosen.model.key} curve is NOT verified against a datasheet")
        return curve, ranked

    # ------------------------------------------------------------------
    @staticmethod
    def _build_pump_curve(d: dict, duty_q: float, duty_h: float,
                          warnings: list[str]) -> PumpCurve:
        src = str(_get(d, "pump.source", "synthetic")).lower()
        name = _get(d, "pump.name", "pump")
        if src == "points":
            q = np.asarray(_get(d, "pump.curve_points.flow_lps"), dtype=float) * LPS_TO_M3S
            h = np.asarray(_get(d, "pump.curve_points.head_m"), dtype=float)
            eff = _get(d, "pump.efficiency_points.value_pct")
            eff_q = _get(d, "pump.efficiency_points.flow_lps")
            npr = _get(d, "pump.npshr_points.value_m")
            npr_q = _get(d, "pump.npshr_points.flow_lps")
            return PumpCurve.from_points(
                q, h,
                eff=np.asarray(eff, float) if eff else None,
                eff_q=np.asarray(eff_q, float) * LPS_TO_M3S if eff_q else None,
                npshr=np.asarray(npr, float) if npr else None,
                npshr_q=np.asarray(npr_q, float) * LPS_TO_M3S if npr_q else None,
                name=name, prefer=_get(d, "pump.fit", "auto"))
        if src in ("single_point", "single-point", "duty"):
            return PumpCurve.from_single_point(
                duty_q, duty_h,
                shutoff_ratio=float(_get(d, "pump.shutoff_ratio", 1.33)),
                runout_flow_ratio=float(_get(d, "pump.runout_flow_ratio", 2.0)),
                name=name)
        if src != "synthetic":
            warnings.append(f"unknown pump.source {src!r}; using synthetic curve")
        return PumpCurve.synthetic(
            duty_q, duty_h,
            shutoff_ratio=float(_get(d, "pump.shutoff_ratio", 1.20)),
            eff_bep=float(_get(d, "pump.bep_efficiency_pct", 82.0)),
            name=name)

    # ------------------------------------------------------------------
    @staticmethod
    def _npsh_check(d, water, system_set, minor_by_group, seg_by_group, diameters,
                    op, warnings):
        lv = _get(d, "levels", {}) or {}
        centreline = _get(d, "levels.pump_centreline_m")
        static_suction = _get(d, "suction.static_suction_head_m")
        if static_suction is None:
            if "sump_bwl_m" in lv and centreline is not None:
                static_suction = float(lv["sump_bwl_m"]) - float(centreline)
            elif "sump_bwl_m" in lv:
                static_suction = 0.0
                warnings.append("levels.pump_centreline_m not given; assuming pump at "
                                "sump BWL (static suction head = 0 m)")
            else:
                static_suction = 0.0
                warnings.append("no suction level data; static suction head = 0 m")

        q = op.flow_m3s
        suc = SystemCurve(static_head=0.0, segments=seg_by_group.get("suction", []),
                          minor_losses=minor_by_group.get("suction", []),
                          kinematic_viscosity=water.kinematic_viscosity,
                          method=system_set.design().method, label="suction")
        h_fric = suc.friction_loss(q)
        h_minor = suc.minor_loss(q)
        ref_d = None
        fit_ref = _get(d, "fitting_reference.suction")
        ref_d = diameters.get(fit_ref) or (seg_by_group["suction"][-1].diameter_mm
                                           if seg_by_group.get("suction") else None)
        v_head = 0.0
        if ref_d:
            v = 4.0 * q / (np.pi * (ref_d / 1000.0) ** 2)
            v_head = v * v / (2.0 * G)

        npshr = _get(d, "pump.npsh_required_m")
        if npshr is None and getattr(op, "npshr_m", None) is not None and not np.isnan(op.npshr_m):
            npshr = float(op.npshr_m)

        return npsh_available(
            atmospheric_head_m=float(_get(d, "suction.atmospheric_head_m",
                                          water.atmospheric_pressure_head)),
            static_suction_head_m=float(static_suction),
            suction_friction_loss_m=h_fric,
            suction_minor_loss_m=h_minor,
            suction_velocity_head_m=v_head,
            vapour_pressure_head_m=(0.0 if _get(d, "suction.ignore_vapour_pressure", False)
                                    else water.vapour_pressure_head),
            safety_margin_m=float(_get(d, "suction.npsh_safety_margin_m", 0.0)),
            npsh_required_m=float(npshr) if npshr is not None else None,
        )
