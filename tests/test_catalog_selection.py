import numpy as np
import pytest

from pumpsizer.catalog import Catalog, PumpModel
from pumpsizer.pipes import PipeSegment
from pumpsizer.project import Project
from pumpsizer.selection import SelectionCriteria, evaluate, select
from pumpsizer.system import MinorLoss, SystemCurve

EXAMPLE = __import__("pathlib").Path(__file__).resolve().parents[1] / "examples" / "potable_water_pumping_station.yaml"


def _system(static=24.0):
    seg = PipeSegment("rm", 500.0, 402.8, 0.06, 140.0)
    return SystemCurve(static_head=static, segments=[seg],
                       minor_losses=[MinorLoss("d", 8.2, 402.8)],
                       kinematic_viscosity=0.8007e-6, method="DW")


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
    cat = Catalog.bundled()
    crit = SelectionCriteria.from_duty(300, 33, system_curve=_system(), npsh_available_m=9.0)
    ranked = select(cat, crit)
    assert ranked, "expected at least one feasible pump"
    assert "300-34" in ranked[0].model.key       # the BEP-matched one wins


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
        manufacturer="T", series="V", model="x",
        reference_speed_rpm=1480, max_speed_ratio=1.2,
        q_lps=[0, 150, 300, 400], h_m=[34, 32, 28, 20],
        eff_pct=[0, 70, 82, 70], npshr_m=[0, 2, 3, 5],
        impeller_diameter_mm=400, min_impeller_diameter_mm=340)
    crit = SelectionCriteria.from_duty(300, 33, allow_trim=False)
    cand = evaluate(m, crit)
    assert cand.method == "vfd" and cand.speed_ratio > 1.0


def test_ksb_omega_envelope_catalogue():
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "src/pumpsizer/data/catalog/ksb_omega_50hz.yaml"
    cat = Catalog.from_path(p)
    assert len(cat) > 50
    m = cat.models[0]
    assert m.envelope_only and not m.verified and m.datasheet_page
    # an envelope model still yields a usable synthetic curve
    curve = m.to_pump_curve()
    assert curve.head(0.0) > curve.head(m.q_bep_lps / 1000.0) > 0

    crit = SelectionCriteria.from_duty(300, 33, npsh_available_m=9.0)
    ranked = select(cat, crit, top=5)
    assert ranked and ranked[0].feasible
    # the shortlist must flag that the curve needs confirming, and be penalised
    assert any("confirm curve" in r for r in ranked[0].reasons)
    assert ranked[0].score < 0.95
    # DN350-ish pump for ~1000 m3/h @ 33 m
    assert "350-" in ranked[0].model.model or "300-" in ranked[0].model.model


def test_project_catalogue_source_runs():
    data = {**Project.from_yaml(EXAMPLE).data}
    data["pump"] = {"source": "catalogue"}      # -> bundled illustrative catalogue
    res = Project.from_dict(data).run()
    assert res.selection is not None and len(res.selection) >= 4
    assert res.operating_point.flow_lps > 200
    assert any("selected" in w for w in res.warnings)
