# Task Hub v1 Getting Started Plan (Agent-Executable)

## Goal
Build Task Hub v1 in a deterministic sequence that an AI coding agent can execute end-to-end with clear gates, resumability, and security controls.

## 0. Agent Execution Contract
1. Execute steps strictly in numeric order.
2. Do not skip a step or mark complete without passing all listed validation commands.
3. Use latest stable dependency and image versions available at execution time, then lock them.
4. Never commit secrets. Commit only `.env.example` and non-sensitive defaults.
5. If a validation command fails: retry once, apply minimal fix, rerun; if still failing, stop and log blocker.
6. After each successful step: update `docs/progress/step-status.md`, append `docs/progress/run-log.md`, and create the step commit.
7. Keep changes scoped to the step's listed files plus generated lockfiles/migrations/tests.
8. Security gates in `Spec/dependency-security-checklist.md` are mandatory release gates.
9. Treat backend as authoritative for filtering, sorting, ordering, pagination, and manual task ordering; frontend must not implement client-only list ordering logic.

## 1. Required Inputs And Tooling
Required inputs:
- `GITHUB_REPO_URL` (for `origin` remote).

Required local tools:
- Docker + Docker Compose
- Python 3.12+
- Node 22 LTS+

Install required security tools before running step validations:
```bash
python -m pip install --upgrade pip pip-tools pip-audit
if ! command -v trivy >/dev/null 2>&1; then
  curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sudo sh -s -- -b /usr/local/bin
fi
```

## 2. Fixed Tooling Decisions (Do Not Re-Decide During Execution)
- Backend framework: Django + Django REST Framework.
- Worker and queue: Celery + Redis.
- Database: PostgreSQL + pgvector.
- Frontend: React + Vite + PWA.
- Python dependency management: `pip-tools` with `requirements.in` -> locked `requirements.txt`.
- Node package manager: `npm` with committed `package-lock.json`.
- Python lint/format: `ruff`.
- Frontend lint/format: `eslint` + `prettier`.
- Backend tests: `pytest` + `pytest-django`.
- Frontend tests: `vitest`.
- Security scans: `pip-audit`, `npm audit`, `trivy`.
- JWT auth library: `djangorestframework-simplejwt`.
- Custom user model: define `AUTH_USER_MODEL` before first migration.

## 3. Resume Protocol
Use these files to support stop/resume across agent runs:
- `docs/progress/step-status.md`
- `docs/progress/run-log.md`

Required `docs/progress/step-status.md` format:
```md
# Step Status

- [ ] Step 1 - Repository bootstrap
- [ ] Step 2 - Project scaffold and dependency locking
- [ ] Step 3 - CI baseline and branch protection
- [ ] Step 4 - Docker compose foundation
- [ ] Step 5 - Schema migration set 001_core
- [ ] Step 6 - Schema migration set 002_collab_ai
- [ ] Step 7 - Schema migration set 003_privacy_controls
- [ ] Step 8 - Auth and tenant context
- [ ] Step 9 - RBAC policy enforcement
- [ ] Step 10 - Core tasks API
- [ ] Step 11 - Projects, tags, views API
- [ ] Step 12 - Integration test gate
- [ ] Step 13 - Frontend MVP shell
- [ ] Step 14 - Worker, AI abstraction, semantic search, dedupe
- [ ] Step 15 - Weekly review, bookmarklet, ops hardening
```

Required `docs/progress/run-log.md` entry format:
```md
## YYYY-MM-DD HH:MM UTC - Step N
- Commands run:
- Files changed:
- Validation results:
- Commit:
- Notes/blockers:
```

## 4. Repository Bootstrap Commands (Idempotent)
Run once before Step 1 validations:
```bash
mkdir -p backend frontend infra docs docs/progress .github/workflows Spec

[ -f .gitignore ] || cat > .gitignore <<'GITIGNORE'
.venv/
__pycache__/
*.pyc
node_modules/
dist/
.env
.env.*
!.env.example
.DS_Store
GITIGNORE

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git init
fi
git branch -M main

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$GITHUB_REPO_URL"
else
  git remote add origin "$GITHUB_REPO_URL"
fi
```

## 5. Step Plan

### Step 1 - Repository Bootstrap
Inputs:
- `Spec/spec.md`
- `Spec/dependency-security-checklist.md`

Files to create/update:
- `.editorconfig`
- `.pre-commit-config.yaml`
- `Makefile`
- `.env.example`
- `docs/progress/step-status.md`
- `docs/progress/run-log.md`
- `.github/workflows/dependency-security.yml`

Commands:
```bash
cat > .editorconfig <<'EOF_EDITOR'
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 2
trim_trailing_whitespace = true
EOF_EDITOR

cat > .pre-commit-config.yaml <<'EOF_PRECOMMIT'
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: end-of-file-fixer
      - id: trailing-whitespace
EOF_PRECOMMIT

cat > Makefile <<'EOF_MAKE'
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
EOF_MAKE

cat > .env.example <<'EOF_ENV'
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=False
DATABASE_URL=postgres://postgres:postgres@db:5432/taskhub
REDIS_URL=redis://redis:6379/0
AI_MODE=off
AI_LOCAL_BASE_URL=http://local-ai:8000
AI_CLOUD_PROVIDER=
AI_CLOUD_API_KEY=
AI_DEFAULT_MODEL=
AI_DEFAULT_EMBED_MODEL=
EOF_ENV

cat > docs/progress/step-status.md <<'EOF_STATUS'
# Step Status

- [ ] Step 1 - Repository bootstrap
- [ ] Step 2 - Project scaffold and dependency locking
- [ ] Step 3 - CI baseline and branch protection
- [ ] Step 4 - Docker compose foundation
- [ ] Step 5 - Schema migration set 001_core
- [ ] Step 6 - Schema migration set 002_collab_ai
- [ ] Step 7 - Schema migration set 003_privacy_controls
- [ ] Step 8 - Auth and tenant context
- [ ] Step 9 - RBAC policy enforcement
- [ ] Step 10 - Core tasks API
- [ ] Step 11 - Projects, tags, views API
- [ ] Step 12 - Integration test gate
- [ ] Step 13 - Frontend MVP shell
- [ ] Step 14 - Worker, AI abstraction, semantic search, dedupe
- [ ] Step 15 - Weekly review, bookmarklet, ops hardening
EOF_STATUS

cat > docs/progress/run-log.md <<'EOF_RUNLOG'
## YYYY-MM-DD HH:MM UTC - Step N
- Commands run:
- Files changed:
- Validation results:
- Commit:
- Notes/blockers:
EOF_RUNLOG

cat > .github/workflows/dependency-security.yml <<'EOF_SECURITY_CI'
name: Dependency Security Scan

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  schedule:
    - cron: "0 9 * * 1"
  workflow_dispatch:

jobs:
  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: Validate lockfiles
        run: |
          if [ -d backend ] && [ ! -f backend/requirements.txt ]; then
            echo "Missing backend/requirements.txt"
            exit 1
          fi
          if [ -d frontend ] && [ ! -f frontend/package-lock.json ]; then
            echo "Missing frontend/package-lock.json"
            exit 1
          fi
      - name: Python audit
        if: ${{ hashFiles('backend/requirements.txt') != '' }}
        run: |
          python -m pip install --upgrade pip
          pip install pip-audit
          pip-audit -r backend/requirements.txt
      - name: Node audit
        if: ${{ hashFiles('frontend/package-lock.json') != '' }}
        run: npm audit --prefix frontend --audit-level=high
      - name: Trivy scan
        uses: aquasecurity/trivy-action@0.28.0
        with:
          scan-type: fs
          scan-ref: .
          severity: HIGH,CRITICAL
          exit-code: "1"
EOF_SECURITY_CI
```

Validation:
```bash
test -f .editorconfig
test -f .pre-commit-config.yaml
test -f Makefile
test -f .env.example
test -f docs/progress/step-status.md
test -f docs/progress/run-log.md
test -f .github/workflows/dependency-security.yml
```

Expected artifacts:
- Repository baseline committed and ready for scaffold work.

Commit checkpoint:
- `chore(bootstrap): initialize repository standards and progress tracking`

### Step 2 - Project Scaffold and Dependency Locking
Inputs:
- Step 1 artifacts

Files to create/update:
- `backend/requirements.in`
- `backend/requirements.txt`
- `backend/manage.py`
- `backend/config/*`
- `frontend/package.json`
- `frontend/package-lock.json`

Commands:
```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip pip-tools

cat > backend/requirements.in <<'REQ'
Django
djangorestframework
djangorestframework-simplejwt
psycopg[binary]
celery
redis
pgvector
pytest
pytest-django
ruff
pip-audit
REQ

pip-compile --upgrade --output-file backend/requirements.txt backend/requirements.in
python -m pip install -r backend/requirements.txt

django-admin startproject config backend

cd frontend
npm create vite@latest . -- --template react
npm install
npm install -D eslint prettier vitest
npm pkg set scripts.lint="eslint ."
npm pkg set scripts.test="vitest run"
npm pkg set scripts.build="vite build"
cd ..
```

Validation:
```bash
test -f backend/requirements.txt
test -f backend/manage.py
test -f frontend/package-lock.json
npm pkg get scripts.lint --prefix frontend | grep -q eslint
npm pkg get scripts.test --prefix frontend | grep -q vitest
npm pkg get scripts.build --prefix frontend | grep -q "vite build"
. .venv/bin/activate && pip-audit -r backend/requirements.txt
npm audit --prefix frontend --audit-level=high
```

Expected artifacts:
- Locked backend/frontend dependencies and initial Django + React scaffolds.

Commit checkpoint:
- `chore(scaffold): add django and react scaffolds with locked dependencies`

### Step 3 - CI Baseline And Branch Protection
Inputs:
- Step 2 artifacts

Files to create/update:
- `.github/workflows/ci.yml`
- `docs/github-branch-protection.md`

Commands:
```bash
cat > .github/workflows/ci.yml <<'EOF_CI'
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: Install backend deps
        run: |
          python -m pip install --upgrade pip
          pip install -r backend/requirements.txt
      - name: Backend tests
        run: |
          if [ -d backend/tests ]; then
            pytest -q backend
          else
            python backend/manage.py check
          fi
      - name: Frontend install and build
        run: |
          npm ci --prefix frontend
          npm run --prefix frontend build
EOF_CI

cat > docs/github-branch-protection.md <<'EOF_BP'
# GitHub Branch Protection (main)

Require pull request before merge: enabled
Require status checks to pass before merge: enabled
Required checks:
- CI / test
- Dependency Security Scan / Dependency And Image Security Scan
Restrict direct pushes to main: enabled
EOF_BP
```

Validation:
```bash
test -f .github/workflows/ci.yml
test -f docs/github-branch-protection.md
```

Expected artifacts:
- Non-security CI checks enforced alongside security scans.

Commit checkpoint:
- `ci: add build-and-test workflow and branch protection policy`

### Step 4 - Docker Compose Foundation
Inputs:
- Step 3 artifacts

Files to create/update:
- `docker-compose.yml`
- `infra/api/Dockerfile`
- `infra/worker/Dockerfile`
- `infra/web/Dockerfile`
- `infra/api/entrypoint.sh`

Commands:
```bash
mkdir -p infra/api infra/worker infra/web

cat > infra/api/entrypoint.sh <<'EOF_ENTRY'
#!/usr/bin/env sh
set -eu
python backend/manage.py migrate
exec "$@"
EOF_ENTRY
chmod +x infra/api/entrypoint.sh

cat > infra/api/Dockerfile <<'EOF_API_DOCKERFILE'
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY infra/api/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "backend/manage.py", "runserver", "0.0.0.0:8000"]
EOF_API_DOCKERFILE

cat > infra/worker/Dockerfile <<'EOF_WORKER_DOCKERFILE'
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
CMD ["celery", "-A", "config", "worker", "-l", "info"]
EOF_WORKER_DOCKERFILE

cat > infra/web/Dockerfile <<'EOF_WEB_DOCKERFILE'
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
EOF_WEB_DOCKERFILE

cat > docker-compose.yml <<'EOF_COMPOSE'
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_DB: taskhub
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d taskhub"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build:
      context: .
      dockerfile: infra/api/Dockerfile
    env_file:
      - .env.example
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:8000/health/live || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10

  worker:
    build:
      context: .
      dockerfile: infra/worker/Dockerfile
    env_file:
      - .env.example
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  web:
    build:
      context: .
      dockerfile: infra/web/Dockerfile
    ports:
      - "8080:80"
    depends_on:
      api:
        condition: service_started
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10

volumes:
  postgres_data:
EOF_COMPOSE
```

Validation:
```bash
docker compose config >/dev/null
docker compose up -d --build
docker compose ps
docker compose ps --status running | grep -q api
docker compose ps --status running | grep -q worker
docker compose ps --status running | grep -q web
docker compose down
```

Expected artifacts:
- Services: `db`, `redis`, `api`, `worker`, `web`, optional `local-ai` with health checks.

Commit checkpoint:
- `feat(infra): add docker compose stack with migration-before-serve startup`

### Step 5 - Schema Migration Set `001_core`
Inputs:
- Step 4 artifacts
- `Spec/spec.md` sections 3 and 4

Files to create/update:
- Django apps/models for `organization`, custom `user`, `task`, `project`, `tag`, `task_tag`
- `backend/config/settings.py` with `AUTH_USER_MODEL` defined before first migration
- migration files for `001_core`

Commands:
```bash
. .venv/bin/activate
python backend/manage.py makemigrations
python backend/manage.py migrate
```

Validation:
```bash
. .venv/bin/activate
python backend/manage.py migrate --check
pytest -q backend -k "models or migration"
```

Expected artifacts:
- `001_core` committed with custom user model in place from first migration.

Commit checkpoint:
- `feat(db): add core tenancy and task schema (001_core)`

### Step 6 - Schema Migration Set `002_collab_ai`
Inputs:
- Step 5 artifacts
- `Spec/spec.md` sections 5, 6.3, and 7 views model

Files to create/update:
- models/migrations for `view`, `ai_job`, `task_ai_suggestion`, `task_embedding`, `review_summary`

Commands:
```bash
. .venv/bin/activate
python backend/manage.py makemigrations
python backend/manage.py migrate
```

Validation:
```bash
. .venv/bin/activate
python backend/manage.py migrate --check
pytest -q backend -k "ai_job or task_embedding or review_summary or views"
```

Expected artifacts:
- `002_collab_ai` committed and migration-safe.

Commit checkpoint:
- `feat(db): add collaboration and ai schema (002_collab_ai)`

### Step 7 - Schema Migration Set `003_privacy_controls`
Inputs:
- Step 6 artifacts
- `Spec/spec.md` section 11

Files to create/update:
- models/migrations for org and task privacy controls

Commands:
```bash
. .venv/bin/activate
python backend/manage.py makemigrations
python backend/manage.py migrate
```

Validation:
```bash
. .venv/bin/activate
python backend/manage.py migrate --check
pytest -q backend -k "privacy or cloud"
```

Expected artifacts:
- `003_privacy_controls` committed.

Commit checkpoint:
- `feat(db): add privacy controls schema (003_privacy_controls)`

### Step 8 - Auth and Tenant Context
Inputs:
- Step 7 artifacts
- `Spec/spec.md` section 7.1/7 Auth contract

Files to create/update:
- auth endpoints: `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`
- JWT settings and middleware/context utilities (`user_id`, `organization_id`, `role`)
- standardized error response envelope (`error_code`, `message`, `details`, `request_id`)
- tests for auth flows and cross-tenant `404`

Validation:
```bash
. .venv/bin/activate
pytest -q backend -k "auth or tenant"
```

Expected artifacts:
- Auth endpoints and token flows match spec contract.

Commit checkpoint:
- `feat(auth): implement jwt auth and tenant context enforcement`

### Step 9 - RBAC Policy Enforcement
Inputs:
- Step 8 artifacts
- `Spec/spec.md` section 10

Files to create/update:
- RBAC policy module
- endpoint permission classes
- `docs/rbac-matrix.md`
- RBAC tests

Validation:
```bash
. .venv/bin/activate
pytest -q backend -k "rbac or permissions"
```

Expected artifacts:
- Owner/admin/member rules enforced with tests.

Commit checkpoint:
- `feat(rbac): enforce role-based access policy across api`

### Step 10 - Core Tasks API
Inputs:
- Step 9 artifacts
- `Spec/spec.md` sections 4.4 and 7 Tasks

Files to create/update:
- task serializers/views/routes/services
- transition validation logic
- filtering/pagination/sort allowlist
- backend-persisted ordering support (position field and/or reorder endpoint contract)
- tests for transition `409`, semantic request contract fields, and fallback metadata fields
- tests that list order/filter/pagination behavior is enforced server-side

Validation:
```bash
. .venv/bin/activate
pytest -q backend -k "tasks"
```

Expected artifacts:
- `POST/GET/PATCH/DELETE /tasks`, complete/reopen endpoints working.
- Filtering/pagination/sort/order and manual reorder persistence enforced by backend contracts.

Commit checkpoint:
- `feat(tasks): implement core task api with transitions and filtering`

### Step 11 - Projects, Tags, Views API
Inputs:
- Step 10 artifacts
- `Spec/spec.md` section 7 Projects/Tags/Views

Files to create/update:
- models/endpoints for projects, tags, saved views
- relation integrity validation
- API tests

Validation:
```bash
. .venv/bin/activate
pytest -q backend -k "projects or tags or views"
```

Expected artifacts:
- API coverage for project/tag/view flows.

Commit checkpoint:
- `feat(organization): add projects tags and saved views api`

### Step 12 - Integration Test Gate
Inputs:
- Steps 8-11 artifacts

Files to create/update:
- integration test suite
- CI wiring to run integration tests
- integration cases for backend-owned sorting/pagination/order semantics

Validation:
```bash
. .venv/bin/activate
pytest -q backend/tests/integration
```

Expected artifacts:
- CI-blocking integration tests for tenancy, RBAC, transitions, and migration startup behavior.

Commit checkpoint:
- `test(integration): add tenancy rbac transitions and startup gate tests`

### Step 13 - Frontend MVP Shell
Inputs:
- Step 12 artifacts

Files to create/update:
- React app shell (sidebar/topbar/task list/quick add)
- auth flow pages
- mobile default route quick add
- API client integration for tasks/search toggle
- frontend query-state wiring that delegates sorting/pagination/order/reorder to backend APIs (no client-only ordering)

Validation:
```bash
npm run --prefix frontend lint
npm run --prefix frontend test
npm run --prefix frontend build
```

Expected artifacts:
- Login and task creation/view flows on desktop/mobile.

Commit checkpoint:
- `feat(frontend): add mvp pwa shell with auth and quick add`

### Step 14 - Worker, AI Abstraction, Semantic Search, Dedupe
Inputs:
- Step 13 artifacts
- `Spec/spec.md` sections 5 and 6

Files to create/update:
- provider interface (`generate_completion`, `generate_embedding`)
- local/cloud/hybrid provider implementations
- celery jobs for suggest/embed/dedupe/weekly review
- semantic ranking and fallback logic
- dedupe threshold logic
- privacy gate enforcement before cloud calls

Validation:
```bash
. .venv/bin/activate
pytest -q backend -k "ai or celery or semantic or dedupe or privacy"
```

Expected artifacts:
- Background jobs execute and semantic search/dedupe behavior matches spec.

Commit checkpoint:
- `feat(ai): add provider abstraction jobs semantic search and dedupe`

### Step 15 - Weekly Review, Bookmarklet, Ops Hardening
Inputs:
- Step 14 artifacts
- `Spec/dependency-security-checklist.md`

Files to create/update:
- weekly review job and storage
- bookmarklet-compatible capture endpoint
- backup/restore runbook
- dependency/image refresh runbook

Validation:
```bash
. .venv/bin/activate
pytest -q backend
npm run --prefix frontend build
trivy fs --severity HIGH,CRITICAL --exit-code 1 --no-progress .
```

Expected artifacts:
- v1-ready deployment docs and operational safeguards.

Commit checkpoint:
- `chore(ops): finalize weekly review capture and production hardening`

## 6. Final Acceptance Gate (Must All Pass)
```bash
docker compose config >/dev/null
. .venv/bin/activate && pytest -q backend
. .venv/bin/activate && pytest -q backend/tests/integration
npm run --prefix frontend build
pip-audit -r backend/requirements.txt
npm audit --prefix frontend --audit-level=high
trivy fs --severity HIGH,CRITICAL --exit-code 1 --no-progress .
```

If all commands pass, tag release candidate:
```bash
git tag -a v1.0.0-rc1 -m "Task Hub v1 RC1"
```
