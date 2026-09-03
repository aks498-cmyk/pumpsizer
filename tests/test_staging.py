import numpy as np
import pytest

from pumpsizer.pipes import PipeSegment
from pumpsizer.project import Project
from pumpsizer.pumpcurve import PumpCurve
from pumpsizer.staging import (
    DEFAULT_DIURNAL,
    DemandPattern,
    StagingConfig,
    Tank,
    simulate_staging,
)
from pumpsizer.system import MinorLoss, SystemCurve

EXAMPLE = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "examples"
    / "potable_water_pumping_station.yaml"
)


def _sys(static=24.0):
    seg = PipeSegment("rm", 500.0, 402.8, 0.30, 140.0)
    return SystemCurve(
        static_head=static,
        segments=[seg],
        minor_losses=[MinorLoss("d", 8.2, 402.8)],
        kinematic_viscosity=0.8007e-6,
        method="DW",
        label="design",
    )


def test_diurnal_pattern_normalisation():
    p_avg = DemandPattern.diurnal(0.3, kind="average")
    assert np.mean(p_avg.multipliers) == pytest.approx(1.0, rel=1e-9)
    p_pk = DemandPattern.diurnal(0.3, kind="peak")
    assert max(p_pk.multipliers) == pytest.approx(1.0, rel=1e-9)
    assert len(DEFAULT_DIURNAL) == 24


def test_vfd_mode_tracks_demand_and_stages_up():
    pump = PumpCurve.synthetic(0.17, 30.0, eff_bep=82.0, name="p")
    tank = Tank(250, 25, 32)
    dem = DemandPattern.diurnal(0.30, kind="peak")
    r = simulate_staging(
        pump,
        _sys(),
        tank,
        dem,
        StagingConfig(n_pumps_available=3, mode="vfd", vfd_min_speed=0.6),
        base_static_reference_level_m=31.0,
    )
    dmd = r.array("demand_m3s")
    dlv = r.array("flow_delivered_m3s")
    assert np.allclose(dlv, dmd, atol=2e-3)  # VFD meets demand each step
    assert r.array("running_pumps").max() >= 2  # stages up at the peak
    assert r.unmet_demand_steps == 0


def test_fixed_mode_cycles_the_tank_and_counts_starts():
    pump = PumpCurve.synthetic(0.20, 30.0, eff_bep=82.0, name="p")
    tank = Tank(200, 25, 32)
    dem = DemandPattern.diurnal(0.30, kind="peak")
    r = simulate_staging(
        pump,
        _sys(),
        tank,
        dem,
        StagingConfig(n_pumps_available=3, mode="fixed"),
        base_static_reference_level_m=31.0,
    )
    lv = r.array("tank_level_m")
    assert lv.max() - lv.min() > 1.0  # tank actually cycles
    assert sum(r.per_pump_starts) >= 2
    assert r.per_pump_run_hours[2] <= r.per_pump_run_hours[0]  # standby used least


def test_undersized_station_flags_unmet_demand():
    pump = PumpCurve.synthetic(0.10, 25.0, eff_bep=80.0, name="small")
    r = simulate_staging(
        pump,
        _sys(),
        Tank(150, 25, 32),
        DemandPattern.diurnal(0.40, kind="peak"),
        StagingConfig(n_pumps_available=2, mode="fixed"),
        base_static_reference_level_m=31.0,
    )
    assert r.unmet_demand_steps > 0
    assert any("meet demand" in w for w in r.warnings)


def test_project_staging_block_runs():
    res = Project.from_yaml(EXAMPLE).run()
    assert res.staging is not None
    s = res.staging.summary()
    assert s["daily_energy_kwh"] > 0
    assert len(res.staging.steps) == 24
