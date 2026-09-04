# Common dev tasks.  `make` is optional - every target is a one-liner you can
# run by hand.  Override the interpreter on non-Windows:  make test PYTHON=python3
PYTHON ?= py
EXAMPLE := examples/potable_water_pumping_station.yaml
OUT     := out

.DEFAULT_GOAL := help
.PHONY: help install dev test test-cov lint format hook run report plots catalog catalog-check ci clean

help:  ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Editable install (runtime deps only)
	$(PYTHON) -m pip install -e .

dev:  ## Editable install with tests, plotting, Excel, EPANET solver
	$(PYTHON) -m pip install -e ".[dev]"

test:  ## Run the test suite
	$(PYTHON) -m pytest -q

test-cov:  ## Run tests with coverage (needs: pip install pytest-cov)
	$(PYTHON) -m pytest -q --cov=pumpsizer --cov-report=term-missing

lint:  ## Static check + format check with ruff
	$(PYTHON) -m ruff check src tests tools
	$(PYTHON) -m ruff format --check src tests tools

format:  ## Auto-format with ruff
	$(PYTHON) -m ruff format src tests tools
	$(PYTHON) -m ruff check --fix src tests tools

hook:  ## Install the pre-push test hook into this clone
	cp scripts/git-hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push

run:  ## Run the worked example
	$(PYTHON) -m pumpsizer.cli run $(EXAMPLE)

report:  ## Write the example report + summary json to $(OUT)/
	@mkdir -p $(OUT)
	$(PYTHON) -m pumpsizer.cli run $(EXAMPLE) --report $(OUT)/report.txt --json $(OUT)/summary.json --epanet $(OUT)/pump.inp

plots:  ## Regenerate the example plots (performance, transient, staging) to $(OUT)/
	@mkdir -p $(OUT)
	$(PYTHON) -m pumpsizer.cli run $(EXAMPLE) --plot $(OUT)/perf.png
	$(PYTHON) -m pumpsizer.cli transient --length 2500 --dn 400 --flow-lps 300 --head 33 --static 24 --inertia 5 --air-vessel-m3 20 --plot $(OUT)/transient.png
	$(PYTHON) -m pumpsizer.cli stage $(EXAMPLE) --plot $(OUT)/staging.png

catalog:  ## Regenerate the digitised KSB catalogues (set KSB=path/to/pdf/dir)
	$(PYTHON) tools/digitise_ksb_omega.py    $(KSB)/dow-omega-data.pdf
	$(PYTHON) tools/digitise_ksb_multitec.py $(KSB)/dow-multitec-data.pdf

catalog-check:  ## QA the bundled digitised catalogues
	$(PYTHON) -m pumpsizer.cli catalog-check

ci:  ## What CI runs: lint + dev install + tests
	$(PYTHON) -m ruff check src tests tools
	$(PYTHON) -m ruff format --check src tests tools
	$(PYTHON) -m pip install -e ".[dev]"
	$(PYTHON) -m pytest -q

clean:  ## Remove caches and generated output
	rm -rf $(OUT) build dist .pytest_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
