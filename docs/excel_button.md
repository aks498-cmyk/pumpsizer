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

1. **Install Python 3.10+** and the engine with the Excel extras:

   ```bash
   pip install "pumpsizer[excel]" xlwings
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
   `RunPumpsizer`.

5. **Add the button.** On the Input sheet: Developer ▸ Insert ▸ Form Control ▸
   Button. Draw it, and in the "Assign Macro" dialog pick `RunPumpsizer`.

## Using it

1. Fill the **Input** sheet (and the `Segments` / `Fittings` sheets if present).
2. Click the button.
3. The engine writes `<workbook-name>-results.xlsx` next to the workbook and
   brings it to the front — Summary, Curves, EPANET, Selection, Surge, Report
   sheets, exactly as `pumpsizer excel` produces headless.
4. A status line lands in **`Input!F1`**, e.g.
   `ran 2026-09-04 18:20: 305.4 l/s @ 33.1 m, eff 86%  ->  station-results.xlsx`.

The button calls `pumpsizer.xlwings_addin.run()`, which just saves the live
workbook and hands the file to the same `excelio.run_workbook` the CLI uses —
so the template and the original `Pump Sizing.xlsx` layout (auto-detected: no
clean `Input` sheet ⇒ legacy) both work.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `RunPython` not defined | xlwings add-in not installed / Excel not restarted (step 2). |
| `No module named pumpsizer` | `pip install` ran in a different Python than xlwings uses. Set `Interpreter_Win` in the xlwings ribbon, or `PYTHONPATH` via `xlwings config`. |
| `MsgBox: pumpsizer failed: …` | The engine raised — run `pumpsizer excel <file>.xlsm` in a terminal to see the full traceback. |
| Results file "in use" | Close a previously opened `*-results.xlsx` before re-running. |
