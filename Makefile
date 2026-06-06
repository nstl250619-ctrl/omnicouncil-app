.PHONY: help install dev lint format typecheck test test-smoke test-cov clean

PYTHON ?= python3
PIP ?= pip3
BACKEND_DIR := backend
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= ruff

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	cd $(BACKEND_DIR) && $(PIP) install -e .

dev: ## Install dev dependencies (linters, test tools)
	cd $(BACKEND_DIR) && $(PIP) install -e ".[dev]"
	$(PIP) install ruff mypy

lint: ## Run ruff linter
	cd $(BACKEND_DIR) && ruff check .

format: ## Run ruff formatter
	cd $(BACKEND_DIR) && ruff format .

typecheck: ## Run mypy type checking
	cd $(BACKEND_DIR) && mypy --ignore-missing-imports .

test: ## Run all tests
	cd $(BACKEND_DIR) && $(PYTHON) -m pytest tests/ -v --tb=short

test-smoke: ## Run smoke tests only (fast, no browser)
	cd $(BACKEND_DIR) && $(PYTHON) -m pytest tests/test_smoke.py -v --tb=short

test-cov: ## Run tests with coverage report
	cd $(BACKEND_DIR) && $(PYTHON) -m pytest tests/ -v --tb=short --cov=. --cov-report=term-missing --cov-report=html

clean: ## Remove build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf $(BACKEND_DIR)/.mypy_cache $(BACKEND_DIR)/.ruff_cache $(BACKEND_DIR)/htmlcov $(BACKEND_DIR)/.coverage
