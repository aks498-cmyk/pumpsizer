---
title: Changelog
---

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims
to follow [Semantic Versioning](https://semver.org/) once it reaches 1.0.

## [Unreleased]

### Added
- **KSB Multitec 50 Hz catalogue** (`ksb_multitec_50hz.yaml`, 45 curves) —
  machine-digitised multistage pumps. `tools/digitise_ksb_multitec.py` reads the
  per-stage H-Q curve from the vector PDF (stitching the fragmented polylines
  back together) and the maximum stage count from the booklet's Table 9.
  `PumpModel` gains `stages_max` / `per_stage_head_m` and
  `to_pump_curve(stages=n)`; `selection` tries `1..stages_max` equal stages and
  picks the shortest stack that clears the duty head ("n of max m stages"), and
  reports the chosen count in `Candidate.stages`.
  `examples/high_head_booster_ksb_multitec.yaml` — a worked high-lift booster
  driven from the Multitec catalogue; end-to-end test added.
- Per-stage `H₀ × stages_max` is cross-checked against Table 9's published
  maximum head: within ~4% for DN32–DN125, ±10–15% for the two DN150 sizes
  (whose H axis reads less cleanly — those entries carry a `NOTE:` in the YAML
  and `table9_delta_pct`). 2900/1450 rpm per-stage `H₀` ratio 3.9–4.1.
- `tools/verify_ksb_multitec.py` renders four datasheet pages with the stitched
  H-Q polyline overlaid (`docs/ksb_multitec_verification.png`) — the digitised
  points sit on the printed per-stage curves for both impellers.
- **`pumpsizer catalog-check`** + `pumpsizer.catalog_qa` — machine QA for a
  catalogue: curve-shape and BEP/NPSHr sanity, multistage `per_stage × stages`
  consistency and the Table 9 cross-check, and `n²` / `D²` affinity between
  speed and impeller-diameter families. Findings are `OK`/`WARN`/`FAIL`; exits
  non-zero on a `FAIL`. The bundled catalogues report 0 FAIL.

### Changed (tooling)
- CI now runs `ruff check` + `ruff format --check` (on `src tests tools`) as a
  separate job before the test matrix; `ruff` is in the `dev` extra and the
  `ruff` `src` list includes `tools`. `make lint` / `make format` cover `tools`
  too; the stale `make catalog` target now calls the two digitisers, and
  `make catalog-check` is new.

### Changed
- **KSB Omega catalogue is now machine-digitised, not envelope-only.**
  `tools/digitise_ksb_omega.py` reads the vector datasheet PDF: it calibrates
  each size page's axes from the tick labels and maps every impeller's curve
  polylines to data, giving a real Q-H curve, NPSHr points and a BEP
  (Q, efficiency) per impeller diameter — **246 curves from 73 of 74 size
  pages** (1 skipped). Entries are `digitised: true`, still `verified: false`.
  The 1450/2900 rpm and impeller-diameter families come out affinity-consistent
  (H ∝ n², H ∝ D²) — a check that the calibration is right.
- `catalog.PumpModel` reads `curve:` / `npshr_points:` / `eff_bep_pct:`;
  `selection` flags digitised candidates ("confirm against datasheet p.N",
  ×0.94 score) distinctly from unverified envelope entries.
- The 5 illustrative catalogue pumps are tagged `illustrative` and ×0.5 in
  selection, so `pump.source: catalogue` with no path (which loads the bundled
  digitised KSB Omega curves + the illustrative ones) never returns a synthetic
  pump over real data.
- `examples/potable_water_pumping_station_ksb.yaml` — the worked station with
  the pump chosen from the digitised KSB catalogue; end-to-end test added.
- Digitised H-Q points spot-checked against 4 rendered datasheet pages
  (`docs/ksb_omega_verification.png`); they sit on the printed curves.
- Removed the old envelope-only builder (`tools/build_ksb_omega_catalog.py`).

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

[Unreleased]: https://github.com/aks498-cmyk/pumpsizer/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/aks498-cmyk/pumpsizer/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aks498-cmyk/pumpsizer/releases/tag/v0.1.0
