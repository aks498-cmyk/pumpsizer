import numpy as np
import pytest

from pumpsizer.pipes import PipeSegment
from pumpsizer.system import MinorLoss, SystemCurve


def make_curve():
    seg = PipeSegment("rm", length_m=500.0, diameter_mm=402.8,
                      roughness_mm=0.06, hazen_williams_c=140.0)
    minor = MinorLoss("disch", k_total=8.2, diameter_mm=402.8)
    return SystemCurve(static_head=24.0, segments=[seg], minor_losses=[minor],
                       kinematic_viscosity=0.8007e-6, method="DW")


def test_head_increases_with_flow():
    sc = make_curve()
    assert sc.head(0.0) == pytest.approx(24.0, abs=1e-6)
    assert sc.head(0.3) > sc.head(0.15) > 24.0


def test_components_add_up():
    sc = make_curve()
    q = 0.3
    assert sc.head(q) == pytest.approx(
        sc.static_head + sc.friction_loss(q) + sc.minor_loss(q))


def test_rising_main_friction_is_physical():
    # 500 m of DN400 DI at 300 l/s -> ~5-6 m Darcy friction
    sc = make_curve()
    assert 4.0 < sc.friction_loss(0.3) < 7.5


def test_vectorised_head():
    sc = make_curve()
    q = np.array([0.0, 0.1, 0.2, 0.3])
    h = sc.head(q)
    assert h.shape == q.shape
    assert np.all(np.diff(h) > 0)


def test_hw_method_switch_changes_result():
    sc = make_curve()
    hf_dw = sc.friction_loss(0.3)
    sc.method = "HW"
    hf_hw = sc.friction_loss(0.3)
    assert hf_hw > 0 and abs(hf_hw - hf_dw) / hf_dw < 0.5


def test_k_resistance_reconstructs_dynamic_loss():
    sc = make_curve()
    k = sc.k_resistance(0.3)
    assert k * 0.3 ** 2 == pytest.approx(sc.dynamic_loss(0.3), rel=1e-9)
