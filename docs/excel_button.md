---
title: The Excel "Run" button
---

# Driving the engine from a button in the workbook

The workbook stays the interface; a Form Control button on the **Input** sheet
runs the Python engine and writes the results back. This uses
[xlwings](https://www.xlwings.org/) and needs Python on the machine that clicks
the button. Everything else in `pumpsizer` works with plain Python — the button
is optional sugar.

`pumpsizer excel-addin --out excel_button/` drops the three pieces:
`pumpsizer.bas` (the macro), `pumpsizer_inputs.xlsx` (a fresh input template)
and `README.txt` (this, condensed).

## One-time setup (per machine)

1. **Install Python 3.10+** and the engine with the xlwings extra:

   ```bash
   pip install "pumpsizer[xlwings]"
   ```

2. **Install the xlwings add-in** — this is what gives the workbook the
   `RunPython` function:

   ```bash
   xlwings addin install
   ```

   Restart Excel. (If your IT blocks add-ins, the `xlwings.bas` module imported
   manually works too — see the xlwings docs.)

3. **Make the workbook macro-enabled.** Open `pumpsizer_inputs.xlsx` (or your
   filled-in copy) and *Save As* → `Excel Macro-Enabled Workbook (*.xlsm)`.

4. **Import the macro.** Developer ▸ Visual Basic ▸ File ▸ Import File… ▸
   `pumpsizer.bas`. You should see a module named `pumpsizer` with one sub,
   `RunPumpsizer`. It calls `RunPython` via `Application.Run "xlwings.xlam!…"`,
   so the workbook needs **no** Tools ▸ References entry for xlwings — just the
   loaded add-in from step 2.

5. **Add the button.** On the Input sheet: Developer ▸ Insert ▸ Form Control ▸
   Button. Draw it, and in the "Assign Macro" dialog pick `RunPumpsizer`. The
   first click is slow (~30 s) while Python and SciPy load; later runs are quick.

### Shortcut: a ready-made `.xlsm`

Steps 3–5 can be scripted on Windows if Excel's *Trust Center ▸ Macro Settings ▸
Trust access to the VBA project object model* is ticked. From the folder
`pumpsizer excel-addin` produced:

```python
import pathlib, win32com.client as w                       # pywin32
d = pathlib.Path(".")                                       # the excel-addin folder
xl = w.DispatchEx("Excel.Application"); xl.DisplayAlerts = False
wb = xl.Workbooks.Open(str(d / "pumpsizer_inputs.xlsx"))
wb.VBProject.VBComponents.Import(str(d / "pumpsizer.bas"))  # embed the macro
b = wb.Worksheets("Input").Buttons().Add(320, 5, 150, 26)   # place the button
b.Text, b.OnAction = "Run pumpsizer", "RunPumpsizer"
wb.SaveAs(str(d / "pumpsizer.xlsm"), FileFormat=52); wb.Close(False); xl.Quit()
```

The resulting `pumpsizer.xlsm` opens with the button already on the Input sheet —
the user just enables macros and clicks.

## Using it

1. Fill the **Input** sheet (and the `Segments` / `Fittings` sheets if present).
2. Click the button. (First click ~30 s; nothing shows until it finishes.)
3. The engine writes `<workbook-name>-results.xlsx` next to the workbook and
   brings it to the front — Summary, Curves, EPANET, Surge, Report sheets,
   exactly as `pumpsizer excel` produces headless.
4. A status line lands in **`Input!F1`**, e.g.
   `ran 2026-09-04 17:22: 255.8 l/s @ 30.7 m, eff 84%  ->  pumpsizer-results.xlsx`.

Verified end-to-end on a Windows + Excel machine: the button runs the full
`Project.run()` pipeline and writes the results workbook.

The button calls `pumpsizer.xlwings_addin.run()`, which just saves the live
workbook and hands the file to the same `excelio.run_workbook` the CLI uses —
so the template and the original `Pump Sizing.xlsx` layout (auto-detected: no
clean `Input` sheet ⇒ legacy) both work.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Compile error: Sub or Function not defined` on `RunPython` | Old macro that called `RunPython` bare — re-import the current `pumpsizer.bas` (it uses `Application.Run "xlwings.xlam!RunPython"`), or add xlwings under Tools ▸ References. |
| Button does nothing, no results file | xlwings add-in not loaded (step 2 / restart Excel), or the file opened in LibreOffice/another editor instead of Excel — open it with Excel explicitly. |
| `No module named pumpsizer` | `pip install` ran in a different Python than xlwings uses. Set `Interpreter_Win` in the xlwings ribbon, or `PYTHONPATH` via `xlwings config`. |
| `MsgBox: pumpsizer failed: …` | The engine raised — run `pumpsizer excel <file>.xlsm` in a terminal to see the full traceback. |
| Results file "in use" | Close a previously opened `*-results.xlsx` before re-running. |
