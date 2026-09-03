# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims
to follow [Semantic Versioning](https://semver.org/) once it reaches 1.0.

## [Unreleased]

### Added
- Repository is public; GitHub Pages site from `/docs`
  (<https://aks498-cmyk.github.io/pumpsizer/>); a `master` branch ruleset
  (no force-push, no deletion, linear history).

## [0.1.0] — 2026-09-03

First working version. A clean-room re-implementation of the `Pump Sizing.xlsx`
workbook as a reusable Python engine, with corrected Darcy–Weisbach friction
and NPSH (see `docs/workbook_mapping.md`). Not yet tagged or published.

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

[Unreleased]: https://github.com/aks498-cmyk/pumpsizer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aks498-cmyk/pumpsizer/releases/tag/v0.1.0
