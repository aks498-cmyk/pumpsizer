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

    if args.patch:
        from .epanet import patch_inp
        out = args.patch_out or (str(Path(args.patch).with_suffix("")) + ".patched.inp")
        patch_inp(args.patch, res.epanet_export, output_path=out)
        print(f"patched .inp       -> {out}")

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
    r.add_argument("--patch", help="existing .inp to splice this pump into")
    r.add_argument("--patch-out", help="output path for the patched .inp")
    r.set_defaults(func=_cmd_run)

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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
