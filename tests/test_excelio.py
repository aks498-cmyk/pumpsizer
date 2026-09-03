import pytest

openpyxl = pytest.importorskip("openpyxl")

from pumpsizer.excelio import (  # noqa: E402
    read_project,
    run_workbook,
    write_input_template,
)
from pumpsizer.project import Project  # noqa: E402


def test_template_roundtrips_into_a_runnable_project(tmp_path):
    tpl = tmp_path / "input.xlsx"
    write_input_template(tpl)
    data = read_project(tpl)
    assert data["project"]["name"]
    assert data["flow"]["total_demand_lps"] == 300
    assert data["pipe"]["material"] == "ductile_iron"
    assert len(data["segments"]) == 4
    assert data["fittings"]["discharge"]["non_return_valve"] == 1

    res = Project.from_dict(data).run()
    assert 200 < res.operating_point.flow_lps < 380
    assert res.motor.rated_kw > 0


def test_run_workbook_writes_all_sheets(tmp_path):
    tpl = tmp_path / "in.xlsx"
    write_input_template(tpl)
    out = tmp_path / "out.xlsx"
    res = run_workbook(tpl, out)
    wb = openpyxl.load_workbook(out)
    assert {"Summary", "Curves", "EPANET", "Surge", "Report"} <= set(wb.sheetnames)
    # EPANET sheet carries the pasteable block
    epanet_text = "\n".join(str(c[0].value) for c in wb["EPANET"].iter_rows())
    assert "[PUMPS]" in epanet_text and "[CURVES]" in epanet_text
    assert res.surge is not None


def test_edited_template_values_take_effect(tmp_path):
    tpl = tmp_path / "in.xlsx"
    write_input_template(tpl)
    wb = openpyxl.load_workbook(tpl)
    ws = wb["Input"]
    for row in ws.iter_rows(min_row=2):
        if row[1].value == "flow.total_demand_lps":
            row[2].value = 150
    wb.save(tpl)

    data = read_project(tpl)
    assert data["flow"]["total_demand_lps"] == 150
    res = Project.from_dict(data).run()
    assert res.operating_point.flow_lps < 250  # lower demand -> lower duty
