# Everything runs in Docker, so only Docker is needed on the host.
NODE = docker run --rm -v "$(CURDIR)":/repo -v rt-fe-node-modules:/repo/frontend/node_modules \
       -v rt-pnpm-store:/pnpm-store -w /repo/frontend node:24-slim sh -c
PNPM = corepack enable >/dev/null 2>&1; pnpm config set store-dir /pnpm-store >/dev/null;

.PHONY: up down logs setup-token dev test test-backend test-frontend build api-types thumbnails evals

up:            ## build and start the app at http://localhost:8080
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f app

setup-token:   ## print the first-run setup token
	docker compose logs app | grep "Setup token" | tail -1

dev:           ## hot-reloading backend + Vite dev server on http://localhost:5173
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

test: test-backend test-frontend

test-backend:
	docker build --target test -t resume-tailor:test .
	docker run --rm resume-tailor:test

test-frontend:
	$(NODE) '$(PNPM) pnpm install --frozen-lockfile && pnpm typecheck && pnpm test'

api-types:     ## regenerate schema/openapi.json and frontend/src/api/schema.d.ts
	docker run --rm -v "$(CURDIR)/schema":/schema resume-tailor:latest resume-tailor openapi --out /schema/openapi.json
	$(NODE) '$(PNPM) pnpm gen:api'

thumbnails:    ## after changing a template: regenerate the gallery thumbnails (backend/app/render/templates/*/thumbnail.png)
	docker build --target test -t resume-tailor:test .
	docker run --rm -v "$(CURDIR)/backend/app/render/templates":/app/app/render/templates resume-tailor:test \
		python -m app.render.thumbnails

evals:         ## the evals, offline; live (costs money): EVAL_ANTHROPIC_API_KEY=... make evals ARGS=--live
	docker build --target test -t resume-tailor:test .
	mkdir -p eval-results
	docker run --rm --user "$$(id -u):$$(id -g)" -e EVAL_ANTHROPIC_API_KEY \
		-v "$(CURDIR)/eval-results":/app/eval-results -v "$(CURDIR)/backend/tests/evals":/app/tests/evals \
		resume-tailor:test python -m tests.evals $(ARGS)
