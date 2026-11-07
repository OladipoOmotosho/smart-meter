PYTHON ?= python3.12
VENV ?= .venv
PY := $(abspath $(VENV))/bin/python
FORGE ?= forge
ANVIL ?= anvil
REPORT_DIR ?= .test-results

.PHONY: help install lint build test-unit test-contracts test-integration coverage check chain deploy demo

help:
	@echo 'install lint build test-unit test-contracts test-integration coverage check chain deploy demo'

install:
	@$(PYTHON) -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -r pipeline/requirements.lock
	$(PY) -m pip check
	@sh scripts/install_contract_libs.sh

lint:
	@$(PY) -m ruff check pipeline scripts
	@$(PY) -m ruff format --check pipeline scripts
	@cd contracts && $(FORGE) fmt --check

build:
	@cd contracts && $(FORGE) build

test-unit:
	@mkdir -p $(REPORT_DIR)
	@cd pipeline && $(PY) -m pytest -m 'not chain' -ra -p no:cacheprovider --strict-markers --junitxml=$(abspath $(REPORT_DIR))/unit.xml
	@$(PY) scripts/check_test_report.py unit $(REPORT_DIR)/unit.xml

test-contracts:
	@mkdir -p $(REPORT_DIR)
	@cd contracts && $(FORGE) test -vv > $(abspath $(REPORT_DIR))/contracts.txt 2>&1 || { cat $(abspath $(REPORT_DIR))/contracts.txt; exit 1; }
	@cat $(REPORT_DIR)/contracts.txt
	@$(PY) scripts/check_test_report.py contracts $(REPORT_DIR)/contracts.txt

test-integration:
	@mkdir -p $(REPORT_DIR)
	@$(PY) scripts/run_integration.py $(abspath $(REPORT_DIR))/integration.xml
	@$(PY) scripts/check_test_report.py chain $(REPORT_DIR)/integration.xml

coverage:
	@cd pipeline && $(PY) -m coverage run --branch -m pytest -m 'not chain' -ra -p no:cacheprovider --strict-markers
	@cd pipeline && $(PY) -m coverage report
	@$(PY) scripts/check_branch_coverage.py pipeline/.coverage

check: lint build test-unit test-contracts test-integration coverage

chain:
	@command -v $(ANVIL) >/dev/null || { echo 'Anvil is missing. Install Foundry v1.9.0.' >&2; exit 1; }
	$(ANVIL) --host 127.0.0.1 --port 8545

deploy:
	@test -f .env || { echo '.env is required for an explicit local deployment.' >&2; exit 1; }
	@cd contracts && set -a && . ../.env && set +a && \
	  test -n "$$ADMIN_PRIVATE_KEY" && test -n "$$AGGREGATOR_ADDRESS" && \
	  $(FORGE) script script/Deploy.s.sol:Deploy --rpc-url "$${RPC_URL:-http://127.0.0.1:8545}" --broadcast

demo:
	@echo 'Task 9.1 must replace the current demo database deletion before make demo is safe.' >&2
	@exit 1
