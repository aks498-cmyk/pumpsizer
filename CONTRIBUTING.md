# Contributing to pumpsizer

## Dev setup

Requires Python 3.10+ and git. On Windows the launcher is `py`; on
macOS/Linux use `python3`.

```bash
git clone https://github.com/aks498-cmyk/pumpsizer.git
cd pumpsizer

# editable install with everything: tests, plotting, Excel, EPANET solver
py -m pip install -e ".[dev]"

# install the pre-push hook (runs the suite before every push)
cp scripts/git-hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

Optional extras if you don't want the full `[dev]` set:

| extra | pulls in | needed for |
|---|---|---|
| `.[plot]` | matplotlib | `--plot` flags, `report.plot_performance` |
| `.[excel]` | openpyxl | `pumpsizer excel*`, `excelio` |
| `.[epanet]` | epyt | `pumpsizer verify`, `run --into --simulate`, `solver` |

## Running things

```bash
py -m pytest -q                     # test suite, ~40 s
py -m ruff check src tests tools    # lint  (CI runs this + `ruff format --check`)
py -m pumpsizer.cli --help          # or: pumpsizer --help  (after install)
py -m pumpsizer.cli run examples/potable_water_pumping_station.yaml
py -m pumpsizer.cli catalog-check   # QA the digitised KSB catalogues
```

There's a `Makefile` with shortcuts (`make dev`, `make test`, `make lint`,
`make format`, `make hook`, `make run`, `make plots`, `make catalog-check`,
`make clean`) — `make` is optional, each target is just a one-liner. Run
`make help` for the list. On non-Windows: `make test PYTHON=python3`.

The EPANET-solver tests `skipif` when `epyt` can't import, so a partial
install still gives a green suite.

## Layout

```
src/pumpsizer/
  fluid, friction, pipes, fittings     physical primitives + data tables (data/*.yaml)
  system, pumpcurve, operating         system curve, pump curve fit, operating point
  npsh, motor, energy                  cavitation check, driver sizing, energy/LCC
  catalog, selection                   pump database + selection/ranking
  epanet, inpfile, solver              EPANET text export, .inp read/write, epyt bridge
  surge, transient                     water hammer: rule-of-thumb + MOC
  staging                              demand-pattern multi-pump simulation
  project                              YAML schema + orchestrator -> ProjectResults
  report, cli, excelio                 text/plots, command line, headless Excel I/O
tests/                                 one file per area, mirrors src
examples/                              a worked project + a skeleton .inp
docs/                                  workbook mapping, catalogue procedures
tools/                                 build_ksb_omega_catalog.py (regenerates a data file)
```

## Conventions

- **SI internally** — Q in m³/s, H in m, everything in the `constants` frame.
  Convert at the edges (CLI/project files take l/s, m, mm, kW).
- New physics goes in its own module with a matching `tests/test_<area>.py`;
  keep functions pure and pass data in, don't reach for globals.
- Data tables (`src/pumpsizer/data/*.yaml`) are plain YAML — extend them or
  point the API at your own (`PipeDatabase.from_yaml`, `Catalog.from_path`).
- Catalogue entries digitised from a datasheet must set `verified: true` only
  after a second check; envelope-only entries stay `verified: false`
  (see `docs/catalog_from_ksb.md`).
- `ruff` is the formatter and linter (`ruff format`, then `ruff check`);
  config is in `pyproject.toml` (100-col, `E/F/W/I/UP/B`). CI enforces both.
- Stick to stdlib + numpy/scipy idioms; match the surrounding style.

## Before you push

- `py -m pytest -q` is green (the hook enforces this locally).
- `py -m ruff check src tests tools` and `ruff format --check` are clean.
- New behaviour has a test; changed numbers have a comment saying why.
- CI runs ruff + the suite on Python 3.10–3.13 for every push and PR to `master`.
- Digitiser or catalogue change: `pumpsizer catalog-check` reports 0 FAIL.
- Update `docs/CHANGELOG.md` (Unreleased section) for anything user-facing.
- Commit messages: imperative subject, a short body explaining *why* for
  anything non-obvious.
