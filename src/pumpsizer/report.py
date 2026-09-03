"""Human-readable report + optional performance plot for a ProjectResults."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .project import ProjectResults


def _row(label: str, value, unit: str = "") -> str:
    return f"  {label:<38} {value:>14}  {unit}"


def text_report(res: ProjectResults) -> str:
    op = res.operating_point
    w = res.water
    L: list[str] = []
    L.append("=" * 74)
    L.append(f" PUMP SIZING REPORT  -  {res.project_name}")
    L.append("=" * 74)

    L.append("\n-- Fluid & site --------------------------------------------------------")
    L.append(_row("Temperature", f"{w.temperature_c:g}", "degC"))
    L.append(_row("Site altitude", f"{w.altitude_m:g}", "m"))
    L.append(_row("Kinematic viscosity", f"{w.kinematic_viscosity*1e6:.4f}", "e-6 m2/s"))
    L.append(_row("Atmospheric pressure head", f"{w.atmospheric_pressure_head:.2f}", "m"))
    L.append(_row("Vapour pressure head", f"{w.vapour_pressure_head:.3f}", "m"))

    L.append("\n-- Pipe diameters (internal) ----------------------------------------")
    for name, dmm in res.diameters_mm.items():
        L.append(_row(name, f"{dmm:.1f}", "mm"))

    L.append("\n-- System head --------------------------------------------------------")
    q_design = res.duty_flow_per_pump_m3s * op.n_pumps
    for label, sc in res.system_set.as_dict().items():
        L.append(_row(f"H_sys @ {q_design*1000:.0f} l/s  [{label}]",
                      f"{sc.head(q_design):.2f}", "m"))
    L.append(_row("Design system head (max static/used)", f"{res.design_system_head_m:.2f}", "m"))
    L.append(_row("Design duty (per pump)",
                  f"{res.duty_flow_per_pump_m3s*1000:.1f} l/s @ {res.duty_head_m:.2f} m", ""))

    if res.selection:
        L.append("\n-- Pump selection (ranked) --------------------------------------")
        L.append(f"  {'#':>2}  {'pump':<26}{'method':<9}{'eff%':>6}{'Q/BEP':>7}"
                 f"{'NPSHmgn':>9}{'score':>7}  notes")
        for i, c in enumerate(res.selection[:8], 1):
            if not c.feasible:
                L.append(f"  {i:>2}  {c.model.key:<26}{'--':<9}{'':>6}{'':>7}{'':>9}"
                         f"{'x':>7}  {'; '.join(c.reasons)[:40]}")
                continue
            nm = "-" if c.npsh_margin_m is None else f"{c.npsh_margin_m:.1f}"
            ef = "-" if (c.efficiency_pct != c.efficiency_pct) else f"{c.efficiency_pct:.0f}"
            L.append(f"  {i:>2}  {c.model.key:<26}{c.method:<9}{ef:>6}"
                     f"{c.bep_ratio:>7.2f}{nm:>9}{c.score:>7.2f}  "
                     f"{'; '.join(c.reasons)[:42]}")
        L.append(f"  -> using: {res.pump.name}")

    L.append("\n-- Pump curve -------------------------------------------------------")
    ps = res.pump.summary()
    L.append(_row("Curve model", ps["model"], f"(fit RMS {ps['fit_rms_m']} m)"))
    if ps["abc"]:
        a, b, c = ps["abc"]
        L.append(_row("H = A - B*Q^C  (Q in m3/s)", f"A={a:.2f} B={b:.3g} C={c:.3f}", ""))
    L.append(_row("Shut-off head", f"{ps['shutoff_head_m']:.2f}", "m"))
    L.append(_row("Runout flow (H=0)", f"{ps['max_flow_lps']:.1f}", "l/s"))
    L.append(_row("BEP", f"{ps['bep_flow_lps']:.1f} l/s @ {ps['bep_head_m']:.2f} m", ""))
    if ps["bep_efficiency_pct"] is not None:
        L.append(_row("BEP efficiency", f"{ps['bep_efficiency_pct']:.1f}", "%"))

    L.append("\n-- Operating point (design system curve) ---------------------------")
    L.append(_row("Running pumps", op.n_pumps, ""))
    L.append(_row("Total flow", f"{op.flow_lps:.1f}", "l/s"))
    L.append(_row("Flow per pump", f"{op.flow_per_pump_m3s*1000:.1f}", "l/s"))
    L.append(_row("Head", f"{op.head_m:.2f}", "m"))
    if not np.isnan(op.efficiency_pct):
        L.append(_row("Pump efficiency at duty", f"{op.efficiency_pct:.1f}", "%"))
    L.append(_row("Hydraulic power (total)", f"{op.hydraulic_power_kw:.1f}", "kW"))
    L.append(_row("Shaft power (total)", f"{op.shaft_power_kw:.1f}", "kW"))
    if op.speed_ratio != 1.0:
        L.append(_row("VFD speed", f"{op.speed_ratio*100:.1f}", "%"))
    if op.note:
        L.append(f"  note: {op.note}")
    for key, ep in res.operating_points_extra.items():
        L.append(_row(f"[{key}] flow / head",
                      f"{ep.flow_lps:.1f} l/s @ {ep.head_m:.2f} m", ""))

    L.append("\n-- NPSH -----------------------------------------------------------")
    n = res.npsh
    for k, v in n.terms.items():
        L.append(_row(k, f"{v:.3f}", "m"))
    L.append(_row("NPSH available", f"{n.npsh_available_m:.2f}", "m"))
    if n.npsh_required_m is not None:
        L.append(_row("NPSH required", f"{n.npsh_required_m:.2f}", "m"))
        L.append(_row("Margin", f"{n.margin_m:.2f}", f"m  ({'OK' if n.safe else 'NOT OK'})"))

    L.append("\n-- Motor --------------------------------------------------------")
    m = res.motor
    L.append(_row("Sizing basis", m.design_basis, ""))
    L.append(_row("Shaft power (one pump)", f"{m.shaft_power_kw:.1f}", "kW"))
    L.append(_row(f"+ margin {m.margin_pct:g}%", f"{m.required_kw:.1f}", "kW"))
    L.append(_row("Selected motor rating", f"{m.rated_kw:g}", f"kW  ({m.poles}-pole {m.ie_class})"))
    L.append(_row("Nominal motor efficiency", f"{m.motor_efficiency_pct:.1f}", "%"))
    L.append(_row("Electrical input (one pump)", f"{m.input_electrical_kw:.1f}", "kW"))

    if res.energy:
        L.append("\n-- Energy -------------------------------------------------------")
        for k, v in res.energy.items():
            if isinstance(v, dict):
                L.append(f"  {k}:")
                for kk, vv in v.items():
                    L.append(_row(f"  {kk}", vv, ""))
            else:
                L.append(_row(k, v, ""))

    if res.surge is not None:
        s = res.surge
        L.append("\n-- Water hammer (rule-of-thumb pre-sizing) --------------------")
        L.append(_row("Rising main assessed", f"{s.length_m:.0f} m x {s.diameter_m*1000:.0f} mm ID", ""))
        L.append(_row("Wall thickness (assumed)", f"{s.wall_thickness_mm:.1f}", "mm"))
        L.append(_row("Wave celerity a", f"{s.celerity_m_s:.0f}", "m/s"))
        L.append(_row("Pipe period  Tc = 2L/a", f"{s.pipe_period_s:.2f}", "s"))
        L.append(_row("Steady velocity", f"{s.steady_velocity_m_s:.2f}", "m/s"))
        L.append(_row("Surge head  +/-", f"{s.surge_head_m:.1f}", f"m   [{s.surge_rule}]"))
        L.append(_row("Max head at pump (static+surge)", f"{s.max_head_m:.1f}", "m"))
        L.append(_row("Min head at pump (static-surge)", f"{s.min_head_m:.1f}", "m"))
        if s.pipe_rating_head_m is not None:
            L.append(_row("Pipe pressure rating", f"{s.pipe_rating_head_m:.1f}",
                          f"m   ({'EXCEEDED' if s.exceeds_rating else 'ok'})"))
        L.append(_row("Column-separation risk", "YES" if s.column_separation_risk else "no", ""))
        L.append(_row("Protection needed", "YES" if s.protection_needed else "no", ""))
        for r in s.recommendations:
            L.append(f"    - {r}")
        if s.air_vessel:
            av = s.air_vessel
            L.append("  air vessel (energy-balance estimate):")
            L.append(_row("  min normal gas volume", av["min_normal_gas_volume_m3"], "m3"))
            L.append(_row("  gas volume at down-surge", av["expanded_gas_volume_m3"], "m3"))
            L.append(_row("  suggested gross vessel", av["suggested_gross_vessel_m3"], "m3"))
        if s.flywheel:
            fw = s.flywheel
            L.append("  flywheel (run-down estimate):")
            L.append(_row("  additional inertia", fw["additional_flywheel_inertia_kgm2"], "kg.m2"))
            L.append(_row("  flywheel mass @ k=%.2fm" % fw["radius_of_gyration_m"],
                          fw["flywheel_mass_kg"], "kg"))
        if getattr(s, "transient", None):
            tr = s.transient
            L.append("  MOC transient (pump trip):")
            L.append(_row("  max head", tr["max_head_m"], f"m at x={tr['max_head_at_x_m']} m"))
            L.append(_row("  min head", tr["min_head_m"], f"m at x={tr['min_head_at_x_m']} m"))
            L.append(_row("  min gauge pressure", tr["min_gauge_pressure_head_m"], "m"))
            L.append(_row("  vapour separation", "YES" if tr["vapour_separation"] else "no", ""))
            if tr.get("air_vessel_max_gas_volume_m3") is not None:
                L.append(_row("  air-vessel gas vol (max)", tr["air_vessel_max_gas_volume_m3"], "m3"))
            if tr.get("exceeds_rating") is not None:
                L.append(_row("  vs pipe rating", "EXCEEDED" if tr["exceeds_rating"] else "ok", ""))
            for nt in tr.get("notes", []):
                L.append(f"    - {nt}")
        else:
            L.append("  (rule-of-thumb only - set water_hammer.method: moc for a transient run)")

    if res.staging is not None:
        st = res.staging
        sm = st.summary()
        L.append("\n-- Demand-pattern staging ------------------------------------")
        L.append(_row("Mode", "VFD common-speed" if any(s.speed_ratio not in (0.0, 1.0)
                      for s in st.steps) else "fixed-speed lead/lag", ""))
        L.append(_row("Daily energy", f"{sm['daily_energy_kwh']:.0f}", "kWh"))
        if sm["daily_energy_cost"]:
            L.append(_row("Daily energy cost", f"{sm['daily_energy_cost']:.0f}", ""))
        L.append(_row("Running efficiency min / mean",
                      f"{sm['efficiency_min_pct']:.0f} / {sm['efficiency_mean_pct']:.0f}", "%"))
        L.append(_row("Time outside BEP window", f"{sm['fraction_time_outside_bep']*100:.0f}", "%"))
        L.append(_row("Starts per pump", str(sm["per_pump_starts"]), ""))
        L.append(_row("Run hours per pump", str(sm["per_pump_run_hours"]), ""))
        L.append(_row("Peak starts/hour", f"{sm['max_starts_per_hour_seen']:.0f}", ""))
        L.append(_row("Standby pump needed", "YES" if sm["standby_used"] else "no", ""))
        if sm["unmet_demand_steps"]:
            L.append(_row("Steps demand NOT met", sm["unmet_demand_steps"], ""))
        for wn in sm["warnings"]:
            L.append(f"    - {wn}")

    L.append("\n-- EPANET export ------------------------------------------------")
    L.append(f"(flow units: {res.epanet_export.flow_units}, head: m)\n")
    L.append(res.epanet_export.full_snippet())

    if res.warnings:
        L.append("\n-- Warnings ----------------------------------------------------")
        for wn in res.warnings:
            L.append(f"  ! {wn}")

    return "\n".join(L)


def plot_performance(res: ProjectResults, path: str | Path, *, dpi: int = 130):
    """Save a system-curve / pump-curve / operating-point figure (needs matplotlib)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    op = res.operating_point
    q_design = res.duty_flow_per_pump_m3s * max(op.n_pumps, 1)
    q_max = max(res.pump.max_flow() * max(op.n_pumps, 1), q_design * 1.4)
    q = np.linspace(1e-4, q_max, 200)
    q_lps = q * 1000.0

    fig, ax1 = plt.subplots(figsize=(8.5, 5.4))
    for label, sc in res.system_set.as_dict().items():
        style = "-" if "used" in label else "--"
        ax1.plot(q_lps, sc.head(q), style, lw=1.2, alpha=0.8, label=f"system {label}")

    single = res.pump
    ax1.plot(q_lps, single.head(q), color="tab:blue", lw=2, label=f"pump x1 ({single.name})")
    if op.n_pumps > 1:
        from .pumpcurve import PumpCurve
        comb = PumpCurve.parallel([single] * op.n_pumps)
        ax1.plot(q_lps, comb.head(q), color="navy", lw=2, label=f"pump x{op.n_pumps} parallel")

    ax1.plot(op.flow_lps, op.head_m, "o", ms=10, color="crimson", zorder=5,
             label=f"operating point\n{op.flow_lps:.0f} l/s @ {op.head_m:.1f} m")
    ax1.set_xlabel("Flow  [l/s]")
    ax1.set_ylabel("Head  [m]")
    ax1.set_xlim(0, q_lps.max())
    ax1.set_ylim(0, None)
    ax1.grid(alpha=0.3)
    ax1.set_title(f"{res.project_name} - pump / system operating point")

    if single.eff_pts is not None:
        ax2 = ax1.twinx()
        ax2.plot(q_lps, single.efficiency(q), color="tab:green", lw=1.4, ls=":",
                 label="pump efficiency")
        ax2.set_ylabel("Efficiency  [%]", color="tab:green")
        ax2.set_ylim(0, 100)
        ax2.tick_params(axis="y", colors="tab:green")

    ax1.legend(loc="upper right", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return str(path)
