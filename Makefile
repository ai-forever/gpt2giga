# Docker Compose targets for all compose files

.PHONY: compose-prod compose-dev compose-down observe-prod observe-prod-up observe-dev observe-down traefik traefik-up traefik-down

COMPOSE_ENV_FILE = .env
DOCKER_COMPOSE = docker compose --env-file $(COMPOSE_ENV_FILE)

# --- compose/base.yaml (базовый gpt2giga) ---
COMPOSE_BASE = compose/base.yaml

compose-prod:
	$(DOCKER_COMPOSE) -f $(COMPOSE_BASE) --profile PROD up

compose-prod-d:
	$(DOCKER_COMPOSE) -f $(COMPOSE_BASE) --profile PROD up -d

compose-dev:
	$(DOCKER_COMPOSE) -f $(COMPOSE_BASE) --profile DEV up

compose-dev-d:
	$(DOCKER_COMPOSE) -f $(COMPOSE_BASE) --profile DEV up -d

compose-down:
	$(DOCKER_COMPOSE) -f $(COMPOSE_BASE) --profile PROD --profile DEV down

# --- compose/observability.yaml (gpt2giga + mitmproxy) ---
COMPOSE_OBSERVE = compose/observability.yaml

observe-prod:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE) --profile PROD up

observe-prod-d:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE) --profile PROD up -d

observe-dev:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE) --profile DEV up

observe-dev-d:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE) --profile DEV up -d

observe-down:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE) --profile PROD --profile DEV down

# --- compose/traefik.yaml (gpt2giga + traefik) ---
COMPOSE_TRAEFIK = compose/traefik.yaml

traefik:
	$(DOCKER_COMPOSE) -f $(COMPOSE_TRAEFIK) up

traefik-up:
	$(DOCKER_COMPOSE) -f $(COMPOSE_TRAEFIK) up -d

traefik-down:
	$(DOCKER_COMPOSE) -f $(COMPOSE_TRAEFIK) down


COMPOSE_OBSERVE_MULTIPLE = compose/observe-multiple.yaml

observe-multiple:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE_MULTIPLE) up

observe-multiple-up:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE_MULTIPLE) up -d

observe-multiple-down:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE_MULTIPLE) down
