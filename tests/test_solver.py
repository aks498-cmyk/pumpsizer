import pytest

from pumpsizer.epanet import build_pump_export
from pumpsizer.operating import solve_operating_point
from pumpsizer.pipes import PipeSegment
from pumpsizer.pumpcurve import PumpCurve
from pumpsizer.solver import available, patch_and_simulate, simulate
from pumpsizer.system import SystemCurve

pytestmark = pytest.mark.skipif(not available(), reason="epyt not installed")

BASE_INP = """[TITLE]
solver test - static lift 24 m + 500 m DN400
[JUNCTIONS]
 J1  \t8\t0
[RESERVOIRS]
 RSUC \t8
 RDIS \t32
[PIPES]
 RM  \tJ1\tRDIS\t500\t402.8\t0.06\t0\tOpen
[PUMPS]
 PMP1 \tRSUC\tJ1\tHEAD C_SEED
[CURVES]
 C_SEED\t0\t45
 C_SEED\t300\t35
 C_SEED\t600\t10
[OPTIONS]
 UNITS  LPS
 HEADLOSS  D-W
[TIMES]
 DURATION  0
[REPORT]
 STATUS  NO
[END]
"""


def _standalone_prediction():
    seg = PipeSegment("RM", 500.0, 402.8, 0.06, 140.0)
    sysc = SystemCurve(
        static_head=24.0, segments=[seg], minor_losses=[], kinematic_viscosity=1.004e-6, method="DW"
    )
    pump = PumpCurve.synthetic(0.3, 33.0, eff_bep=84.0, name="WS300")
    return pump, solve_operating_point(pump, sysc)


def test_epanet_matches_standalone_operating_point(tmp_path):
    base = tmp_path / "net.inp"
    base.write_text(BASE_INP)
    pump, pred = _standalone_prediction()
    exp = build_pump_export(
        pump, pump_id="PMP1", from_node="RSUC", to_node="J1", flow_units="LPS", head_points=7
    )
    sim, patched = patch_and_simulate(base, exp, output_path=tmp_path / "patched.inp")

    p = sim.pump("PMP1")
    assert sim.flow_units == "LPS"
    assert p.status == "open"
    # EPANET's own solve should land within a few % of ours
    assert p.flow_lps == pytest.approx(pred.flow_lps, rel=0.06)
    assert p.head_m == pytest.approx(pred.head_m, rel=0.06)
    assert 24.0 < p.head_m < 40.0


def test_simulate_reads_seed_curve(tmp_path):
    base = tmp_path / "seed.inp"
    base.write_text(BASE_INP)
    sim = simulate(base)
    p = sim.pump("PMP1")
    # seed curve is higher than the patched one -> more flow, still physical
    assert 200 < p.flow_lps < 500
