.PHONY: frontend-assets sync sync-all-extras lint test build public-gateway

HARNESS_FRONTEND = packages/gpt2giga-harness/frontend
UV_CACHE_DIR ?= .cache/uv

frontend-assets:
	npm --prefix $(HARNESS_FRONTEND) ci --ignore-scripts
	npm --prefix $(HARNESS_FRONTEND) run build

sync: frontend-assets
	./scripts/ci-base.sh sync

sync-all-extras: frontend-assets
	./scripts/ci-base.sh sync-all-extras

lint:
	./scripts/ci-base.sh ruff-check .
	./scripts/ci-base.sh ruff-format-check .

test:
	./scripts/ci-base.sh pytest tests/harness --cov=. --cov-report=term --cov-fail-under=80

build: frontend-assets
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv build --no-sources

public-gateway: sync-all-extras
	./scripts/ci-public-gateway.sh
