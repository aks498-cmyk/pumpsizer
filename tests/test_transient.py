import numpy as np

from pumpsizer.surge import wave_celerity
from pumpsizer.transient import (
    AirVessel,
    Pipeline,
    PumpInertia,
    simulate_pump_trip,
)


def _case(length=2000.0, static=24.0, reaches=20, f=0.017):
    a = wave_celerity(0.4028, 0.0169, 170e9)
    pipe = Pipeline(length, 0.4028, a, f, 0.0, static, reaches)
    pump = PumpInertia(1480, 0.30, 33.0, total_inertia_kgm2=5.0, rated_efficiency=0.83)
    return pipe, pump


def test_steady_state_is_consistent():
    pipe, pump = _case()
    r = simulate_pump_trip(pipe, pump, sump_level_m=0.0, reservoir_level_m=24.0, duration_s=1.0)
    # step 0 is the steady solution: pump head - static = friction, all Q equal
    q0 = r.flow_pump_m3s[0]
    assert 0.15 < q0 < 0.35
    assert r.head_pump_m[0] > 24.0


def test_unprotected_long_main_separates_and_needs_protection():
    pipe, pump = _case(length=2500.0)
    r = simulate_pump_trip(pipe, pump, sump_level_m=0.0, reservoir_level_m=24.0, duration_s=40.0)
    min_gauge = float(np.min(r.envelope_min_m - r.node_elevation_m))
    assert min_gauge < -8.0  # approaches full vacuum
    assert r.vapour_anywhere is True
    assert any("check valve" in n for n in r.notes)


def test_air_vessel_reduces_the_downsurge():
    pipe, pump = _case(length=2500.0)
    base = simulate_pump_trip(pipe, pump, sump_level_m=0.0, reservoir_level_m=24.0, duration_s=40.0)
    prot = simulate_pump_trip(
        pipe,
        pump,
        sump_level_m=0.0,
        reservoir_level_m=24.0,
        duration_s=40.0,
        air_vessel=AirVessel(gas_volume_m3=25.0),
    )
    assert prot.min_head_m > base.min_head_m + 3.0
    assert prot.vapour_anywhere is False
    assert prot.air_vessel_gas_volume_m3 is not None
    assert prot.air_vessel_gas_volume_m3.max() > 25.0  # gas expands on the down-surge


def test_bigger_vessel_gives_smaller_surge():
    pipe, pump = _case(length=2500.0)
    hi = []
    for v in (6.0, 12.0, 25.0):
        r = simulate_pump_trip(
            pipe,
            pump,
            sump_level_m=0.0,
            reservoir_level_m=24.0,
            duration_s=50.0,
            air_vessel=AirVessel(gas_volume_m3=v),
        )
        hi.append(r.max_head_m)
    # surge above the steady operating head shrinks as the vessel grows
    assert hi[0] >= hi[1] >= hi[2]
    assert hi[0] - hi[2] > 2.0


def test_result_dict_shape():
    pipe, pump = _case()
    d = simulate_pump_trip(
        pipe, pump, sump_level_m=0.0, reservoir_level_m=24.0, duration_s=20.0
    ).as_dict()
    for k in (
        "max_head_m",
        "min_head_m",
        "min_gauge_pressure_head_m",
        "vapour_separation",
        "duration_s",
    ):
        assert k in d


def test_project_moc_block(tmp_path):
    import yaml

    from pumpsizer.project import Project

    base = yaml.safe_load(
        (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "examples"
            / "potable_water_pumping_station.yaml"
        ).read_text()
    )
    base["water_hammer"] = {
        "enabled": True,
        "method": "moc",
        "moc_reaches": 16,
        "pressure_class_pn": 16,
    }
    res = Project.from_dict(base).run()
    assert res.surge is not None and res.surge.transient is not None
    assert res.surge.transient["max_head_m"] > res.surge.static_head_m
