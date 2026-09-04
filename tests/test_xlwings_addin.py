"""The xlwings button glue, exercised without Excel or xlwings via a fake book."""

import pytest

openpyxl = pytest.importorskip("openpyxl")

from pumpsizer.cli import main  # noqa: E402
from pumpsizer.excelio import write_input_template  # noqa: E402
from pumpsizer.xlwings_addin import BUTTON_BAS, _is_legacy, run  # noqa: E402


class _Cell:
    def __init__(self):
        self.value = None


class _Sheet:
    def __init__(self, name):
        self.name = name
        self._cells = {}

    def range(self, addr):
        return self._cells.setdefault(addr, _Cell())


class _Sheets:
    def __init__(self, names):
        self._s = [_Sheet(n) for n in names]

    def __iter__(self):
        return iter(self._s)

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._s[k]
        return next(s for s in self._s if s.name == k)


class _Book:
    def __init__(self, path, names):
        self.fullname = str(path)
        self.sheets = _Sheets(names)
        self.saved = 0

    def save(self):
        self.saved += 1


def test_is_legacy_detection(tmp_path):
    tpl = tmp_path / "template.xlsx"
    write_input_template(tpl)
    assert _is_legacy(tpl) is False  # dotted schema keys in column B

    wb = openpyxl.Workbook()
    wb.active.title = "Input"
    wb["Input"]["A2"] = "Total demand (l/s)"  # legacy: label in A, value in D
    wb["Input"]["D2"] = 300
    legacy = tmp_path / "legacy.xlsx"
    wb.save(legacy)
    assert _is_legacy(legacy) is True

    wb2 = openpyxl.Workbook()
    wb2.active.title = "Data"
    other = tmp_path / "other.xlsx"
    wb2.save(other)
    assert _is_legacy(other) is True  # no Input sheet at all


def test_button_bas_is_wired():
    assert "Sub RunPumpsizer()" in BUTTON_BAS
    assert 'RunPython "import pumpsizer.xlwings_addin as m; m.run()"' in BUTTON_BAS


def test_run_drives_the_engine_and_writes_results(tmp_path):
    src = tmp_path / "station.xlsx"
    write_input_template(src)
    book = _Book(src, ["Input", "Segments", "Fittings"])

    out = run(book=book)

    assert book.saved == 1
    assert out.endswith("station-results.xlsx")
    wb = openpyxl.load_workbook(out)
    assert {"Summary", "Curves", "EPANET"} <= set(wb.sheetnames)
    status = book.sheets["Input"].range("F1").value
    assert status and "l/s @" in status and "station-results.xlsx" in status


def test_excel_addin_cli_emits_the_pieces(tmp_path):
    d = tmp_path / "btn"
    assert main(["excel-addin", "--out", str(d)]) == 0
    assert (d / "pumpsizer.bas").read_text(encoding="utf-8").startswith("Attribute VB_Name")
    assert (d / "pumpsizer_inputs.xlsx").exists()
    assert "xlwings addin install" in (d / "README.txt").read_text(encoding="utf-8")
