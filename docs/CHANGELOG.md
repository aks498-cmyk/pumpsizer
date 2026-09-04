---
title: Changelog
---

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims
to follow [Semantic Versioning](https://semver.org/) once it reaches 1.0.

## [Unreleased]

### Fixed
- Excel button: the macro now calls `RunPython` through
  `Application.Run "xlwings.xlam!RunPython"` instead of a bare `RunPython`,
  which needs a per-workbook Tools ▸ References entry the generated `.xlsm`
  didn't carry (it failed with *Compile error: Sub or Function not defined*).
  Verified end-to-end on Windows + Excel: the button runs the full pipeline and
  writes `<workbook>-results.xlsx`. `docs/excel_button.md` updated.

## [0.3.1] — 2026-09-04

Catalogue and tooling: a fuller Omega set, a datasheet-audit tool, and the
Excel button packaged for install. No engine API change.

### Added
- `tools/verify_ksb_omega.py` — the Omega counterpart of the Multitec overlay
  tool (`--pages a,b,c` to check any datasheet pages while verifying a
  shortlisted pump); it also regenerates `docs/ksb_omega_verification.png`.
- Both `verify_ksb_*.py` tools now also print the digitised numbers (H₀, H end,
  Q range, BEP, NPSHr range, stages, Table 9 Δ) for the rendered pages, so a
  checker can compare them with the printed curve without opening the YAML.

### Changed
- **KSB Omega digitiser recovers dropped curves.** The shape gate rejected any
  impeller whose shut-off/run-out ratio exceeded 2.7 — which on many pages
  killed the smallest (heavily trimmed, deep run-out) impeller and, by shifting
  the diameter index, mislabelled or collapsed the rest. The cap is now 4.5
  with an added "each impeller in the family has a lower shut-off than the last"
  check. Result: **296 curves from all 74 pages** (was 246 from 73); page 66
  (had collapsed to one un-labelled entry) and page 75 (was skipped) are back.
  The new deep-run-out entries are `catalog-check` `WARN` (ratio 3–4.5) — real
  curves, still `verified: false`.
- `tools/audit_digitisation.py` — page-level audit against the source PDFs
  (curves dropped vs H-band strokes, ø-label count mismatch, truncated Qmax),
  worst-pages-first, to steer the human datasheet pass.
- Both digitisers and the audit now drop a stroke that does not fall
  left-to-right (a chart border wrongly counted as a curve): this fixed the
  Omega diameter labels on pages 9 and 13 and cut the audit's flagged list from
  12 to 9. Multitec's shape gate matches Omega's (`ratio ≤ 4.5` + family order).
  Remaining audit flags: Omega p66/67/73/75 (smallest impeller, run-out ratio
  6–8, or a missing ø-label) and Multitec twin-page split noise.
- `pip install "pumpsizer[xlwings]"` extra (openpyxl + xlwings) for the Excel
  button; `docs/excel_button.md` gains a win32com snippet that embeds the macro
  and places the button, producing a ready-to-click `pumpsizer.xlsm`.

## [0.3.0] — 2026-09-04

Real digitised manufacturer curves (KSB Omega + Multitec), catalogue QA and a
verification workflow, and an in-workbook Excel "Run" button.

### Added
- **KSB Omega 50 Hz catalogue is machine-digitised from the vector datasheet.**
  `tools/digitise_ksb_omega.py` calibrates each size page's axes from the tick
  labels and maps *every* impeller's curve polylines to data — a real Q-H
  curve, NPSHr points and a BEP per impeller diameter: **246 curves from 73 of
  74 pages**. Entries are `digitised: true`, `verified: false`. The 1450/2900
  rpm and diameter families come out affinity-consistent (H ∝ n², H ∝ D²).
  Replaces the old envelope-only data and its builder.
- **KSB Multitec 50 Hz catalogue** (`ksb_multitec_50hz.yaml`, 45 multistage
  curves). `tools/digitise_ksb_multitec.py` reads the per-stage H-Q curve from
  the vector PDF — stitching the fragmented polylines back together — and the
  maximum stage count from the booklet's Table 9. `PumpModel` gains
  `stages_max` / `per_stage_head_m` / `to_pump_curve(stages=n)`; `selection`
  tries `1..stages_max` equal stages, takes the shortest stack that clears the
  duty head ("n of max m stages") and reports it in `Candidate.stages`.
  Per-stage `H₀ × stages_max` matches Table 9 within ~4% for DN32–DN125; the
  two DN150 sizes read ±10–15% and carry a `NOTE:` + `table9_delta_pct`.
- **`pumpsizer catalog-check`** + `pumpsizer.catalog_qa` — machine QA for a
  catalogue: curve-shape and BEP/NPSHr sanity, multistage `per_stage × stages`
  consistency and the Table 9 cross-check, and `n²` / `D²` affinity between
  speed and impeller-diameter families. `OK`/`WARN`/`FAIL`; exits non-zero on a
  `FAIL`. The bundled catalogues report 0 FAIL.
- **`pumpsizer catalog-verify`** — status of the human "against the paper
  datasheet" pass (verified vs. still-to-check, by series) and `--emit
  checklist.csv`, a row per unverified entry with its key digitised numbers,
  `datasheet_page` and blank verdict / checked-by columns.
- **xlwings "Run" button** — `pumpsizer excel-addin --out <dir>` writes
  `pumpsizer.bas` (the button macro), a fresh input template and setup notes.
  `pumpsizer.xlwings_addin.run()` (what the button calls) saves the live
  workbook and hands the file to the headless `excelio.run_workbook`, opens the
  `*-results.xlsx` and writes a status line to `Input!F1`. Template vs. legacy
  `Pump Sizing.xlsx` is auto-detected. Needs Python + `xlwings` on the machine
  with Excel; full guide in `docs/excel_button.md`.
- Verification overlays `docs/ksb_omega_verification.png` and
  `docs/ksb_multitec_verification.png` (`tools/verify_ksb_multitec.py`, with a
  `--pages a,b,c` option); worked examples
  `examples/potable_water_pumping_station_ksb.yaml` and
  `examples/high_head_booster_ksb_multitec.yaml` with end-to-end tests.

### Changed
- `catalog.PumpModel` reads `curve:` / `npshr_points:` / `eff_bep_pct:` /
  `per_stage_head_m` / `stages_max` / the `table9_*` QA fields. `selection`
  flags digitised candidates ("confirm against datasheet p.N", ×0.94 score) and
  ×0.5-penalises the illustrative pumps (now tagged `illustrative`), so
  `pump.source: catalogue` with no path never returns a synthetic pump over
  real data.
- CI runs `ruff check` + `ruff format --check` (on `src tests tools`) as a job
  before the test matrix; `ruff` is in the `dev` extra. `make lint` / `format`
  cover `tools`; `make catalog` calls the two digitisers; `make catalog-check`
  is new.

## [0.2.0] — 2026-09-04

Repository / distribution and documentation only — no functional change to the
engine (no API or calculation differences from 0.1.0). Consolidates the
earlier `v0.2.0` and `v0.3.0` tags (both docs-only), which were removed.

### Added
- Repository is public.
- **Docs site** on GitHub Pages from `/docs`
  (<https://aks498-cmyk.github.io/pumpsizer/>): landing page + reference docs,
  Cayman theme, top navigation with an active-page indicator, `CHANGELOG`
  rendered as a page, and a footer with the project description, a
  repo / version / licence / maintainer line, and a "back to docs home" link.
- README and docs badge row: `docs` (Pages) and `release` (latest tag) badges
  alongside CI / Python / licence / EPANET.

### Changed
- `master` branch ruleset: no force-push, no branch deletion, linear history
  (admin bypass).
- CI actions bumped to `actions/checkout@v7` and `actions/setup-python@v7`
  (Dependabot).

## [0.1.0] — 2026-09-03

First working version. A clean-room re-implementation of the `Pump Sizing.xlsx`
workbook as a reusable Python engine, with corrected Darcy–Weisbach friction
and NPSH (see `docs/workbook_mapping.md`). Tagged `v0.1.0` with a GitHub
release.

### Added

**Hydraulics**
- Colebrook–White friction factor (iterative) + Darcy–Weisbach, and
  Hazen–Williams as an alternative.
- Minor losses `K·v²/2g` referenced to each fitting's driving bore; editable
  pipe-bore, fitting-K and motor-efficiency data tables (`data/*.yaml`).
- Water properties vs temperature and site altitude (viscosity table ported
  from the workbook; vapour pressure and barometric pressure added).
- System characteristic for the full `{min,max static} × {new,aged roughness}`
  family; fitted resistance `K` in `H ≈ H_static + K·Q²`.

**Pump curves & operating point**
- Least-squares `H = A − B·Qᶜ` fit (piecewise-linear fallback); single-point
  (EPANET 1.33×/2× rule) and synthetic constructors; affinity scaling on speed
  and impeller diameter; parallel and series combination.
- Operating point by `brentq` intersection; parallel-set and VFD-speed solvers.
- NPSHa with the `NPSHa − NPSHr ≥ max(0.5 m, 0.1·NPSHr)` check.
- Motor sizing to the IEC 60072-1 kW series with IE1–IE4 nominal efficiency;
  annual energy and present-value life-cycle cost.

**Selection & catalogue**
- Pump catalogue data model + YAML loader; selection/ranking that tries fixed
  speed, impeller trim (KSB turn-down rule) and VFD speed-up to meet a duty,
  scored on efficiency, BEP proximity, NPSH margin and head margin.
- Bundled data: 5 illustrative pumps plus **74 KSB Omega / Omega V 50 Hz
  sizes** extracted from the datasheet booklet (envelope + page number per
  size; BEP approximated, `verified: false`).

**EPANET**
- `[CURVES]` / `[PUMPS]` / `[ENERGY]` text export in any flow unit.
- Dependency-free `.inp` reader/writer (`InpModel`) that splices a curve, pump
  and energy block into an existing network, keeping the pump's end nodes.
- Optional bridge to the EPANET 2.2 solver via `epyt` (`verify`,
  `run --into --simulate`); on the worked example the stand-alone operating
  point and EPANET's own solve agree to ~0.2%.

**Water hammer**
- Rule-of-thumb pre-sizing: wave celerity, pipe period `2L/a`, Joukowsky and
  Michaud slow-closure surge, column-separation and pipe-rating checks,
  energy-balance air-vessel and run-down flywheel sizing.
- Method-of-characteristics transient solver for a pumping main: pipeline
  discretisation, pump rundown from rotating inertia, check valve on reversal,
  discrete vapour-cavity model, optional air vessel; per-node pressure envelope.

**Extended-period**
- Demand-pattern multi-pump staging with delivery-tank dynamics: VFD
  common-speed or fixed-speed lead/lag; daily energy, per-pump starts and
  run-hours, efficiency stats, BEP-window compliance, unmet-demand steps.

**Interfaces**
- CLI: `run`, `curve`, `schema`, `select`, `verify`, `surge`, `transient`,
  `stage`, `excel`, `excel-template`.
- Library API: `Project.from_yaml(...).run()` → `ProjectResults`.
- Headless Excel bridge (`openpyxl`, no Excel/xlwings): labelled input
  template, results workbook, and a best-effort reader for the original
  `Pump Sizing.xlsx` layout.

**Tooling / repository**
- GitHub Actions CI (pytest on Python 3.10–3.13), Dependabot (grouped weekly
  actions + pip; alerts and security updates on), bug/feature issue forms,
  pull-request template, `SECURITY.md`, `CODEOWNERS`, `CONTRIBUTING.md`,
  `CHANGELOG.md`, `Makefile`, `.editorconfig`, MIT `LICENSE`, and a `pre-push`
  hook that runs the suite.
- `ruff` config in `pyproject.toml`; codebase passes `ruff check` and is
  `ruff format`-clean, with a `.git-blame-ignore-revs`.

### Known limitations
- The KSB Omega catalogue is envelope-only; digitise real curve points before
  using an entry for design (`docs/catalog_from_ksb.md`).
- The MOC solver is single-pipe and damps the cavity-collapse spike — use a
  specialist package for a branched network or final sign-off.

[Unreleased]: https://github.com/aks498-cmyk/pumpsizer/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/aks498-cmyk/pumpsizer/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/aks498-cmyk/pumpsizer/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/aks498-cmyk/pumpsizer/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aks498-cmyk/pumpsizer/releases/tag/v0.1.0
