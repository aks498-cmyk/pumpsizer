import numpy as np
import pytest

from pumpsizer.pumpcurve import PumpCurve


def test_single_point_follows_epanet_rule():
    p = PumpCurve.from_single_point(0.3, 40.0, shutoff_ratio=1.33, runout_flow_ratio=2.0)
    assert p.head(0.0) == pytest.approx(1.33 * 40.0, rel=0.02)
    assert p.head(0.3) == pytest.approx(40.0, rel=0.02)
    assert p.head(0.6) == pytest.approx(0.0, abs=1.0)


def test_abc_fit_recovers_points():
    q = np.array([0.0, 0.1, 0.2, 0.3, 0.4])
    h = 50.0 - 180.0 * q ** 2
    p = PumpCurve.from_points(q, h, prefer="abc")
    assert p.model == "abc"
    assert np.allclose(p.head(q), h, atol=0.5)


def test_affinity_speed_scaling():
    q = np.array([0.0, 0.15, 0.3, 0.45])
    h = 45.0 - 150.0 * q ** 2
    p = PumpCurve.from_points(q, h, prefer="abc")
    half = p.scaled(speed_ratio=0.5)
    # at half speed: flow scales x0.5, head x0.25
    assert half.head(0.15) == pytest.approx(0.25 * p.head(0.30), rel=1e-3)


def test_efficiency_and_bep():
    p = PumpCurve.synthetic(0.3, 40.0, eff_bep=83.0)
    qb, hb, eb = p.bep()
    assert eb == pytest.approx(83.0, abs=1.5)
    assert 0.25 < qb < 0.35


def test_parallel_doubles_flow_at_equal_head():
    q = np.array([0.0, 0.15, 0.3, 0.45])
    h = 45.0 - 150.0 * q ** 2
    p = PumpCurve.from_points(q, h, prefer="abc")
    two = PumpCurve.parallel([p, p])
    h_target = 30.0
    # flow of the pair at h_target ~ 2x single-pump flow at h_target
    from scipy.optimize import brentq
    q1 = brentq(lambda x: p.head(x) - h_target, 1e-4, p.max_flow())
    q2 = brentq(lambda x: two.head(x) - h_target, 1e-4, two.max_flow())
    assert q2 == pytest.approx(2 * q1, rel=0.03)


def test_shaft_power_uses_efficiency():
    p = PumpCurve.synthetic(0.3, 40.0, eff_bep=80.0)
    ph = p.hydraulic_power(0.3)
    ps = p.shaft_power(0.3)
    assert ps > ph
