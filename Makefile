PYTHON ?= python3.12
VENV := .venv
PY := $(abspath $(VENV))/bin/python
FORGE ?= forge
ANVIL ?= anvil

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
	@$(PY) -m ruff check pipeline
	@$(PY) -m ruff format --check pipeline
	@cd contracts && $(FORGE) fmt --check

build:
	@cd contracts && $(FORGE) build

test-unit:
	@cd pipeline && $(PY) -m pytest -m 'not chain' -ra

test-contracts:
	@cd contracts && $(FORGE) test -vv

test-integration:
	@$(PY) scripts/run_integration.py

coverage:
	@cd pipeline && $(PY) -m coverage run -m pytest -m 'not chain' -ra
	@cd pipeline && $(PY) -m coverage report --fail-under=85

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
