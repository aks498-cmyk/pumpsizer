import numpy as np
import pytest

from pumpsizer.motor import next_standard_kw, nominal_efficiency, size_motor
from pumpsizer.npsh import npsh_available
from pumpsizer.operating import solve_operating_point, solve_parallel, solve_vfd_speed
from pumpsizer.pipes import PipeSegment
from pumpsizer.pumpcurve import PumpCurve
from pumpsizer.system import MinorLoss, SystemCurve


def _system(static=24.0):
    seg = PipeSegment("rm", 500.0, 402.8, 0.06, 140.0)
    return SystemCurve(static_head=static, segments=[seg],
                       minor_losses=[MinorLoss("d", 8.2, 402.8)],
                       kinematic_viscosity=0.8007e-6, method="DW")


def _pump():
    return PumpCurve.synthetic(0.3, 34.0, eff_bep=84.0, name="WS-300")


def test_operating_point_on_curve_intersection():
    p, s = _pump(), _system()
    op = solve_operating_point(p, s)
    assert p.head(op.flow_m3s) == pytest.approx(s.head(op.flow_m3s), abs=1e-4)
    assert 0.2 < op.flow_m3s < 0.45
    assert op.shaft_power_kw > op.hydraulic_power_kw


def test_parallel_delivers_more_than_single():
    p, s = _pump(), _system()
    one = solve_operating_point(p, s)
    two = solve_parallel(p, s, 2)
    assert two.flow_m3s > one.flow_m3s
    assert two.head_m > one.head_m          # further up the system curve


def test_vfd_hits_target_flow():
    p, s = _pump(), _system()
    op = solve_vfd_speed(p, s, target_flow_m3s=0.25, min_speed_ratio=0.5)
    assert op.flow_m3s == pytest.approx(0.25, rel=0.02)
    assert 0.5 <= op.speed_ratio <= 1.0


def test_npsh_flooded_positive_and_check():
    r = npsh_available(
        atmospheric_head_m=10.33, static_suction_head_m=0.0,
        suction_friction_loss_m=0.05, suction_minor_loss_m=0.15,
        suction_velocity_head_m=0.03, vapour_pressure_head_m=0.43,
        safety_margin_m=0.5, npsh_required_m=3.5)
    assert r.npsh_available_m == pytest.approx(10.33 - 0.43 - 0.05 - 0.15 - 0.03 - 0.5)
    assert r.safe is True


def test_npsh_lift_can_fail():
    r = npsh_available(
        atmospheric_head_m=10.33, static_suction_head_m=-7.0,
        suction_friction_loss_m=1.0, suction_minor_loss_m=0.5,
        suction_velocity_head_m=0.1, vapour_pressure_head_m=0.43,
        npsh_required_m=3.5)
    assert r.safe is False


def test_motor_series_and_efficiency():
    assert next_standard_kw(118.0) == 132
    assert next_standard_kw(0.6) == 0.75
    e = nominal_efficiency(132, poles=2, ie_class="IE3")
    assert 94.0 < e < 96.0


def test_size_motor_end_to_end():
    m = size_motor(115.0, margin_pct=15, poles=2, ie_class="IE3")
    assert m.rated_kw == 160          # 115*1.15 = 132.25 -> next size 160
    assert m.input_electrical_kw > m.shaft_power_kw
