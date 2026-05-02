# Auger Platform - Makefile
# Convenient commands for Docker operations

.PHONY: help build run ui test clean shell logs

# Use docker compose (v2) instead of docker-compose (v1)
DOCKER_COMPOSE = docker compose

help:
	@echo "Auger Platform - Docker Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make setup       - Create .env file from template"
	@echo ""
	@echo "Development:"
	@echo "  make build       - Build Docker image"
	@echo "  make ui          - Start Auger Platform UI (launches GUI)"
	@echo "  make run         - Run container (bash shell, detached)"
	@echo "  make shell       - Open bash shell in running container"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run automated test in clean environment"
	@echo "  make test-shell  - Open shell in test container"
	@echo "  make test-build  - Build test image"
	@echo ""
	@echo "Maintenance:"
	@echo "  make logs        - Show container logs"
	@echo "  make stop        - Stop all containers"
	@echo "  make clean       - Remove containers and images"
	@echo "  make reset       - Full reset (clean + remove volumes)"

setup:
	@mkdir -p $(HOME)/.auger
	@if [ ! -f $(HOME)/.auger/.env ]; then \
		cp .env.example $(HOME)/.auger/.env; \
		chmod 600 $(HOME)/.auger/.env; \
		echo "✅ Created $(HOME)/.auger/.env"; \
		echo "⚠️  Edit it and add your tokens: vim $(HOME)/.auger/.env"; \
	else \
		echo "⚠️  $(HOME)/.auger/.env already exists"; \
	fi

build:
	$(DOCKER_COMPOSE) build

ui:
	@echo "🚀 Starting Auger Platform UI..."
	@xhost +local:docker 2>/dev/null || true
	@mkdir -p $(HOME)/.auger
	DOCKER_UID=$(shell id -u) DOCKER_GID=$(shell id -g) $(DOCKER_COMPOSE) up -d
	docker exec -e DISPLAY=$(DISPLAY) auger-platform auger start

run:
	@echo "Starting Auger Platform container..."
	@echo "Run 'make shell' to access, 'make ui' to launch GUI"
	DOCKER_UID=$(shell id -u) DOCKER_GID=$(shell id -g) $(DOCKER_COMPOSE) up -d
	$(DOCKER_COMPOSE) logs -f

shell:
	$(DOCKER_COMPOSE) exec auger /bin/bash

test-build:
	$(DOCKER_COMPOSE) -f docker-compose.test.yml build

test:
	@echo "🧪 Running automated tests in clean environment..."
	$(DOCKER_COMPOSE) -f docker-compose.test.yml up --build --abort-on-container-exit
	$(DOCKER_COMPOSE) -f docker-compose.test.yml down

test-shell:
	$(DOCKER_COMPOSE) -f docker-compose.test.yml run --rm auger-test /bin/bash

logs:
	$(DOCKER_COMPOSE) logs -f

stop:
	$(DOCKER_COMPOSE) down
	$(DOCKER_COMPOSE) -f docker-compose.test.yml down

clean: stop
	$(DOCKER_COMPOSE) down --rmi all
	$(DOCKER_COMPOSE) -f docker-compose.test.yml down --rmi all

reset: clean
	$(DOCKER_COMPOSE) down -v
	@echo "✅ Full reset complete"

# Quick test with your actual token
quick-test:
	@if [ -z "$$GITHUB_COPILOT_TOKEN" ] && [ -f .env ]; then \
		export $$(cat .env | grep GITHUB_COPILOT_TOKEN | xargs) && \
		$(DOCKER_COMPOSE) -f docker-compose.test.yml up --build --abort-on-container-exit; \
	else \
		$(DOCKER_COMPOSE) -f docker-compose.test.yml up --build --abort-on-container-exit; \
	fi
	$(DOCKER_COMPOSE) -f docker-compose.test.yml down
