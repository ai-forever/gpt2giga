.PHONY: frontend-assets sync lint test build candidate-gateway

HARNESS_FRONTEND = packages/gpt2giga-harness/frontend
UV_CACHE_DIR ?= .cache/uv

frontend-assets:
	npm --prefix $(HARNESS_FRONTEND) ci --ignore-scripts
	npm --prefix $(HARNESS_FRONTEND) run build

sync: frontend-assets
	./scripts/ci-base.sh sync

lint:
	./scripts/ci-base.sh ruff-check .
	./scripts/ci-base.sh ruff-format-check .

test:
	./scripts/ci-base.sh pytest tests/harness --cov=. --cov-report=term --cov-fail-under=80

build: frontend-assets
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv build --package gpt2giga-harness --no-sources

candidate-gateway:
	@test -n "$(GIGALOOM_GATEWAY_CANDIDATE_WHEEL)" || \
		(echo "set GIGALOOM_GATEWAY_CANDIDATE_WHEEL" >&2; exit 2)
	@test -n "$(GIGALOOM_GATEWAY_CANDIDATE_SHA256)" || \
		(echo "set GIGALOOM_GATEWAY_CANDIDATE_SHA256" >&2; exit 2)
	./scripts/ci-candidate-gateway.sh \
		"$(GIGALOOM_GATEWAY_CANDIDATE_WHEEL)" \
		"$(GIGALOOM_GATEWAY_CANDIDATE_SHA256)"
