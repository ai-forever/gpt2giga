# Docker Compose targets for all compose files

.PHONY: compose-prod compose-dev compose-down observe-prod observe-prod-up observe-dev observe-down traefik traefik-up traefik-down

# --- compose/base.yaml (базовый gpt2giga) ---
COMPOSE_BASE = compose/base.yaml

compose-prod:
	docker compose -f $(COMPOSE_BASE) --profile PROD up

compose-prod-d:
	docker compose -f $(COMPOSE_BASE) --profile PROD up -d

compose-dev:
	docker compose -f $(COMPOSE_BASE) --profile DEV up

compose-dev-d:
	docker compose -f $(COMPOSE_BASE) --profile DEV up -d

compose-down:
	docker compose -f $(COMPOSE_BASE) --profile PROD --profile DEV down

# --- compose/observability.yaml (gpt2giga + mitmproxy) ---
COMPOSE_OBSERVE = compose/observability.yaml

observe-prod:
	docker compose -f $(COMPOSE_OBSERVE) --profile PROD up

observe-prod-d:
	docker compose -f $(COMPOSE_OBSERVE) --profile PROD up -d

observe-dev:
	docker compose -f $(COMPOSE_OBSERVE) --profile DEV up

observe-dev-d:
	docker compose -f $(COMPOSE_OBSERVE) --profile DEV up -d

observe-down:
	docker compose -f $(COMPOSE_OBSERVE) --profile PROD --profile DEV down

# --- compose/traefik.yaml (gpt2giga + traefik) ---
COMPOSE_TRAEFIK = compose/traefik.yaml

traefik:
	docker compose -f $(COMPOSE_TRAEFIK) up

traefik-up:
	docker compose -f $(COMPOSE_TRAEFIK) up -d

traefik-down:
	docker compose -f $(COMPOSE_TRAEFIK) down


COMPOSE_OBSERVE_MULTIPLE = compose/observe-multiple.yaml

observe-multiple:
	docker compose -f $(COMPOSE_OBSERVE_MULTIPLE) up

observe-multiple-up:
	docker compose -f $(COMPOSE_OBSERVE_MULTIPLE) up -d

observe-multiple-down:
	docker compose -f $(COMPOSE_OBSERVE_MULTIPLE) down
