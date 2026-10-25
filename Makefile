# TikTok Intelligence Bot — developer shortcuts
SHELL := /bin/bash
COMPOSE = docker compose -f docker/docker-compose.yml --env-file docker/.env

.PHONY: help install migrate bot worker beat test compose-up compose-down \
        compose-logs backup clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies (dev)
	pip install -r requirements.txt

migrate: ## Create/update database schema
	python scripts/migrate.py

bot: ## Run the bot (polling by default)
	python bot/main.py

worker: ## Run Celery worker (with embedded beat)
	celery -A bot.tasks worker --loglevel=info -B

beat: ## Run dedicated Celery beat scheduler
	celery -A bot.tasks beat --loglevel=info

test: ## Run the test suite
	pytest tests/ -v

compose-up: ## Start full production stack (postgres, redis, bot, worker, beat, nginx, prometheus, grafana)
	$(COMPOSE) up -d --build

compose-down: ## Stop the stack
	$(COMPOSE) down

compose-logs: ## Tail bot logs
	$(COMPOSE) logs -f --tail=100 bot

backup: ## Manual database backup
	python scripts/backup.py

clean: ## Remove caches and temp artifacts (keeps data/)
	find . -type d -name __pycache__ -prune -exec rm -rf {} \; 2>/dev/null || true
	rm -rf .pytest_cache
