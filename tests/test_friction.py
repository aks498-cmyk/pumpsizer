import math

import pytest

from pumpsizer.friction import (
    colebrook_white,
    darcy_weisbach_hf,
    hazen_williams_hf,
    reynolds,
    velocity,
)


def test_laminar_branch():
    assert colebrook_white(1000, 1e-3) == pytest.approx(64 / 1000)


def test_colebrook_matches_known_moody_point():
    # Re = 1e5, e/D = 1e-4  ->  f ~ 0.0185 (Colebrook-White, just above smooth)
    f = colebrook_white(1e5, 1e-4)
    assert f == pytest.approx(0.01852, rel=0.02)
    # sanity: smooth-pipe (e/D = 0) is slightly lower at the same Re
    assert colebrook_white(1e5, 0.0) < f


def test_colebrook_fully_rough_limit():
    # large Re, e/D = 0.01  ->  f approaches von Karman rough value ~0.0379
    f = colebrook_white(1e9, 0.01)
    vk = 1.0 / (-2.0 * math.log10(0.01 / 3.7)) ** 2
    assert f == pytest.approx(vk, rel=1e-3)


def test_darcy_weisbach_basic():
    hf = darcy_weisbach_hf(f=0.02, length=1000.0, d=0.3, v=2.0, g=9.81)
    assert hf == pytest.approx(0.02 * (1000 / 0.3) * 4.0 / (2 * 9.81))


def test_hazen_williams_reasonable():
    # 300 mm, C=140, Q=0.05 m3/s (v~0.7 m/s), L=1000 m -> ~1.5 m loss
    hf = hazen_williams_hf(0.05, 1000.0, 0.3, 140.0)
    assert 1.0 < hf < 3.0
    # doubling flow raises loss by ~2^1.852
    assert hazen_williams_hf(0.10, 1000.0, 0.3, 140.0) / hf == pytest.approx(2 ** 1.852, rel=1e-3)


def test_velocity_and_reynolds_roundtrip():
    v = velocity(0.3, 0.4028)
    assert v == pytest.approx(2.354, rel=1e-3)
    re = reynolds(v, 0.4028, 0.8007e-6)
    assert re == pytest.approx(1.184e6, rel=1e-2)
