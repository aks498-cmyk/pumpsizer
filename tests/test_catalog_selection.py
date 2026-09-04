from pathlib import Path

import pytest

from pumpsizer.catalog import Catalog, PumpModel
from pumpsizer.pipes import PipeSegment
from pumpsizer.project import Project
from pumpsizer.selection import SelectionCriteria, evaluate, select
from pumpsizer.system import MinorLoss, SystemCurve

_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = _ROOT / "examples" / "potable_water_pumping_station.yaml"
ILLUSTRATIVE = _ROOT / "src/pumpsizer/data/catalog/_example_water_pumps.yaml"


def _system(static=24.0):
    seg = PipeSegment("rm", 500.0, 402.8, 0.06, 140.0)
    return SystemCurve(
        static_head=static,
        segments=[seg],
        minor_losses=[MinorLoss("d", 8.2, 402.8)],
        kinematic_viscosity=0.8007e-6,
        method="DW",
    )


def test_bundled_catalogue_loads():
    cat = Catalog.bundled()
    assert len(cat) >= 4
    m = cat.get("250-30")
    assert m.manufacturer == "Example"
    assert m.trim_limit_ratio == pytest.approx(270 / 320, rel=1e-6)


def test_model_to_pump_curve_roundtrip():
    m = Catalog.bundled().get("300-34")
    p = m.to_pump_curve()
    assert p.head(0.0) == pytest.approx(38, abs=1.5)
    assert p.head(0.3) == pytest.approx(33, abs=1.5)


def test_selection_prefers_bep_matched_pump():
    cat = Catalog.from_path(ILLUSTRATIVE)  # small controlled set
    crit = SelectionCriteria.from_duty(300, 33, system_curve=_system(), npsh_available_m=9.0)
    ranked = select(cat, crit)
    assert ranked, "expected at least one feasible pump"
    assert "300-34" in ranked[0].model.key  # the BEP-matched one wins


def test_illustrative_pumps_are_penalised_vs_real_data():
    cat = Catalog.bundled()  # digitised KSB Omega + illustrative
    crit = SelectionCriteria.from_duty(300, 33, system_curve=_system(), npsh_available_m=9.0)
    top = select(cat, crit, top=5)
    assert "illustrative" not in top[0].model.tags  # a real KSB pump wins
    assert "KSB" in top[0].model.manufacturer


def test_oversized_pump_gets_trimmed():
    cat = Catalog.bundled()
    crit = SelectionCriteria.from_duty(300, 33, system_curve=_system(), allow_trim=True)
    cand = evaluate(cat.get("350-42"), crit)
    assert cand.feasible and cand.method == "trim"
    assert 0.80 <= cand.trim_ratio < 1.0


def test_undersized_pump_infeasible():
    cat = Catalog.bundled()
    crit = SelectionCriteria.from_duty(300, 33)
    cand = evaluate(cat.get("250-30"), crit)
    assert cand.feasible is False


def test_vfd_pump_can_speed_up_when_needed():
    m = PumpModel(
        manufacturer="T",
        series="V",
        model="x",
        reference_speed_rpm=1480,
        max_speed_ratio=1.2,
        q_lps=[0, 150, 300, 400],
        h_m=[34, 32, 28, 20],
        eff_pct=[0, 70, 82, 70],
        npshr_m=[0, 2, 3, 5],
        impeller_diameter_mm=400,
        min_impeller_diameter_mm=340,
    )
    crit = SelectionCriteria.from_duty(300, 33, allow_trim=False)
    cand = evaluate(m, crit)
    assert cand.method == "vfd" and cand.speed_ratio > 1.0


def test_ksb_omega_digitised_catalogue():
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "src/pumpsizer/data/catalog/ksb_omega_50hz.yaml"
    cat = Catalog.from_path(p)
    assert len(cat) > 50
    m = cat.models[0]
    assert m.digitised and not m.verified and m.datasheet_page
    # real digitised curve: descending head, rising-ish NPSHr, BEP efficiency
    assert m.q_lps and m.h_m and m.h_m[0] > m.h_m[-1] > 0
    curve = m.to_pump_curve()
    qb, hb, eb = curve.bep()
    assert curve.head(0.0) > hb > 0
    assert 40 < eb < 96  # efficiency parabola from eff_bep_pct

    crit = SelectionCriteria.from_duty(300, 33, npsh_available_m=9.0)
    ranked = select(cat, crit, top=5)
    assert ranked and ranked[0].feasible
    # digitised entries are flagged for confirmation and lightly penalised
    assert any("machine-digitised" in r for r in ranked[0].reasons)
    assert ranked[0].score < 0.98
    # a DN300/350 pump for ~1000 m3/h @ 33 m
    assert ranked[0].model.discharge_dn >= 250


def test_ksb_multitec_digitised_catalogue():
    p = _ROOT / "src/pumpsizer/data/catalog/ksb_multitec_50hz.yaml"
    cat = Catalog.from_path(p)
    assert len(cat) >= 40
    m = cat.models[0]
    assert m.digitised and not m.verified and m.is_multistage
    assert m.stages_max and m.per_stage_head_m and len(m.per_stage_head_m) == len(m.q_lps)
    # curve:h_m is the per-stage head x the max stack
    full = m.to_pump_curve()
    assert full.head(0.0) == pytest.approx(m.per_stage_head_m[0] * m.stages_max, rel=0.02)
    # a chosen stage count scales head pro rata, leaves NPSHr alone
    half = m.to_pump_curve(stages=max(1, m.stages_max // 2))
    assert half.head(0.0) < full.head(0.0)


def test_ksb_multitec_example_end_to_end():
    """The Multitec-driven high-head booster runs the whole pipeline."""
    ex = _ROOT / "examples" / "high_head_booster_ksb_multitec.yaml"
    res = Project.from_yaml(ex).run()
    op = res.operating_point
    assert res.selection and res.selection[0].feasible
    assert "Multitec" in res.pump.name
    assert res.selection[0].model.is_multistage
    assert 1 < res.selection[0].stages <= res.selection[0].model.stages_max
    assert 25 < op.flow_lps < 45
    assert 95 < op.head_m < 135
    assert 60 < op.efficiency_pct < 88
    assert any("stages" in w for w in res.warnings)


def test_multitec_selection_picks_stage_count():
    p = _ROOT / "src/pumpsizer/data/catalog/ksb_multitec_50hz.yaml"
    cat = Catalog.from_path(p)

    hi = select(cat, SelectionCriteria.from_duty(30, 120, npsh_available_m=9.0), top=1)
    lo = select(cat, SelectionCriteria.from_duty(30, 55, npsh_available_m=9.0), top=1)
    assert hi and lo and hi[0].feasible and lo[0].feasible
    # fewer stages for the lower-head duty on the same family, or at least not more
    same = hi[0].model.key == lo[0].model.key
    if same:
        assert lo[0].stages <= hi[0].stages
    assert 1 <= lo[0].stages <= lo[0].model.stages_max
    assert any("stage" in r for r in lo[0].reasons)


def test_project_catalogue_source_runs():
    data = {**Project.from_yaml(EXAMPLE).data}
    data["pump"] = {"source": "catalogue"}  # -> bundled illustrative catalogue
    res = Project.from_dict(data).run()
    assert res.selection is not None and len(res.selection) >= 4
    assert res.operating_point.flow_lps > 200
    assert any("selected" in w for w in res.warnings)


def test_ksb_catalogue_example_end_to_end():
    """The KSB-Omega-driven example runs the whole pipeline on real curves."""
    from pathlib import Path

    ex = Path(__file__).resolve().parents[1] / "examples" / "potable_water_pumping_station_ksb.yaml"
    res = Project.from_yaml(ex).run()
    op = res.operating_point
    assert res.selection and res.selection[0].feasible
    assert "KSB Omega" in res.pump.name
    assert 250 < op.flow_lps < 360
    assert 24 < op.head_m < 45
    assert 70 < op.efficiency_pct < 92  # real digitised efficiency
    assert res.npsh.npsh_required_m and res.npsh.npsh_required_m > 1.0
    assert res.motor.rated_kw in (110, 132, 160, 200)
