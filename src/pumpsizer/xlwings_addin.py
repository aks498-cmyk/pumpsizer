"""The "Run pumpsizer" button for the Excel input workbook (via xlwings).

The workbook keeps its role as the UI; this is the glue that lets a button in
it call the engine.  The button's VBA is one line::

    Sub RunPumpsizer()
        RunPython "import pumpsizer.xlwings_addin as m; m.run()"
    End Sub

``run()`` saves the calling workbook, hands the file to the headless
:func:`pumpsizer.excelio.run_workbook` (which already parses every sheet of the
template - or the original ``Pump Sizing.xlsx`` layout with ``--legacy``), then
opens the ``*-results.xlsx`` it writes and drops a one-line status back on the
Input sheet.

Nothing here is imported unless the button fires - ``xlwings`` is a desktop-only
dependency and is not needed for the rest of the package.  One-time setup:
``docs/excel_button.md`` (or ``pumpsizer excel-addin --out <dir>``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .excelio import run_workbook

# VBA module dropped by ``pumpsizer excel-addin`` and documented in
# docs/excel_button.md.  Kept here so the two never drift.
BUTTON_BAS = """\
Attribute VB_Name = "pumpsizer"
' pumpsizer - "Run" button macro.
'
' Setup (once per machine):
'   1. Install Python + the engine:  pip install "pumpsizer[xlwings]"
'   2. Install the xlwings add-in:    xlwings addin install
'      (gives this workbook the RunPython function used below)
'   3. In Excel: Developer > Visual Basic > File > Import File... > this .bas
'   4. On the Input sheet add a Form Control button and assign RunPumpsizer.
'
' See docs/excel_button.md for the full guide.

Sub RunPumpsizer()
    On Error GoTo Fail
    RunPython "import pumpsizer.xlwings_addin as m; m.run()"
    Exit Sub
Fail:
    MsgBox "pumpsizer failed: " & Err.Description, vbExclamation, "pumpsizer"
End Sub
"""


def _is_legacy(path: str | Path) -> bool:
    """True for the original ``Pump Sizing.xlsx``.  Both layouts have a sheet
    named ``Input``; the template's has dotted schema keys in column B, the
    legacy one has free-text labels in column A - so tell them apart by B2."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        if "Input" not in wb.sheetnames:
            return True
        b2 = wb["Input"]["B2"].value
        return not (isinstance(b2, str) and "." in b2)
    finally:
        wb.close()


def run(book=None) -> str:
    """Entry point for the workbook button.  Returns the results-file path."""
    if book is None:
        import xlwings as xw

        book = xw.Book.caller()
    src = Path(book.fullname)
    book.save()

    legacy = _is_legacy(src)
    out = src.with_name(f"{src.stem}-results.xlsx")
    res = run_workbook(src, out, legacy=legacy)

    op = res.operating_point
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    status = (
        f"ran {stamp}: {op.flow_lps:.1f} l/s @ {op.head_m:.1f} m, "
        f"eff {op.efficiency_pct:.0f}%  ->  {out.name}"
    )
    try:
        book.sheets["Input"].range("F1").value = status
    except Exception:  # pragma: no cover - cosmetic only
        pass

    try:  # pragma: no cover - desktop only
        import xlwings as xw

        xw.Book(str(out))  # bring the results workbook to the front
    except Exception:
        pass
    return str(out)
