from pathlib import Path

import pytest

from pumpsizer.epanet import FLOW_UNITS, build_pump_export, patch_inp, read_sections
from pumpsizer.project import Project
from pumpsizer.pumpcurve import PumpCurve

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "potable_water_pumping_station.yaml"


def test_epanet_export_blocks_present():
    p = PumpCurve.synthetic(0.3, 34.0, eff_bep=84.0, name="WS300")
    exp = build_pump_export(p, pump_id="PMP1", flow_units="LPS", head_points=3)
    snip = exp.full_snippet()
    assert "[CURVES]" in snip and "[PUMPS]" in snip and "[ENERGY]" in snip
    # 3-point curve, flows strictly increasing, in l/s
    rows = [r for r in exp.curves_section().splitlines() if r.startswith(" C_PMP1")]
    flows = [float(r.split()[1]) for r in rows]
    assert flows == sorted(flows) and flows[-1] > 100


def test_epanet_flow_unit_conversion():
    p = PumpCurve.synthetic(0.3, 34.0, name="X")
    lps = build_pump_export(p, flow_units="LPS", head_points=3).head_points
    cmh = build_pump_export(p, flow_units="CMH", head_points=3).head_points
    assert cmh[1][0] == pytest.approx(lps[1][0] * 3.6, rel=1e-6)


def test_patch_inp_roundtrip(tmp_path):
    base = tmp_path / "net.inp"
    base.write_text(
        "[TITLE]\ntest\n\n[JUNCTIONS]\n J1 0\n\n[PUMPS]\n PMP1 A B HEAD OLD\n\n"
        "[CURVES]\n OLD 1 2\n\n[ENERGY]\n GLOBAL EFFIC 75\n\n[END]\n")
    p = PumpCurve.synthetic(0.3, 34.0, eff_bep=84.0, name="WS300")
    exp = build_pump_export(p, pump_id="PMP1", flow_units="LPS", head_points=3)
    out = patch_inp(base, exp, output_path=tmp_path / "patched.inp")
    sec = read_sections(out)
    assert any("C_PMP1" in ln for ln in sec["CURVES"])
    assert any("HEAD C_PMP1" in ln for ln in sec["PUMPS"])
    assert sum("PMP1" in ln and "HEAD" in ln for ln in sec["PUMPS"]) == 1  # old dropped


def test_project_example_runs():
    res = Project.from_yaml(EXAMPLE).run()
    op = res.operating_point
    # sane potable-water pumping station numbers
    assert 250 < op.flow_lps < 360
    assert 24 < op.head_m < 45
    assert 60 < op.shaft_power_kw < 200
    assert res.motor.rated_kw in (110, 132, 160, 200)
    assert res.npsh.npsh_available_m > 5.0
    assert "[PUMPS]" in res.epanet_export.full_snippet()
    assert res.design_system_head_m > 24.0   # static + losses


def test_project_parallel_and_vfd_variants():
    data = Project.from_yaml(EXAMPLE).data
    data = {**data}
    data["flow"] = {**data["flow"], "duty_pumps": 2}
    data["control"] = {**data["control"], "arrangement": "parallel"}
    res = Project.from_dict(data).run()
    assert res.operating_point.n_pumps == 2
    assert "single_pump" in res.operating_points_extra
