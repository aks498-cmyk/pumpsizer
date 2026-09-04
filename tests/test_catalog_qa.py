from pathlib import Path

from pumpsizer.catalog import Catalog, PumpModel
from pumpsizer.catalog_qa import check_catalog, summarise

_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_catalogue_has_no_failures():
    """The shipped digitised catalogues must pass QA (WARN is allowed)."""
    findings = check_catalog(Catalog.bundled())
    fails = [f for f in findings if f.level == "FAIL"]
    assert not fails, "\n".join(str(f) for f in fails)


def test_qa_flags_a_broken_shape():
    bad = PumpModel(
        manufacturer="T",
        series="X",
        model="rising-head",
        reference_speed_rpm=1450,
        q_lps=[0, 100, 200, 300],
        h_m=[30, 32, 34, 36],  # head rises with flow -> FAIL
    )
    findings = check_catalog(Catalog([bad]))
    assert any(f.level == "FAIL" and f.check == "shape" for f in findings)


def test_qa_flags_speed_affinity_outlier():
    lo = PumpModel(
        manufacturer="T",
        series="X",
        model="A ø200 (1450rpm)",
        reference_speed_rpm=1450,
        impeller_diameter_mm=200,
        q_lps=[0, 100, 200],
        h_m=[20, 18, 14],
    )
    hi = PumpModel(
        manufacturer="T",
        series="X",
        model="A ø200 (2900rpm)",
        reference_speed_rpm=2900,
        impeller_diameter_mm=200,
        q_lps=[0, 100, 200],
        h_m=[120, 108, 84],  # ~6x, should be ~4x -> FAIL
    )
    findings = check_catalog(Catalog([lo, hi]))
    assert any(f.check == "affinity-n" and f.level == "FAIL" for f in findings)


def test_qa_multistage_per_stage_consistency():
    p = _ROOT / "src/pumpsizer/data/catalog/ksb_multitec_50hz.yaml"
    cat = Catalog.from_path(p)
    findings = check_catalog(cat)
    assert not [f for f in findings if f.level == "FAIL"]
    s = summarise(findings)
    assert s["OK"] + s["WARN"] + s["FAIL"] == len(findings)
