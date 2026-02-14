.PHONY: up down migrate test lint

up:
	docker compose up -d --build

down:
	docker compose down

migrate:
	python backend/manage.py migrate

test:
	pytest -q backend

lint:
	ruff check backend
	npm run --prefix frontend lint
