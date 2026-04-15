# Docker Compose shortcuts for deploy/compose/* examples

.PHONY: help \
	compose-base-prod compose-base-prod-d compose-base-dev compose-base-dev-d compose-base-down \
	compose-observe-prod compose-observe-prod-d compose-observe-dev compose-observe-dev-d compose-observe-down \
	compose-traefik-up compose-traefik-up-d compose-traefik-down \
	compose-multiple-up compose-multiple-up-d compose-multiple-down \
	compose-observe-multiple-up compose-observe-multiple-up-d compose-observe-multiple-down \
	compose-nginx-up compose-nginx-up-d compose-nginx-down \
	compose-prometheus-prod compose-prometheus-prod-d compose-prometheus-dev compose-prometheus-dev-d compose-prometheus-down \
	compose-otlp-prod compose-otlp-prod-d compose-otlp-dev compose-otlp-dev-d compose-otlp-down \
	compose-langfuse-prod compose-langfuse-prod-d compose-langfuse-dev compose-langfuse-dev-d compose-langfuse-down \
	compose-runtime-redis-up compose-runtime-redis-up-d compose-runtime-redis-down \
	compose-runtime-postgres-up compose-runtime-postgres-up-d compose-runtime-postgres-down \
	compose-runtime-s3-up compose-runtime-s3-up-d compose-runtime-s3-down \
	compose-prod compose-prod-d compose-dev compose-dev-d compose-down \
	observe-prod observe-prod-d observe-dev observe-dev-d observe-down \
	traefik traefik-up traefik-down \
	multiple-up multiple-up-d multiple-down \
	observe-multiple observe-multiple-up observe-multiple-up-d observe-multiple-down

COMPOSE_ENV_FILE = .env
DOCKER_COMPOSE = docker compose --env-file $(COMPOSE_ENV_FILE)

COMPOSE_BASE = deploy/compose/base.yaml
COMPOSE_OBSERVE = deploy/compose/observability.yaml
COMPOSE_TRAEFIK = deploy/compose/traefik.yaml
COMPOSE_MULTIPLE = deploy/compose/multiple.yaml
COMPOSE_OBSERVE_MULTIPLE = deploy/compose/observe-multiple.yaml
COMPOSE_NGINX = deploy/compose/nginx.yaml
COMPOSE_PROMETHEUS = deploy/compose/observability-prometheus.yaml
COMPOSE_OTLP = deploy/compose/observability-otlp.yaml
COMPOSE_LANGFUSE = deploy/compose/observability-langfuse.yaml
COMPOSE_RUNTIME_REDIS = deploy/compose/runtime-backends/redis.yaml
COMPOSE_RUNTIME_POSTGRES = deploy/compose/runtime-backends/postgres.yaml
COMPOSE_RUNTIME_S3 = deploy/compose/runtime-backends/s3.yaml

BASE_STACK = -f $(COMPOSE_BASE)
OBSERVE_STACK = -f $(COMPOSE_OBSERVE)
TRAEFIK_STACK = -f $(COMPOSE_TRAEFIK)
MULTIPLE_STACK = -f $(COMPOSE_MULTIPLE)
OBSERVE_MULTIPLE_STACK = -f $(COMPOSE_OBSERVE_MULTIPLE)
NGINX_STACK = -f $(COMPOSE_NGINX)
PROMETHEUS_STACK = -f $(COMPOSE_BASE) -f $(COMPOSE_PROMETHEUS)
OTLP_STACK = -f $(COMPOSE_BASE) -f $(COMPOSE_OTLP)
LANGFUSE_STACK = -f $(COMPOSE_BASE) -f $(COMPOSE_LANGFUSE)
RUNTIME_REDIS_STACK = -f $(COMPOSE_RUNTIME_REDIS)
RUNTIME_POSTGRES_STACK = -f $(COMPOSE_RUNTIME_POSTGRES)
RUNTIME_S3_STACK = -f $(COMPOSE_RUNTIME_S3)

define compose_profile_stack_targets
$(1)-prod:
	$(DOCKER_COMPOSE) $(2) --profile PROD up

$(1)-prod-d:
	$(DOCKER_COMPOSE) $(2) --profile PROD up -d

$(1)-dev:
	$(DOCKER_COMPOSE) $(2) --profile DEV up

$(1)-dev-d:
	$(DOCKER_COMPOSE) $(2) --profile DEV up -d

$(1)-down:
	$(DOCKER_COMPOSE) $(2) --profile PROD --profile DEV down
endef

define compose_plain_stack_targets
$(1)-up:
	$(DOCKER_COMPOSE) $(2) up

$(1)-up-d:
	$(DOCKER_COMPOSE) $(2) up -d

$(1)-down:
	$(DOCKER_COMPOSE) $(2) down
endef

$(eval $(call compose_profile_stack_targets,compose-base,$(BASE_STACK)))
$(eval $(call compose_profile_stack_targets,compose-observe,$(OBSERVE_STACK)))
$(eval $(call compose_profile_stack_targets,compose-prometheus,$(PROMETHEUS_STACK)))
$(eval $(call compose_profile_stack_targets,compose-otlp,$(OTLP_STACK)))
$(eval $(call compose_profile_stack_targets,compose-langfuse,$(LANGFUSE_STACK)))

$(eval $(call compose_plain_stack_targets,compose-traefik,$(TRAEFIK_STACK)))
$(eval $(call compose_plain_stack_targets,compose-multiple,$(MULTIPLE_STACK)))
$(eval $(call compose_plain_stack_targets,compose-observe-multiple,$(OBSERVE_MULTIPLE_STACK)))
$(eval $(call compose_plain_stack_targets,compose-nginx,$(NGINX_STACK)))
$(eval $(call compose_plain_stack_targets,compose-runtime-redis,$(RUNTIME_REDIS_STACK)))
$(eval $(call compose_plain_stack_targets,compose-runtime-postgres,$(RUNTIME_POSTGRES_STACK)))
$(eval $(call compose_plain_stack_targets,compose-runtime-s3,$(RUNTIME_S3_STACK)))

help:
	@printf "%s\n" \
		"Deployment targets (.env is passed as --env-file):" \
		"" \
		"  make compose-base-dev-d              # single instance, DEV" \
		"  make compose-base-prod-d             # single instance, PROD" \
		"  make compose-observe-dev-d           # gpt2giga + mitmproxy" \
		"  make compose-prometheus-dev-d        # base + Prometheus" \
		"  make compose-otlp-dev-d              # base + OpenTelemetry Collector" \
		"  make compose-langfuse-dev-d          # base + Langfuse stack" \
		"  make compose-multiple-up-d           # several model-specific instances" \
		"  make compose-observe-multiple-up-d   # several instances + mitmproxy" \
		"  make compose-traefik-up-d            # several instances behind Traefik" \
		"  make compose-nginx-up-d              # local nginx example (needs nginx.conf)" \
		"  make compose-runtime-redis-up-d      # runtime backend example: Redis" \
		"  make compose-runtime-postgres-up-d   # runtime backend example: Postgres" \
		"  make compose-runtime-s3-up-d         # runtime backend example: S3/MinIO" \
		"" \
		"Use the matching *-down target to stop a stack." \
		"See deploy/README.md for the full matrix."

# Backward-compatible aliases for existing shortcuts.
compose-prod: compose-base-prod
compose-prod-d: compose-base-prod-d
compose-dev: compose-base-dev
compose-dev-d: compose-base-dev-d
compose-down: compose-base-down

observe-prod: compose-observe-prod
observe-prod-d: compose-observe-prod-d
observe-dev: compose-observe-dev
observe-dev-d: compose-observe-dev-d
observe-down: compose-observe-down

traefik: compose-traefik-up
traefik-up: compose-traefik-up-d
traefik-down: compose-traefik-down

multiple-up: compose-multiple-up
multiple-up-d: compose-multiple-up-d
multiple-down: compose-multiple-down

observe-multiple: compose-observe-multiple-up
observe-multiple-up: compose-observe-multiple-up-d
observe-multiple-up-d: compose-observe-multiple-up-d
observe-multiple-down: compose-observe-multiple-down
