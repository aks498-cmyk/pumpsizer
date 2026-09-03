---
---

# `Pump Sizing.xlsx` → `pumpsizer` mapping

How the spreadsheet's inputs and calculations map onto this engine, and where
the engine deliberately differs.

## Inputs (Input sheet → project YAML)

| Workbook cell / label | Project field |
|---|---|
| Type of Pumping System | *(not modelled in Phase 1; affects sump design only)* |
| Piping Material | `pipe.material` |
| Condition (new/used) | both are always computed → `system_set` |
| Pipe Roughness (New) `en` | `data/pipes.yaml → roughness_mm_new` |
| Pipe Roughness (Used) `eu` | `data/pipes.yaml → roughness_mm_used` |
| Total Flow/Demand `Q` | `flow.total_demand_lps` |
| No of Duty Pumps `N` | `flow.duty_pumps` |
| VFD Operation / Min Speed % | `control.vfd`, `control.vfd_min_speed_pct` |
| Suction Header / Pump Suction / Pump Discharge / Rising Main lengths | `segments[].length_m` |
| Max/Min velocity limits | `velocity_limits.*` (used only if `autosize_diameter`) |
| Temperature `T` | `fluid.temperature_c` |
| Pipe Class / Pressure Rating `PN` | `pipe.series` (HDPE/uPVC) / choose `dn` per segment |
| Pipeline Fittings & Quantity (suction / discharge) | `fittings.suction`, `fittings.discharge` |
| HWL/BWL at Receiving Reservoir | `levels.reservoir_hwl_m`, `levels.reservoir_bwl_m` |
| HWL/BWL at Pumping Sump | `levels.sump_hwl_m`, `levels.sump_bwl_m` |
| Pump Centreline (from Sump BWL) | `levels.pump_centreline_m` |
| NPSH Safety Margin `NPSHsf` | `suction.npsh_safety_margin_m` |
| Pump Data Input (Make/Model, NPSHr, ηp, ηm, margin) | `pump.*`, `motor.*` |

## Calculations (Calculations sheet → engine)

| Workbook step | Engine |
|---|---|
| Internal diameter lookup by class/PN | `PipeDatabase.internal_diameter_mm` (DN400 = 402.8 mm, DN700 = 704.4 mm reproduced) |
| Velocity `v = 4Q/πD²` | `friction.velocity` / `PipeSegment.velocity` |
| Reynolds `Re = vD/ν`, ν from Viscousity sheet | `friction.reynolds`, `fluid.kinematic_viscosity` (same table) |
| Friction factor: Colebrook–White implicit | `friction.colebrook_white` (iterative, Haaland seed) |
| Friction loss | `friction.darcy_weisbach_hf` — **see correction below** |
| Minor losses `Σ K·v²/2g` (fixed K per fitting) | `fittings.yaml → workbook_defaults`, `system.MinorLoss` |
| Static head: `Hs,max = HWLres − BWLsump`, `Hs,min = BWLres − HWLsump` | `SystemCurveSet` (max/min) |
| TDH = Hf + Hm + Hs (used & new) | `SystemCurve.head` for each of the 4 curves |
| NPSHa = Patm − Hst − Hsf − Hsm − v²/2g − SF | `npsh.npsh_available` — **vapour pressure added**, see below |
| Motor P = ρgQH / (ηp·ηm), + margin | `pumpcurve.shaft_power`, `motor.size_motor` |
| IE1–IE4 efficiency table (ABB) | `data/motors.yaml` (same numbers) |

## Deliberate differences / corrections

1. **Friction-loss formula.** The workbook cell computes
   `Hf = f · (L/D) · (Q/1000) · v²/2g` — i.e. Darcy–Weisbach multiplied by an
   extra `Q_in_m³s` factor, which is dimensionally inconsistent and makes
   `Hf` scale with the cube of flow. The engine uses the standard
   `Hf = f · (L/D) · v²/2g`. *(The saved copy of the workbook is also in an
   error state: "Pipe Roughness (Used)" is blank, so `e/D = 0`, `f` is clamped
   to 10000 and the reported duty head is ~1.05 million m. That is a data-entry
   gap, not a method choice, but it confirms the sheet needs the fix.)*

2. **NPSH.** The workbook uses a fixed `Patm = 10 m` and omits the vapour-pressure
   term. The engine derives `Patm` from site altitude and subtracts
   `p_v/ρg` (from steam tables). Set `suction.atmospheric_head_m: 10` and
   `suction.ignore_vapour_pressure: true` to reproduce the workbook exactly.

3. **Static suction head sign.** `static_suction_head_m` is **+ve for flooded
   suction, −ve for a lift** (`sump_bwl − pump_centreline`). The workbook's
   `Hst = centreline − BWL` is the same quantity with the same sign.

4. **VFD locus.** The workbook scales the whole pump curve by `n²` and reads a
   new intersection. The engine does the same but keeps the *system* curve
   unscaled, so the static-head part is not (incorrectly) reduced with speed.

5. **Pump curve.** The workbook has no real pump curve — it reports the duty
   point only. The engine fits / synthesises `H = A − B·Qᶜ` so an actual
   operating point (which is rarely exactly the duty point) can be found.
