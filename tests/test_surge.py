import math

import pytest

from pumpsizer import surge as S
from pumpsizer.project import Project

EXAMPLE = __import__("pathlib").Path(__file__).resolve().parents[1] / "examples" / "potable_water_pumping_station.yaml"


def test_celerity_rigid_limit():
    # E -> huge  =>  a -> sqrt(K/rho) ~ 1480 m/s
    a = S.wave_celerity(0.4, 0.01, 1e15)
    assert a == pytest.approx(math.sqrt(S.WATER_BULK_MODULUS / 1000.0), rel=1e-3)


def test_celerity_steel_and_plastic_ballpark():
    a_steel = S.wave_celerity(0.4028, 0.0048, 210e9)      # D/e ~84  -> ~1050-1150 m/s
    a_pe = S.wave_celerity(0.352, 0.048, 1.1e9)           # HDPE ~250-350 m/s
    assert 1000 < a_steel < 1300
    assert 200 < a_pe < 400
    assert a_steel > a_pe


def test_pipe_period_and_joukowsky():
    a = 1200.0
    assert S.pipe_period(600.0, a) == pytest.approx(1.0)
    assert S.joukowsky_head(a, 2.0) == pytest.approx(a * 2.0 / 9.81)


def test_slow_closure_below_joukowsky():
    a = 1200.0
    dh_rapid, rule = S.surge_head(600.0, 2.0, a, closure_time_s=0.5)
    dh_slow, rule2 = S.surge_head(600.0, 2.0, a, closure_time_s=10.0)
    assert "Joukowsky" in rule
    assert dh_slow < dh_rapid
    assert "Michaud" in rule2


def test_air_vessel_scales_with_velocity_squared():
    kw = dict(pipe_area_m2=0.127, length_m=500.0, static_head_m=24.0,
              allowable_max_head_m=150.0, allowable_min_head_m=2.0)
    v1 = S.air_vessel_prelim(velocity_m_s=1.0, **kw)["min_normal_gas_volume_m3"]
    v2 = S.air_vessel_prelim(velocity_m_s=2.0, **kw)["min_normal_gas_volume_m3"]
    assert v2 == pytest.approx(4.0 * v1, rel=0.05)


def test_flywheel_prelim_positive_and_scales_with_target():
    a = S.flywheel_prelim(shaft_power_kw=115.0, speed_rpm=1480.0, target_stop_time_s=1.0)
    b = S.flywheel_prelim(shaft_power_kw=115.0, speed_rpm=1480.0, target_stop_time_s=3.0)
    assert a["additional_flywheel_inertia_kgm2"] >= 0
    assert b["required_total_inertia_kgm2"] == pytest.approx(
        3.0 * a["required_total_inertia_kgm2"], rel=2e-3)


def test_assess_flags_column_separation_on_a_stiff_long_main():
    a = S.assess(length_m=3000.0, diameter_m=0.4028, wall_thickness_m=0.017,
                 youngs_modulus_pa=170e9, steady_velocity_m_s=2.4,
                 static_head_m=24.0, pipe_rating_head_m=163.0)
    assert a.column_separation_risk is True
    assert a.protection_needed is True
    assert a.air_vessel is not None


def test_project_water_hammer_block_runs():
    res = Project.from_yaml(EXAMPLE).run()
    assert res.surge is not None
    s = res.surge
    assert 900 < s.celerity_m_s < 1300          # DI DN400
    assert s.surge_head_m > 0
    assert s.max_head_m > s.static_head_m
