"""Command-line interface.

pumpsizer run PROJECT.yaml [--report out.txt] [--plot out.png]
                          [--epanet out.inp] [--json out.json]
                          [--patch existing.inp --patch-out patched.inp]
pumpsizer curve --duty-q 300 --duty-h 45 [--source synthetic|single_point]
               [--epanet-units LPS] [--points 3]
pumpsizer schema        # print an annotated example project file
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .project import Project
from .pumpcurve import PumpCurve
from .report import text_report


def _cmd_run(args: argparse.Namespace) -> int:
    proj = Project.from_yaml(args.project)
    res = proj.run()
    report = text_report(res)

    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"wrote report      -> {args.report}")
    else:
        print(report)

    if args.json:
        Path(args.json).write_text(json.dumps(res.summary(), indent=2), encoding="utf-8")
        print(f"wrote summary json -> {args.json}")

    if args.epanet:
        Path(args.epanet).write_text(res.epanet_export.full_snippet(), encoding="utf-8")
        print(f"wrote EPANET block -> {args.epanet}")

    target_inp = args.into
    if target_inp:
        from .inpfile import InpModel

        out = args.patch_out or (str(Path(target_inp).with_suffix("")) + ".patched.inp")
        model = InpModel.read(target_inp)
        model.apply_export(res.epanet_export)
        model.write(out)
        print(f"patched .inp       -> {out}")
        if args.simulate:
            _print_sim_vs_prediction(out, res.epanet_export.pump_id, res.operating_point)

    if args.plot:
        try:
            from .report import plot_performance

            plot_performance(res, args.plot)
            print(f"wrote plot         -> {args.plot}")
        except ImportError:
            print("!! matplotlib not installed; skipping --plot", file=sys.stderr)

    if res.warnings:
        print("\nwarnings:")
        for w in res.warnings:
            print(f"  ! {w}")
    return 0


def _print_sim_vs_prediction(inp_path, pump_id, predicted=None) -> int:
    from .solver import available, simulate

    if not available():
        print("!! EPANET solver bridge needs 'epyt'  (pip install epyt)", file=sys.stderr)
        return 2
    sim = simulate(inp_path)
    print(f"\nEPANET simulation ({sim.flow_units}):")
    print(f"  {'pump':<14}{'flow l/s':>12}{'head m':>10}{'status':>9}")
    for p in sim.pumps:
        print(f"  {p.id:<14}{p.flow_lps:>12.2f}{p.head_m:>10.2f}{p.status:>9}")
    if predicted is not None:
        try:
            s = sim.pump(pump_id)
            dq = (s.flow_lps - predicted.flow_lps) / predicted.flow_lps * 100
            dh = (s.head_m - predicted.head_m) / predicted.head_m * 100
            print(
                f"\n  vs pumpsizer prediction for {pump_id}: "
                f"flow {predicted.flow_lps:.1f} -> {s.flow_lps:.1f} l/s ({dq:+.1f}%), "
                f"head {predicted.head_m:.1f} -> {s.head_m:.1f} m ({dh:+.1f}%)"
            )
        except KeyError as exc:
            print(f"  ({exc})")
    for w in sim.warnings:
        if w.strip():
            print(f"  epanet: {w.strip()}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    predicted = None
    if args.project:
        predicted = Project.from_yaml(args.project).run().operating_point
    return _print_sim_vs_prediction(args.inp, args.pump_id, predicted)


def _cmd_select(args: argparse.Namespace) -> int:
    from .catalog import Catalog
    from .selection import SelectionCriteria, select

    cat = Catalog.from_path(args.catalogue) if args.catalogue else Catalog.bundled()
    system = None
    duty_q, duty_h = args.duty_q / 1000.0, args.duty_h
    if args.project:
        res = Project.from_yaml(args.project).run()
        system = res.system_set.design()
        duty_q = duty_q or res.duty_flow_per_pump_m3s
        duty_h = duty_h or res.duty_head_m
        if args.npsha is None:
            args.npsha = res.npsh.npsh_available_m

    crit = SelectionCriteria(
        duty_flow_m3s=duty_q,
        duty_head_m=duty_h,
        system_curve=system,
        npsh_available_m=args.npsha,
        allow_trim=not args.no_trim,
        allow_vfd=not args.no_vfd,
    )
    ranked = select(cat, crit, top=args.top, include_infeasible=args.all)
    if args.json:
        Path(args.json).write_text(
            json.dumps([c.as_dict() for c in ranked], indent=2), encoding="utf-8"
        )
        print(f"wrote {args.json}")
    hdr = f"{'#':>2}  {'pump':<26}{'method':<9}{'eff%':>6}{'Q/BEP':>7}{'NPSHmgn':>9}{'score':>7}  notes"
    print(
        f"duty {duty_q * 1000:.0f} l/s @ {duty_h:.1f} m   "
        f"catalogue: {len(cat)} pumps   feasible: {sum(c.feasible for c in ranked)}"
    )
    print(hdr)
    for i, c in enumerate(ranked, 1):
        if not c.feasible:
            print(
                f"{i:>2}  {c.model.key:<26}{'infeasible':<9}{'':>22}{'x':>7}  "
                f"{'; '.join(c.reasons)[:44]}"
            )
            continue
        nm = "-" if c.npsh_margin_m is None else f"{c.npsh_margin_m:.1f}"
        ef = "-" if c.efficiency_pct != c.efficiency_pct else f"{c.efficiency_pct:.0f}"
        print(
            f"{i:>2}  {c.model.key:<26}{c.method:<9}{ef:>6}{c.bep_ratio:>7.2f}"
            f"{nm:>9}{c.score:>7.2f}  {'; '.join(c.reasons)[:44]}"
        )
    return 0


def _cmd_stage(args: argparse.Namespace) -> int:
    proj = Project.from_yaml(args.project)
    if args.mode:
        proj.data.setdefault("staging", {})["mode"] = args.mode
    proj.data.setdefault("staging", {})["enabled"] = True
    res = proj.run()
    if res.staging is None:
        print("no staging result (check the staging: block)", file=sys.stderr)
        return 2
    st = res.staging
    sm = st.summary()
    print(
        f"daily energy {sm['daily_energy_kwh']:.0f} kWh   "
        f"eff min/mean {sm['efficiency_min_pct']:.0f}/{sm['efficiency_mean_pct']:.0f}%   "
        f"outside BEP {sm['fraction_time_outside_bep'] * 100:.0f}%"
    )
    print(
        f"starts/pump {sm['per_pump_starts']}   run h/pump {sm['per_pump_run_hours']}   "
        f"peak {sm['max_starts_per_hour_seen']:.0f}/h   standby used: {sm['standby_used']}"
    )
    print(f"{'t[h]':>5}{'demand':>9}{'deliv':>9}{'pumps':>7}{'speed%':>8}{'head':>7}{'kW':>8}")
    for s in st.steps[: len(res.staging.steps) if args.full else 24]:
        print(
            f"{s.time_h:>5.0f}{s.demand_m3s * 1000:>9.0f}{s.flow_delivered_m3s * 1000:>9.0f}"
            f"{s.running_pumps:>7}{s.speed_ratio * 100:>8.0f}{s.head_m:>7.1f}{s.input_power_kw:>8.1f}"
        )
    for w in sm["warnings"]:
        print(f"  ! {w}")
    if args.json:
        Path(args.json).write_text(json.dumps(sm, indent=2), encoding="utf-8")
    if args.plot:
        try:
            _plot_staging(st, args.plot)
            print(f"wrote plot -> {args.plot}")
        except ImportError:
            print("!! matplotlib not installed", file=sys.stderr)
    return 0


def _plot_staging(st, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = st.array("time_h")
    run = st.array("running_pumps")
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    a1.fill_between(t, 0, st.array("demand_m3s") * 1000, step="mid", color="0.85", label="demand")
    a1.plot(t, st.array("flow_delivered_m3s") * 1000, "b-", lw=1.6, label="delivered")
    a1.set_ylabel("flow [l/s]")
    a1.grid(alpha=0.3)
    a1.legend(fontsize=8)
    a1.set_title("Demand-pattern staging")

    a2.step(t, run, "g-", where="mid", lw=1.6, label="pumps running")
    a2.set_ylabel("pumps running", color="g")
    a2.set_ylim(-0.2, max(1, int(run.max())) + 0.5)
    a2.set_yticks(range(0, max(1, int(run.max())) + 1))
    a2.grid(alpha=0.3)
    a2b = a2.twinx()
    a2b.plot(t, st.array("speed_ratio") * 100, "m-", alpha=0.8, label="speed %")
    a2b.set_ylabel("speed [%]", color="m")
    a2b.set_ylim(0, 105)

    a3.plot(t, st.array("tank_level_m"), "c-", lw=1.6)
    a3.set_ylabel("tank level [m]")
    a3.set_xlabel("time [h]")
    a3.grid(alpha=0.3)
    a3.ticklabel_format(axis="y", useOffset=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _cmd_transient(args: argparse.Namespace) -> int:
    import json as _json

    from . import transient as T
    from .pipes import PipeDatabase

    db = PipeDatabase.default()
    id_mm = args.diameter_mm or db.internal_diameter_mm(args.material, args.dn, args.series)
    e_mm = db.wall_thickness_from_id_mm(args.material, id_mm, args.series)
    E = db.youngs_modulus_gpa(args.material) * 1e9
    pipe = T.Pipeline.from_pipe(
        length_m=args.length,
        diameter_mm=id_mm,
        wall_thickness_mm=e_mm,
        youngs_modulus_pa=E,
        friction_factor=args.friction,
        pump_elevation_m=0.0,
        reservoir_elevation_m=args.static,
        reaches=args.reaches,
    )
    pump = T.PumpInertia(
        rated_speed_rpm=args.speed_rpm,
        rated_flow_m3s=args.flow_lps / 1000.0,
        rated_head_m=args.head,
        total_inertia_kgm2=args.inertia,
        rated_efficiency=args.efficiency,
    )
    av = T.AirVessel(gas_volume_m3=args.air_vessel_m3) if args.air_vessel_m3 else None
    r = T.simulate_pump_trip(
        pipe,
        pump,
        sump_level_m=0.0,
        reservoir_level_m=args.static,
        air_vessel=av,
        duration_s=args.duration,
    )
    d = r.as_dict()
    if args.json:
        Path(args.json).write_text(_json.dumps(d, indent=2), encoding="utf-8")
    print(
        f"pipe        {args.length:.0f} m x {id_mm:.1f} mm ID  a={pipe.wave_speed_m_s:.0f} m/s  "
        f"Tc={2 * args.length / pipe.wave_speed_m_s:.2f} s"
    )
    print(f"max head    {d['max_head_m']:.1f} m  (x={d['max_head_at_x_m']} m)")
    print(
        f"min head    {d['min_head_m']:.1f} m  (x={d['min_head_at_x_m']} m)  "
        f"min gauge {d['min_gauge_pressure_head_m']:.1f} m"
    )
    print(f"vapour separation: {'YES' if d['vapour_separation'] else 'no'}")
    if d.get("air_vessel_max_gas_volume_m3") is not None:
        print(
            f"air vessel   {args.air_vessel_m3:.1f} m3 initial -> {d['air_vessel_max_gas_volume_m3']:.1f} m3 max gas"
        )
    for nt in d["notes"]:
        print(f"  - {nt}")
    if args.plot:
        try:
            _plot_transient(r, args.plot)
            print(f"wrote plot   -> {args.plot}")
        except ImportError:
            print("!! matplotlib not installed; skipping --plot", file=sys.stderr)
    return 0


def _plot_transient(r, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.5, 6), sharex=False)
    ax1.plot(r.time_s, r.head_pump_m, label="pump")
    ax1.plot(r.time_s, r.head_midpoint_m, label="mid-line", alpha=0.7)
    ax1.set_xlabel("time [s]")
    ax1.set_ylabel("head [m]")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8)
    ax1.set_title("MOC pump-trip transient")
    ax2.plot(r.node_x_m, r.envelope_max_m, "r-", label="max envelope")
    ax2.plot(r.node_x_m, r.envelope_min_m, "b-", label="min envelope")
    ax2.plot(r.node_x_m, r.node_elevation_m, "k--", lw=0.8, label="pipe elevation")
    ax2.fill_between(
        r.node_x_m,
        r.node_elevation_m - 10.1,
        r.node_elevation_m,
        color="orange",
        alpha=0.15,
        label="vacuum band",
    )
    ax2.set_xlabel("distance along main [m]")
    ax2.set_ylabel("head [m]")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _cmd_excel_template(args: argparse.Namespace) -> int:
    from .excelio import write_input_template

    write_input_template(args.out)
    print(f"wrote input template -> {args.out}")
    return 0


def _cmd_excel_addin(args: argparse.Namespace) -> int:
    from .excelio import write_input_template
    from .xlwings_addin import BUTTON_BAS

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pumpsizer.bas").write_text(BUTTON_BAS, encoding="utf-8")
    write_input_template(out / "pumpsizer_inputs.xlsx")
    (out / "README.txt").write_text(
        "pumpsizer Excel button - one-time setup\n"
        "======================================\n\n"
        '1. pip install "pumpsizer[xlwings]"\n'
        "2. xlwings addin install            (adds RunPython to Excel)\n"
        "3. Open pumpsizer_inputs.xlsx, save it as .xlsm (macro-enabled).\n"
        "4. Developer > Visual Basic > File > Import File... > pumpsizer.bas\n"
        "5. On the Input sheet, add a Form Control button -> assign RunPumpsizer.\n"
        "6. Fill the Input sheet, click the button. Results open in\n"
        "   <workbook>-results.xlsx and a status line lands in Input!F1.\n\n"
        "Full guide: docs/excel_button.md\n",
        encoding="utf-8",
    )
    print(f"wrote pumpsizer.bas, pumpsizer_inputs.xlsx, README.txt -> {out}/")
    return 0


def _cmd_excel(args: argparse.Namespace) -> int:
    from .excelio import run_workbook

    out = args.out or (str(Path(args.workbook).with_suffix("")) + ".results.xlsx")
    res = run_workbook(args.workbook, out, legacy=args.legacy)
    print(f"read {'legacy ' if args.legacy else ''}workbook -> {args.workbook}")
    print(
        f"operating point: {res.operating_point.flow_lps:.1f} l/s @ "
        f"{res.operating_point.head_m:.2f} m   motor {res.motor.rated_kw:g} kW"
    )
    print(f"wrote results        -> {out}")
    for w in res.warnings:
        print(f"  ! {w}")
    return 0


def _cmd_surge(args: argparse.Namespace) -> int:
    import math

    from . import surge as S
    from .pipes import PipeDatabase

    db = PipeDatabase.default()
    if args.diameter_mm:
        id_mm = args.diameter_mm
    else:
        id_mm = db.internal_diameter_mm(args.material, args.dn, args.series)
    e_mm = db.wall_thickness_from_id_mm(args.material, id_mm, args.series)
    E = db.youngs_modulus_gpa(args.material) * 1e9
    d_m = id_mm / 1000.0
    v = args.velocity if args.velocity else (args.flow_lps / 1000.0) / (math.pi * d_m**2 / 4.0)
    rating = args.rating_m or (args.pn * 10.2 if args.pn else None)

    a = S.assess(
        length_m=args.length,
        diameter_m=d_m,
        wall_thickness_m=e_mm / 1000.0,
        youngs_modulus_pa=E,
        steady_velocity_m_s=v,
        static_head_m=args.static,
        closure_time_s=args.closure_time,
        pipe_rating_head_m=rating,
        shaft_power_kw=args.shaft_power_kw,
        speed_rpm=args.speed_rpm,
        allowable_max_head_m=args.allowable_max_m,
    )
    if args.json:
        Path(args.json).write_text(json.dumps(a.as_dict(), indent=2), encoding="utf-8")
    print(
        f"pipe            {args.length:.0f} m x {id_mm:.1f} mm ID ({args.material}), "
        f"wall ~{e_mm:.1f} mm"
    )
    print(f"celerity a      {a.celerity_m_s:.0f} m/s     pipe period Tc = {a.pipe_period_s:.2f} s")
    print(f"steady v        {v:.2f} m/s")
    print(f"surge head +/-  {a.surge_head_m:.1f} m   [{a.surge_rule}]")
    print(f"head at pump    max {a.max_head_m:.1f} m / min {a.min_head_m:.1f} m")
    if a.pipe_rating_head_m:
        print(
            f"pipe rating     {a.pipe_rating_head_m:.1f} m  "
            f"({'EXCEEDED' if a.exceeds_rating else 'ok'})"
        )
    print(
        f"column sep risk {'YES' if a.column_separation_risk else 'no'}     "
        f"protection needed {'YES' if a.protection_needed else 'no'}"
    )
    for r in a.recommendations:
        print(f"  - {r}")
    if a.air_vessel:
        print(
            f"  air vessel   min gas {a.air_vessel['min_normal_gas_volume_m3']} m3, "
            f"suggested gross {a.air_vessel['suggested_gross_vessel_m3']} m3"
        )
    if a.flywheel:
        print(
            f"  flywheel     +{a.flywheel['additional_flywheel_inertia_kgm2']} kg.m2  "
            f"(~{a.flywheel['flywheel_mass_kg']} kg at k={a.flywheel['radius_of_gyration_m']} m)"
        )
    return 0


def _cmd_curve(args: argparse.Namespace) -> int:
    q = args.duty_q / 1000.0
    if args.source == "single_point":
        pump = PumpCurve.from_single_point(q, args.duty_h, shutoff_ratio=args.shutoff)
    else:
        pump = PumpCurve.synthetic(q, args.duty_h, shutoff_ratio=args.shutoff)
    print(json.dumps(pump.summary(), indent=2))
    from .epanet import build_pump_export

    exp = build_pump_export(pump, flow_units=args.epanet_units, head_points=args.points)
    print("\n" + exp.full_snippet())
    return 0


def _cmd_catalog_check(args: argparse.Namespace) -> int:
    from .catalog import Catalog
    from .catalog_qa import check_catalog, format_report, summarise

    cat = Catalog.from_path(args.catalogue) if args.catalogue else Catalog.bundled()
    findings = check_catalog(cat)
    if args.json:
        Path(args.json).write_text(
            json.dumps([f.__dict__ for f in findings], indent=2), encoding="utf-8"
        )
        print(f"wrote {args.json}")
    print(format_report(cat, findings, show_ok=args.show_ok))
    return 1 if summarise(findings)["FAIL"] and not args.no_fail else 0


def _cmd_catalog_verify(args: argparse.Namespace) -> int:
    from .catalog import Catalog
    from .catalog_qa import check_catalog, verification_status, write_checklist

    cat = Catalog.from_path(args.catalogue) if args.catalogue else Catalog.bundled()
    if args.emit:
        n = write_checklist(cat, args.emit, check_catalog(cat))
        print(f"wrote {n} rows to check -> {args.emit}")
        print("fill verdict / checked_by / checked_date / notes against the paper")
        print("datasheet, then set `verified: true` on the OK entries in the YAML.")
        return 0
    st = verification_status(cat)
    print(f"{'series':<16}{'verified':>10}{'to check':>10}{'other':>8}")
    for series, b in sorted(st.items(), key=lambda kv: (kv[0] == "TOTAL", kv[0])):
        print(f"{series:<16}{b['verified']:>10}{b['to_check']:>10}{b['other']:>8}")
    return 0


_SCHEMA = (Path(__file__).parent / "data").parent  # placeholder; real file below


def _cmd_schema(_args: argparse.Namespace) -> int:
    example = (
        Path(__file__).resolve().parents[2] / "examples" / "potable_water_pumping_station.yaml"
    )
    if example.exists():
        print(example.read_text(encoding="utf-8"))
    else:  # installed without examples/
        print("see https://…/examples/potable_water_pumping_station.yaml")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pumpsizer", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a project YAML file")
    r.add_argument("project")
    r.add_argument("--report", help="write the text report to this path")
    r.add_argument("--json", help="write the machine-readable summary here")
    r.add_argument("--epanet", help="write the [CURVES]/[PUMPS]/[ENERGY] block here")
    r.add_argument("--plot", help="write a performance plot (PNG) here")
    r.add_argument(
        "--into", dest="into", help="existing .inp to splice this pump/curve/energy into"
    )
    r.add_argument("--patch", dest="into", help=argparse.SUPPRESS)  # legacy alias
    r.add_argument("--patch-out", help="output path for the patched .inp")
    r.add_argument(
        "--simulate",
        action="store_true",
        help="run EPANET on the patched .inp and compare (needs epyt)",
    )
    r.set_defaults(func=_cmd_run)

    v = sub.add_parser("verify", help="run EPANET on an .inp and report pump operating points")
    v.add_argument("inp", help=".inp file to simulate")
    v.add_argument("--pump-id", default="PMP1", help="pump id to compare against a prediction")
    v.add_argument("--project", help="project YAML whose prediction to compare with")
    v.set_defaults(func=_cmd_verify)

    sel = sub.add_parser("select", help="rank catalogue pumps against a duty point")
    sel.add_argument("--duty-q", type=float, default=0.0, help="duty flow [l/s]")
    sel.add_argument("--duty-h", type=float, default=0.0, help="duty head [m]")
    sel.add_argument("--catalogue", help="catalogue file or directory (default: bundled)")
    sel.add_argument("--project", help="project YAML -> real system curve + NPSHa")
    sel.add_argument("--npsha", type=float, help="NPSH available [m] for the margin check")
    sel.add_argument("--no-trim", action="store_true", help="disallow impeller trim")
    sel.add_argument("--no-vfd", action="store_true", help="disallow VFD speed-up")
    sel.add_argument("--all", action="store_true", help="also list infeasible pumps")
    sel.add_argument("--top", type=int, help="show only the top N")
    sel.add_argument("--json", help="write the ranked list here")
    sel.set_defaults(func=_cmd_select)

    sg = sub.add_parser("surge", help="rule-of-thumb water-hammer pre-sizing for a main")
    sg.add_argument("--length", type=float, required=True, help="rising-main length [m]")
    sg.add_argument("--material", default="ductile_iron")
    sg.add_argument("--dn", type=float, help="nominal diameter (uses the pipe DB bore)")
    sg.add_argument("--diameter-mm", type=float, help="internal diameter [mm] (overrides --dn)")
    sg.add_argument("--series", help="SDR name for HDPE/uPVC")
    sg.add_argument("--velocity", type=float, help="steady velocity [m/s]")
    sg.add_argument("--flow-lps", type=float, help="steady flow [l/s] (if --velocity omitted)")
    sg.add_argument("--static", type=float, required=True, help="static head [m]")
    sg.add_argument("--closure-time", type=float, help="valve/pump-trip effective time [s]")
    sg.add_argument("--pn", type=float, help="pipe pressure class [bar] -> rating head")
    sg.add_argument("--rating-m", type=float, help="pipe rating as head [m] (overrides --pn)")
    sg.add_argument(
        "--allowable-max-m", type=float, help="allowable max head for vessel sizing [m]"
    )
    sg.add_argument(
        "--shaft-power-kw", type=float, help="pump shaft power [kW] for flywheel sizing"
    )
    sg.add_argument("--speed-rpm", type=float, default=1480.0)
    sg.add_argument("--json", help="write the assessment here")
    sg.set_defaults(func=_cmd_surge)

    stg = sub.add_parser("stage", help="extended-period demand-pattern multi-pump staging")
    stg.add_argument("project", help="project YAML with a staging: block")
    stg.add_argument("--mode", choices=["fixed", "vfd"], help="override staging.mode")
    stg.add_argument("--full", action="store_true", help="print every step, not just 24 h")
    stg.add_argument("--plot", help="write demand / pumps / tank-level PNG")
    stg.add_argument("--json", help="write the staging summary here")
    stg.set_defaults(func=_cmd_stage)

    tr = sub.add_parser("transient", help="method-of-characteristics pump-trip surge run")
    tr.add_argument("--length", type=float, required=True, help="rising-main length [m]")
    tr.add_argument("--material", default="ductile_iron")
    tr.add_argument("--dn", type=float, help="nominal diameter (pipe DB bore)")
    tr.add_argument("--diameter-mm", type=float, help="internal diameter [mm]")
    tr.add_argument("--series", help="SDR name for HDPE/uPVC")
    tr.add_argument("--flow-lps", type=float, required=True, help="steady flow [l/s]")
    tr.add_argument("--head", type=float, required=True, help="pump head at duty [m]")
    tr.add_argument("--static", type=float, required=True, help="static lift [m]")
    tr.add_argument(
        "--inertia", type=float, required=True, help="pump+motor rotating inertia [kg.m2]"
    )
    tr.add_argument("--speed-rpm", type=float, default=1480.0)
    tr.add_argument("--efficiency", type=float, default=0.82)
    tr.add_argument("--friction", type=float, default=0.017, help="Darcy f for the main")
    tr.add_argument("--air-vessel-m3", type=float, help="initial gas volume of an air vessel [m3]")
    tr.add_argument("--reaches", type=int, default=24)
    tr.add_argument("--duration", type=float, help="sim duration [s] (default ~10 pipe periods)")
    tr.add_argument("--plot", help="write a head-trace + envelope PNG here")
    tr.add_argument("--json", help="write the result summary here")
    tr.set_defaults(func=_cmd_transient)

    c = sub.add_parser("curve", help="quick curve from a duty point")
    c.add_argument("--duty-q", type=float, required=True, help="duty flow [l/s]")
    c.add_argument("--duty-h", type=float, required=True, help="duty head [m]")
    c.add_argument("--source", choices=["synthetic", "single_point"], default="synthetic")
    c.add_argument("--shutoff", type=float, default=1.20, help="shut-off/design head ratio")
    c.add_argument("--epanet-units", default="LPS")
    c.add_argument("--points", type=int, default=3, help="EPANET head-curve points")
    c.set_defaults(func=_cmd_curve)

    s = sub.add_parser("schema", help="print an example project file")
    s.set_defaults(func=_cmd_schema)

    cc = sub.add_parser("catalog-check", help="QA the (digitised) pump catalogue")
    cc.add_argument("--catalogue", help="catalogue file or directory (default: bundled)")
    cc.add_argument("--json", help="write findings here")
    cc.add_argument("--show-ok", action="store_true", help="also print OK-level notes")
    cc.add_argument(
        "--no-fail", action="store_true", help="always exit 0 (report only, don't gate)"
    )
    cc.set_defaults(func=_cmd_catalog_check)

    cv = sub.add_parser(
        "catalog-verify", help="verification status / checklist for digitised entries"
    )
    cv.add_argument("--catalogue", help="catalogue file or directory (default: bundled)")
    cv.add_argument("--emit", help="write a CSV checklist of the entries still to verify")
    cv.set_defaults(func=_cmd_catalog_verify)

    et = sub.add_parser("excel-template", help="write a blank input workbook (openpyxl)")
    et.add_argument("out", help="output .xlsx path")
    et.set_defaults(func=_cmd_excel_template)

    ea = sub.add_parser(
        "excel-addin", help="write the xlwings 'Run' button (.bas + template + README)"
    )
    ea.add_argument("--out", default="excel_button", help="output directory")
    ea.set_defaults(func=_cmd_excel_addin)

    ex = sub.add_parser("excel", help="run a project from an .xlsx and write a results .xlsx")
    ex.add_argument("workbook", help="input .xlsx (template-shaped, or --legacy)")
    ex.add_argument("--out", help="results .xlsx (default: <workbook>.results.xlsx)")
    ex.add_argument(
        "--legacy",
        action="store_true",
        help="parse the original Pump Sizing.xlsx Input-sheet layout",
    )
    ex.set_defaults(func=_cmd_excel)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
