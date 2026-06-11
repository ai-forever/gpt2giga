# Docker Compose targets for deploy files.

.PHONY: compose-prod compose-prod-d compose-dev compose-dev-d compose-down
.PHONY: phoenix-prod phoenix-prod-d phoenix-dev phoenix-dev-d phoenix-down
.PHONY: super-prod super-prod-d super-dev super-dev-d super-down
.PHONY: phoenix-mitm-prod phoenix-mitm-prod-d phoenix-mitm-dev phoenix-mitm-dev-d phoenix-mitm-down
.PHONY: observe-prod observe-prod-d observe-dev observe-dev-d observe-down
.PHONY: traefik traefik-up traefik-down
.PHONY: observe-multiple observe-multiple-up observe-multiple-down

COMPOSE_ENV_FILE = .env
DOCKER_COMPOSE = docker compose --env-file $(COMPOSE_ENV_FILE)

# --- deploy/base.yaml (базовый gpt2giga) ---
COMPOSE_BASE = deploy/base.yaml

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

# --- deploy/base.yaml + deploy/phoenix.yaml (gpt2giga + Phoenix) ---
COMPOSE_PHOENIX = deploy/phoenix.yaml
COMPOSE_BASE_PHOENIX = -f $(COMPOSE_BASE) -f $(COMPOSE_PHOENIX)

phoenix-prod:
	$(DOCKER_COMPOSE) $(COMPOSE_BASE_PHOENIX) --profile PROD --profile phoenix up --build

phoenix-prod-d:
	$(DOCKER_COMPOSE) $(COMPOSE_BASE_PHOENIX) --profile PROD --profile phoenix up -d --build

phoenix-dev:
	$(DOCKER_COMPOSE) $(COMPOSE_BASE_PHOENIX) --profile DEV --profile phoenix up --build

phoenix-dev-d:
	$(DOCKER_COMPOSE) $(COMPOSE_BASE_PHOENIX) --profile DEV --profile phoenix up -d --build

phoenix-down:
	$(DOCKER_COMPOSE) $(COMPOSE_BASE_PHOENIX) --profile PROD --profile DEV --profile phoenix down

# --- base + phoenix + mitmproxy (gpt2giga + Phoenix + intercepted upstream traffic) ---
COMPOSE_MITMPROXY = deploy/mitmproxy.yaml
COMPOSE_SUPER = $(COMPOSE_BASE_PHOENIX) -f $(COMPOSE_MITMPROXY)

super-prod:
	$(DOCKER_COMPOSE) $(COMPOSE_SUPER) --profile PROD --profile phoenix --profile mitmproxy up --build

super-prod-d:
	$(DOCKER_COMPOSE) $(COMPOSE_SUPER) --profile PROD --profile phoenix --profile mitmproxy up -d --build

super-dev:
	$(DOCKER_COMPOSE) $(COMPOSE_SUPER) --profile DEV --profile phoenix --profile mitmproxy up --build

super-dev-d:
	$(DOCKER_COMPOSE) $(COMPOSE_SUPER) --profile DEV --profile phoenix --profile mitmproxy up -d --build

super-down:
	$(DOCKER_COMPOSE) $(COMPOSE_SUPER) --profile PROD --profile DEV --profile phoenix --profile mitmproxy down

phoenix-mitm-prod: super-prod

phoenix-mitm-prod-d: super-prod-d

phoenix-mitm-dev: super-dev

phoenix-mitm-dev-d: super-dev-d

phoenix-mitm-down: super-down

# --- deploy/observability.yaml (gpt2giga + mitmproxy) ---
COMPOSE_OBSERVE = deploy/observability.yaml

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

# --- deploy/traefik.yaml (gpt2giga + traefik) ---
COMPOSE_TRAEFIK = deploy/traefik.yaml

traefik:
	$(DOCKER_COMPOSE) -f $(COMPOSE_TRAEFIK) up

traefik-up:
	$(DOCKER_COMPOSE) -f $(COMPOSE_TRAEFIK) up -d

traefik-down:
	$(DOCKER_COMPOSE) -f $(COMPOSE_TRAEFIK) down


COMPOSE_OBSERVE_MULTIPLE = deploy/observe-multiple.yaml

observe-multiple:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE_MULTIPLE) up

observe-multiple-up:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE_MULTIPLE) up -d

observe-multiple-down:
	$(DOCKER_COMPOSE) -f $(COMPOSE_OBSERVE_MULTIPLE) down
