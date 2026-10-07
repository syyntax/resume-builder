# Resume Tailor

A self-hosted, multi-user web app that tailors a master résumé (and, soon, a cover letter) to each job
posting with Claude, then exports polished PDF, DOCX, Markdown or JSON. See [DESIGN.md](DESIGN.md) for
the full design and [mockups/](mockups/index.html) for the approved templates.

**Status:** milestone M1 (foundations and accounts) is built. You can create accounts and upload, validate,
version and download master résumés. AI tailoring arrives in M2.

## Run it

You only need Docker.

```bash
cp .env.example .env              # then set APP_SECRET_KEY (openssl rand -base64 32)
docker compose up -d --build
docker compose logs app | grep "Setup token"
```

Open http://localhost:8080/setup, paste the setup token and create the admin account. After that, other
people can register (open registration is the default; switch to invite-only under **Admin → Registration**).

This folder syncs to OneDrive, so consider keeping your real env file outside it:

```bash
RT_ENV_FILE=~/.config/resume-tailor/.env docker compose up -d --build
```

Data lives in the `app-data` Docker volume, not in this folder. Optional extras:

| | |
|---|---|
| HTTPS via Caddy | `docker compose --profile https up -d` (set `SITE_ADDRESS` and an `https://` `APP_BASE_URL`) |
| PostgreSQL | `docker compose --profile postgres up -d` (set `POSTGRES_PASSWORD` and `DATABASE_URL`) |

## Admin tasks

```bash
docker compose exec app resume-tailor admin list
docker compose exec app resume-tailor admin create --email you@example.com --name "Your Name"
docker compose exec app resume-tailor admin reset-password --email you@example.com
docker compose exec app resume-tailor setup-token   # new setup token, before the first account exists
```

## Develop

```bash
make dev     # hot-reloading backend on :8080 and Vite dev server on http://localhost:5173
make test    # backend (pytest) and frontend (tsc + vitest), both in Docker
make api-types   # after changing the API: regenerate schema/openapi.json and the frontend types
```

| Path | What |
|---|---|
| `backend/` | FastAPI app (Python 3.13): `app/auth` sign-in and sessions, `app/masters` schema normalization, `app/api` routes |
| `frontend/` | React 19 + TypeScript + Tailwind single-page app |
| `schema/` | Generated JSON Schema for master résumés, an example, and the OpenAPI document |
| `mockups/` | Static template mockups (Meridian, Atlas, Ledger, Vanguard) |
| `deploy/` | Caddy config for the `https` profile |

Your master résumé is JSON; point your editor at the schema for autocomplete by adding
`"$schema": "http://localhost:8080/schema/master-resume.schema.json"` to the file. The example is in
[`schema/examples/master-resume.example.json`](schema/examples/master-resume.example.json).
