import pytest

from pumpsizer.fluid import (
    atmospheric_pressure,
    kinematic_viscosity,
    vapour_pressure,
    water_properties,
)


def test_kinematic_viscosity_matches_workbook_table():
    # workbook Viscousity sheet: 30 degC -> 0.8007e-6 m2/s
    assert kinematic_viscosity(30) == pytest.approx(0.8007e-6, rel=1e-4)
    assert kinematic_viscosity(20) == pytest.approx(1.0035e-6, rel=1e-4)


def test_vapour_pressure_monotonic_and_scale():
    assert vapour_pressure(20) == pytest.approx(2339, rel=0.02)
    assert vapour_pressure(80) > vapour_pressure(30) > vapour_pressure(10)


def test_atmospheric_pressure_drops_with_altitude():
    assert atmospheric_pressure(0) == pytest.approx(101325, rel=1e-6)
    assert atmospheric_pressure(1500) == pytest.approx(84_560, rel=0.02)
    assert atmospheric_pressure(3000) < atmospheric_pressure(1500)


def test_water_properties_bundle_heads():
    w = water_properties(30, 0)
    assert w.atmospheric_pressure_head == pytest.approx(10.33, rel=0.02)
    assert 0.3 < w.vapour_pressure_head < 0.6
