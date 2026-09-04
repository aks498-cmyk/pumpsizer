import csv
from pathlib import Path

from pumpsizer.catalog import Catalog, PumpModel
from pumpsizer.catalog_qa import (
    check_catalog,
    summarise,
    verification_rows,
    verification_status,
    write_checklist,
)

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


def test_verification_status_and_checklist(tmp_path):
    cat = Catalog.bundled()
    st = verification_status(cat)
    assert st["TOTAL"]["to_check"] > 250  # all digitised entries start unverified
    assert st["TOTAL"]["verified"] == 0
    # illustrative (non-digitised) entries are neither verified nor "to check"
    assert st["WS"]["other"] >= 4

    rows = verification_rows(cat, check_catalog(cat))
    assert len(rows) == st["TOTAL"]["to_check"]
    assert set(rows[0]) >= {"model", "datasheet_page", "shutoff_head_m", "verdict"}
    assert all(r["verdict"] == "" for r in rows)  # blank for the human to fill

    out = tmp_path / "chk.csv"
    n = write_checklist(cat, out, check_catalog(cat))
    with out.open(encoding="utf-8") as fh:
        got = list(csv.DictReader(fh))
    assert len(got) == n == len(rows)
    assert "checked_by" in got[0] and "qa" in got[0]


def test_verified_entry_drops_off_the_checklist():
    m = PumpModel(
        manufacturer="KSB",
        series="Omega",
        model="x",
        reference_speed_rpm=1450,
        q_lps=[0, 100, 200],
        h_m=[30, 27, 20],
        digitised=True,
        verified=True,
    )
    cat = Catalog([m])
    assert verification_rows(cat) == []
    assert verification_status(cat)["Omega"] == {"verified": 1, "to_check": 0, "other": 0}
