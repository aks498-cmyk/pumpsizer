"""Shared helper for the verify_ksb_*.py overlay tools: print the digitised
catalogue numbers for the datasheet pages being rendered, so a checker can
compare them with the printed curve without opening the YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]


def print_catalogue_rows(catalogue_yaml: str, pages: list[int]) -> None:
    p = _ROOT / catalogue_yaml
    if not p.exists():
        return
    pumps = yaml.safe_load(p.read_text(encoding="utf-8")).get("pumps", [])
    want = set(pages)
    rows = [e for e in pumps if e.get("datasheet_page") in want]
    if not rows:
        return
    print(f"\ndigitised entries on pages {sorted(want)} ({p.name}):")
    for e in sorted(
        rows, key=lambda e: (e["datasheet_page"], -(e.get("impeller_diameter_mm") or 0))
    ):
        q = e["curve"]["q_lps"]
        h = e["curve"]["h_m"]
        bits = [
            f"p.{e['datasheet_page']:>3}",
            f"{e['model']:<28}",
            f"H0 {h[0]:6.1f}  Hend {h[-1]:5.1f}  Q {q[0]:.1f}-{q[-1]:.1f} l/s",
        ]
        if e.get("eff_bep_pct"):
            bits.append(f"BEP {e['eff_bep_pct']:.1f}% @ {e.get('q_bep_lps', 0):.1f} l/s")
        if e.get("npshr_points"):
            v = e["npshr_points"]["value_m"]
            bits.append(f"NPSHr {min(v):.1f}-{max(v):.1f} m")
        if e.get("stages_max"):
            bits.append(f"x{e['stages_max']} stages")
        if e.get("table9_delta_pct") is not None:
            bits.append(f"Table9 {e['table9_delta_pct']:+.0f}%")
        print("  " + "  ".join(bits))
    print()
