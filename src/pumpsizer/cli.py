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
            print(f"\n  vs pumpsizer prediction for {pump_id}: "
                  f"flow {predicted.flow_lps:.1f} -> {s.flow_lps:.1f} l/s ({dq:+.1f}%), "
                  f"head {predicted.head_m:.1f} -> {s.head_m:.1f} m ({dh:+.1f}%)")
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

    crit = SelectionCriteria(duty_flow_m3s=duty_q, duty_head_m=duty_h,
                             system_curve=system, npsh_available_m=args.npsha,
                             allow_trim=not args.no_trim, allow_vfd=not args.no_vfd)
    ranked = select(cat, crit, top=args.top, include_infeasible=args.all)
    if args.json:
        Path(args.json).write_text(json.dumps([c.as_dict() for c in ranked], indent=2),
                                   encoding="utf-8")
        print(f"wrote {args.json}")
    hdr = f"{'#':>2}  {'pump':<26}{'method':<9}{'eff%':>6}{'Q/BEP':>7}{'NPSHmgn':>9}{'score':>7}  notes"
    print(f"duty {duty_q*1000:.0f} l/s @ {duty_h:.1f} m   "
          f"catalogue: {len(cat)} pumps   feasible: {sum(c.feasible for c in ranked)}")
    print(hdr)
    for i, c in enumerate(ranked, 1):
        if not c.feasible:
            print(f"{i:>2}  {c.model.key:<26}{'infeasible':<9}{'':>22}{'x':>7}  "
                  f"{'; '.join(c.reasons)[:44]}")
            continue
        nm = "-" if c.npsh_margin_m is None else f"{c.npsh_margin_m:.1f}"
        ef = "-" if c.efficiency_pct != c.efficiency_pct else f"{c.efficiency_pct:.0f}"
        print(f"{i:>2}  {c.model.key:<26}{c.method:<9}{ef:>6}{c.bep_ratio:>7.2f}"
              f"{nm:>9}{c.score:>7.2f}  {'; '.join(c.reasons)[:44]}")
    return 0


def _cmd_excel_template(args: argparse.Namespace) -> int:
    from .excelio import write_input_template
    write_input_template(args.out)
    print(f"wrote input template -> {args.out}")
    return 0


def _cmd_excel(args: argparse.Namespace) -> int:
    from .excelio import run_workbook
    out = args.out or (str(Path(args.workbook).with_suffix("")) + ".results.xlsx")
    res = run_workbook(args.workbook, out, legacy=args.legacy)
    print(f"read {'legacy ' if args.legacy else ''}workbook -> {args.workbook}")
    print(f"operating point: {res.operating_point.flow_lps:.1f} l/s @ "
          f"{res.operating_point.head_m:.2f} m   motor {res.motor.rated_kw:g} kW")
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
    v = args.velocity if args.velocity else (args.flow_lps / 1000.0) / (math.pi * d_m ** 2 / 4.0)
    rating = args.rating_m or (args.pn * 10.2 if args.pn else None)

    a = S.assess(length_m=args.length, diameter_m=d_m, wall_thickness_m=e_mm / 1000.0,
                 youngs_modulus_pa=E, steady_velocity_m_s=v, static_head_m=args.static,
                 closure_time_s=args.closure_time, pipe_rating_head_m=rating,
                 shaft_power_kw=args.shaft_power_kw, speed_rpm=args.speed_rpm,
                 allowable_max_head_m=args.allowable_max_m)
    if args.json:
        Path(args.json).write_text(json.dumps(a.as_dict(), indent=2), encoding="utf-8")
    print(f"pipe            {args.length:.0f} m x {id_mm:.1f} mm ID ({args.material}), "
          f"wall ~{e_mm:.1f} mm")
    print(f"celerity a      {a.celerity_m_s:.0f} m/s     pipe period Tc = {a.pipe_period_s:.2f} s")
    print(f"steady v        {v:.2f} m/s")
    print(f"surge head +/-  {a.surge_head_m:.1f} m   [{a.surge_rule}]")
    print(f"head at pump    max {a.max_head_m:.1f} m / min {a.min_head_m:.1f} m")
    if a.pipe_rating_head_m:
        print(f"pipe rating     {a.pipe_rating_head_m:.1f} m  "
              f"({'EXCEEDED' if a.exceeds_rating else 'ok'})")
    print(f"column sep risk {'YES' if a.column_separation_risk else 'no'}     "
          f"protection needed {'YES' if a.protection_needed else 'no'}")
    for r in a.recommendations:
        print(f"  - {r}")
    if a.air_vessel:
        print(f"  air vessel   min gas {a.air_vessel['min_normal_gas_volume_m3']} m3, "
              f"suggested gross {a.air_vessel['suggested_gross_vessel_m3']} m3")
    if a.flywheel:
        print(f"  flywheel     +{a.flywheel['additional_flywheel_inertia_kgm2']} kg.m2  "
              f"(~{a.flywheel['flywheel_mass_kg']} kg at k={a.flywheel['radius_of_gyration_m']} m)")
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


_SCHEMA = (Path(__file__).parent / "data").parent  # placeholder; real file below


def _cmd_schema(_args: argparse.Namespace) -> int:
    example = Path(__file__).resolve().parents[2] / "examples" / "potable_water_pumping_station.yaml"
    if example.exists():
        print(example.read_text(encoding="utf-8"))
    else:  # installed without examples/
        print("see https://…/examples/potable_water_pumping_station.yaml")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pumpsizer", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a project YAML file")
    r.add_argument("project")
    r.add_argument("--report", help="write the text report to this path")
    r.add_argument("--json", help="write the machine-readable summary here")
    r.add_argument("--epanet", help="write the [CURVES]/[PUMPS]/[ENERGY] block here")
    r.add_argument("--plot", help="write a performance plot (PNG) here")
    r.add_argument("--into", dest="into",
                   help="existing .inp to splice this pump/curve/energy into")
    r.add_argument("--patch", dest="into", help=argparse.SUPPRESS)  # legacy alias
    r.add_argument("--patch-out", help="output path for the patched .inp")
    r.add_argument("--simulate", action="store_true",
                   help="run EPANET on the patched .inp and compare (needs epyt)")
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
    sg.add_argument("--allowable-max-m", type=float, help="allowable max head for vessel sizing [m]")
    sg.add_argument("--shaft-power-kw", type=float, help="pump shaft power [kW] for flywheel sizing")
    sg.add_argument("--speed-rpm", type=float, default=1480.0)
    sg.add_argument("--json", help="write the assessment here")
    sg.set_defaults(func=_cmd_surge)

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

    et = sub.add_parser("excel-template", help="write a blank input workbook (openpyxl)")
    et.add_argument("out", help="output .xlsx path")
    et.set_defaults(func=_cmd_excel_template)

    ex = sub.add_parser("excel", help="run a project from an .xlsx and write a results .xlsx")
    ex.add_argument("workbook", help="input .xlsx (template-shaped, or --legacy)")
    ex.add_argument("--out", help="results .xlsx (default: <workbook>.results.xlsx)")
    ex.add_argument("--legacy", action="store_true",
                    help="parse the original Pump Sizing.xlsx Input-sheet layout")
    ex.set_defaults(func=_cmd_excel)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
