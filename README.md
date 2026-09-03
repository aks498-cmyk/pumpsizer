# pumpsizer

Reusable engine for **water-supply pump sizing, operating-point analysis and
EPANET-compatible curve generation**.

Given a duty (head in m, discharge in l/s) and the installation data, it:

1. builds the **system (installation) characteristic** `H_sys(Q)` from pipe
   reaches + minor losses + static lift, for the whole family
   *{min, max static head} × {new, aged roughness}*;
2. produces a **pump characteristic** `H = A − B·Qᶜ` (+ efficiency, + NPSHr) from
   a manufacturer curve, a single duty point (EPANET's 1.33×/2× rule), or a
   synthetic shape;
3. solves the **operating point** — single pump, N in parallel, series, or a
   variable-speed drive trimmed to a target flow;
4. runs the **NPSHa / cavitation-margin** check, sizes the **motor**
   (IEC 60072-1 kW series, IE1–IE4 efficiency), and estimates **energy / LCC**;
5. exports **`[CURVES]` / `[PUMPS]` / `[ENERGY]`** ready to paste into an EPANET
   2.2 `.inp`, or splices them into an existing `.inp`.

It is a clean-room re-implementation of the `Pump Sizing.xlsx` workbook logic,
with corrected Darcy–Weisbach hydraulics (see
[`docs/workbook_mapping.md`](docs/workbook_mapping.md)).

---

## Install

```bash
py -m pip install -e .          # from this folder
py -m pip install -e ".[dev]"   # + pytest, matplotlib, openpyxl
```

Python ≥ 3.10. Runtime deps: `numpy`, `scipy`, `pyyaml` (`matplotlib` only for
`--plot`).

## Quick start

```bash
# full run from a project file
pumpsizer run examples/potable_water_pumping_station.yaml \
    --plot out/perf.png --epanet out/pump.inp --json out/summary.json

# rank catalogue pumps against a duty point (uses the real system curve
# + NPSHa when a project file is given)
pumpsizer select --duty-q 300 --duty-h 33 --npsha 9
pumpsizer select --project examples/potable_water_pumping_station.yaml \
    --catalogue my_catalogue/

# one-off curve + EPANET block from a duty point
pumpsizer curve --duty-q 300 --duty-h 33 --source synthetic --points 3

# rule-of-thumb water-hammer check + air-vessel / flywheel pre-size
pumpsizer surge --length 2500 --material ductile_iron --dn 400 \
    --flow-lps 300 --static 24 --pn 16 --shaft-power-kw 114

# splice the sized pump into a real network and let EPANET solve it
pumpsizer run examples/potable_water_pumping_station.yaml \
    --into examples/network_skeleton.inp --patch-out out/net.inp --simulate

# run EPANET on any .inp and report the pump operating points
pumpsizer verify out/net.inp --pump-id PMP1 \
    --project examples/potable_water_pumping_station.yaml

# Excel in / out (headless, needs openpyxl - no Excel install)
pumpsizer excel-template my_inputs.xlsx        # blank labelled input workbook
pumpsizer excel my_inputs.xlsx --out result.xlsx
pumpsizer excel "Pump Sizing.xlsx" --legacy --out result.xlsx   # original layout

# print the annotated project schema
pumpsizer schema
```

`--into` / `verify` need the EPANET solver bridge: `pip install epyt`
(`pip install -e ".[epanet]"`). On the bundled example the stand-alone operating
point and EPANET's own solve agree to ~0.2%.

To drive selection from the project file, set `pump.source: catalogue` and
`pump.catalogue_path: my_catalogue/` (a file or directory of YAML — see
`docs/catalog_template.yaml`). The winning pump's curve (with any impeller trim
or VFD speed applied) flows straight into the operating-point, NPSH, motor and
EPANET steps; the full ranked list is in `ProjectResults.selection`.

Library:

```python
from pumpsizer import Project
res = Project.from_yaml("myproject.yaml").run()
print(res.operating_point.as_dict())
print(res.epanet_export.full_snippet())
```

## Project file

`pumpsizer schema` prints a fully annotated example. Key blocks:

| block | purpose |
|---|---|
| `fluid` | temperature → viscosity / vapour pressure; altitude → atmospheric pressure |
| `pipe` | material (`ductile_iron`/`steel`/`grp`/`hdpe`/`upvc`), `headloss_method: DW` or `HW` |
| `flow` | `total_demand_lps`, `duty_pumps`, `standby_pumps` |
| `segments` | each pipe reach: `length_m` + (`dn` or `diameter_mm`), `group: suction`/`discharge` |
| `fittings` | `{fitting_name: quantity}` per group; K values in `src/pumpsizer/data/fittings.yaml` |
| `levels` | reservoir / sump HWL & BWL → max & min static head |
| `pump` | `source: synthetic` \| `single_point` \| `points` (+ `curve_points`, `efficiency_points`, `npshr_points`) |
| `control` | `arrangement: single`/`parallel`/`series`, `vfd`, `vfd_min_speed_pct`, `vfd_target_flow_lps` |
| `motor` | `poles`, `ie_class`, `rating_margin_pct`, `sizing_basis` |
| `water_hammer` | `enabled`, `closure_time_s`, `pressure_class_pn` (bar), `allowable_max_head_m` — rule-of-thumb surge pre-sizing on the rising main |
| `energy` | `hours_per_day`, `tariff_per_kwh`, `life_cycle_years`, `discount_rate` |
| `epanet` | `flow_units` (LPS/CMH/MLD/…), `pump_id`, `from_node`, `to_node`, `head_points` (3 → EPANET refits A-B·Qᶜ; >3 → multi-point) |

Data tables (`src/pumpsizer/data/*.yaml`) — pipe bores, fitting K, motor
efficiency — are plain YAML; edit or point the API at your own via
`PipeDatabase.from_yaml(...)` / `FittingCatalog.from_yaml(...)`.

## What it computes

* **Friction** – Colebrook–White (iterative) + Darcy–Weisbach, or Hazen–Williams.
* **Minor losses** – `K·v²/2g`, each referenced to its driving bore.
* **System curve** – `H_static + Σ friction + Σ minor`, vectorised, plus the
  fitted `K` in `H ≈ H_static + K·Q²`.
* **Pump curve** – least-squares `A − B·Qᶜ` (falls back to piecewise-linear),
  affinity scaling on speed and impeller diameter, parallel/series combination.
* **Operating point** – `brentq` on `pump.head(Q) − system.head(Q)`.
* **VFD** – speed-scaled pump curve intersected with the *unscaled* system curve
  (so static head is handled correctly), clamped to the minimum speed.
* **NPSHa** – `(p_atm − p_v)/ρg + z_s,geo − H_L,s − v_s²/2g − SF`, with the
  cavitation rule `NPSHa − NPSHr ≥ max(0.5 m, 0.1·NPSHr)`.
* **Motor** – shaft power (at duty or non-overloading) × margin → next IEC size,
  with IE-class nominal efficiency and electrical input.

## Roadmap

* **Phase 1** – engine, CLI, EPANET text export, `.inp` splice. ✅
* **Phase 2** – catalogue data model + loader, selection & ranking, impeller-trim
  and VFD-speed solving, `pumpsizer select`, `pump.source: catalogue`. ✅
  *Still to do: digitise real curves from the KSB / Lubi / Grundfos datasheets
  into `docs/catalog_template.yaml` format (bundled entries are illustrative).*
* **Phase 3** – `inpfile.InpModel` structured `.inp` reader/writer; `.inp`
  splice (curve + pump + energy, keeps the existing pump's end nodes); `solver`
  bridge to the EPANET 2.2 engine via `epyt`; `pumpsizer verify` and
  `run --into --simulate`. ✅  On the bundled example the stand-alone operating
  point and EPANET's own solve agree to ~0.2%.  *Still to do: multi-pump
  staging against a demand pattern; extended-period energy read-back.*
* **Phase 4** – `surge` module: wave celerity, pipe period `2L/a`, Joukowsky &
  Michaud slow-closure surge, column-separation / pipe-rating check, and
  energy-balance air-vessel + run-down flywheel pre-sizing; `pumpsizer surge`
  and a `water_hammer:` project block. ✅  Rule-of-thumb only — a
  method-of-characteristics transient model is still needed for final design.
* **Phase 5** – `excelio` headless Excel bridge (openpyxl, no Excel/xlwings):
  `excel-template` writes a labelled input workbook, `excel` reads it (or the
  original `Pump Sizing.xlsx` via `--legacy`) and writes a multi-sheet results
  workbook (Summary / Curves / EPANET / Selection / Surge / Report). ✅
* **Next** – optional xlwings "Run" button inside the workbook itself (needs
  Python alongside Excel on each machine); real vendor curves digitised into
  the catalogue; EPD demand-pattern staging.

## Tests

```bash
py -m pytest -q
```
