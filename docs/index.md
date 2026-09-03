---
title: pumpsizer
---

[![CI](https://github.com/aks498-cmyk/pumpsizer/actions/workflows/ci.yml/badge.svg)](https://github.com/aks498-cmyk/pumpsizer/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/aks498-cmyk/pumpsizer?sort=semver)](https://github.com/aks498-cmyk/pumpsizer/releases)
[![docs](https://img.shields.io/badge/docs-pages-blue)](https://aks498-cmyk.github.io/pumpsizer/)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![EPANET](https://img.shields.io/badge/EPANET-2.2-informational)

Reusable engine for **water-supply pump sizing, operating-point analysis and
EPANET-compatible curve generation** — plus water hammer and demand-pattern
staging.

[Source &amp; README](https://github.com/aks498-cmyk/pumpsizer){: .btn} ·
[latest release](https://github.com/aks498-cmyk/pumpsizer/releases/latest) ·
[Changelog](CHANGELOG.html)

## What it does

Given a duty (head in m, discharge in l/s) and the installation data:

1. builds the **system characteristic** `H_sys(Q)` for the `{min,max static} × {new,aged roughness}` family;
2. fits or synthesises a **pump characteristic** `H = A − B·Qᶜ` (+ efficiency, + NPSHr);
3. solves the **operating point** — single, parallel, series, or VFD;
4. runs the **NPSHa / cavitation** check, sizes the **motor** (IEC 60072-1, IE1–IE4), estimates **energy / LCC**;
5. **selects and ranks** catalogue pumps (incl. 74 KSB Omega sizes) with impeller-trim and VFD;
6. exports **EPANET 2.2** `[CURVES]/[PUMPS]/[ENERGY]`, splices into an `.inp`, and can run the solver via `epyt`;
7. assesses **water hammer** — rule-of-thumb (Joukowsky, air vessel, flywheel) and a **method-of-characteristics** pump-trip transient;
8. simulates **demand-pattern multi-pump staging** against a delivery tank.

It is a clean-room re-implementation of a spreadsheet workflow, with corrected
Darcy–Weisbach friction and NPSH — see [Workbook mapping](workbook_mapping.html).

## Install

```bash
git clone https://github.com/aks498-cmyk/pumpsizer.git
cd pumpsizer
py -m pip install -e ".[dev]"     # or python3 on macOS/Linux
```

## Quick start

```bash
pumpsizer run examples/potable_water_pumping_station.yaml --plot out/perf.png
pumpsizer select --duty-q 300 --duty-h 33 --npsha 9
pumpsizer transient --length 2500 --dn 400 --flow-lps 300 --head 33 --static 24 --inertia 5 --air-vessel-m3 20
pumpsizer stage examples/potable_water_pumping_station.yaml --mode vfd
pumpsizer schema        # annotated project file
```

```python
from pumpsizer import Project
res = Project.from_yaml("myproject.yaml").run()
print(res.operating_point.as_dict())
```

## Reference

- [Workbook mapping](workbook_mapping.html) — how the schema maps onto the source spreadsheet, and the corrections made
- [Building a catalogue from a KSB booklet](catalog_from_ksb.html) — the envelope-only entries and how to upgrade them
- [`catalog_template.yaml`](catalog_template.yaml) — catalogue file template
- [Contributing](https://github.com/aks498-cmyk/pumpsizer/blob/master/CONTRIBUTING.md)

## Limitations

The KSB Omega catalogue is **envelope-only** (BEP approximated, `verified: false`) —
digitise real curve points before design use. The MOC solver is single-pipe and
damps the cavity-collapse spike; use a specialist package for a branched network
or final sign-off.
