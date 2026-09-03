from pumpsizer.epanet import build_pump_export
from pumpsizer.inpfile import InpModel
from pumpsizer.pumpcurve import PumpCurve

BASE = """[TITLE]
demo
[JUNCTIONS]
 J1  \t8  0
[RESERVOIRS]
 RSUC \t8
 RDIS \t32
[PIPES]
 RM  \tJ1\tRDIS\t500\t402.8\t0.06\t0\tOpen
[PUMPS]
 PMP1 \tRSUC\tJ1\tHEAD OLDC
[CURVES]
 OLDC\t0\t50
 OLDC\t300\t20
[ENERGY]
 GLOBAL EFFIC 75
[OPTIONS]
 UNITS  LPS
 HEADLOSS  D-W
[END]
"""


def test_parse_and_roundtrip_preserves_unknown_sections():
    m = InpModel.parse(BASE)
    assert m.flow_units == "LPS"
    assert m.headloss == "D-W"
    txt = m.to_text()
    assert "[JUNCTIONS]" in txt and "[PIPES]" in txt
    assert "RM" in txt and "RDIS" in txt


def test_pump_records():
    m = InpModel.parse(BASE)
    pumps = m.pumps
    assert len(pumps) == 1
    assert pumps[0].id == "PMP1"
    assert pumps[0].params["HEAD"] == "OLDC"


def test_apply_export_replaces_curve_and_pump_once():
    m = InpModel.parse(BASE)
    p = PumpCurve.synthetic(0.3, 33.0, eff_bep=84.0, name="WS300")
    exp = build_pump_export(p, pump_id="PMP1", from_node="RSUC", to_node="J1",
                            flow_units="LPS", head_points=3)
    m.apply_export(exp)
    txt = m.to_text()
    # exactly one PMP1 line, now pointing at the new curve
    pump_lines = [ln for ln in m.sections["PUMPS"] if ln.split()[:1] == ["PMP1"]]
    assert len(pump_lines) == 1
    assert exp.head_curve_id in pump_lines[0]
    # new curve present; the pump no longer references OLDC (which is left in
    # place - it may be shared - but is now orphaned)
    assert any(exp.head_curve_id in ln for ln in m.sections["CURVES"])
    assert "OLDC" not in pump_lines[0]
    # efficiency wired into ENERGY
    assert any("EFFIC" in ln and "PMP1" in ln for ln in m.sections["ENERGY"])
    assert "GLOBAL EFFIC 75" in txt          # untouched global line kept


def test_upsert_curve_dedupes():
    m = InpModel.parse(BASE)
    m.upsert_curve("OLDC", [(0, 40), (100, 35), (200, 25)])
    rows = [ln for ln in m.sections["CURVES"] if ln.split()[:1] == ["OLDC"]]
    assert len(rows) == 3
