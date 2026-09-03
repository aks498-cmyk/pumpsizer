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

# one-off curve + EPANET block from a duty point
pumpsizer curve --duty-q 300 --duty-h 33 --source synthetic --points 3

# print the annotated project schema
pumpsizer schema
```

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

* **Phase 1 (this release)** – engine, CLI, EPANET text export, `.inp` splice.
* **Phase 2** – manufacturer-catalogue database (from the KSB / Lubi / Grundfos
  datasheets) + selection & ranking; impeller-trim prediction.
* **Phase 3** – full `.inp` round-trip + EPANET-solver operating point
  (`epanet-python` / WNTR); multi-pump staging against a demand pattern.
* **Phase 4** – water-hammer pre-sizing (Joukowsky + air-vessel/flywheel rules
  of thumb).
* **Excel front end** – keep `Pump Sizing.xlsx` as the input UI, this package as
  the calc engine (xlwings), once the core is signed off.

## Tests

```bash
py -m pytest -q
```
