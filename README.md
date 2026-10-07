# Resume Tailor

A self-hosted, multi-user web app that tailors a master résumé (and, soon, a cover letter) to each job
posting with Claude, then exports polished PDF, DOCX, Markdown or JSON. See [DESIGN.md](DESIGN.md) for
the full design and [mockups/](mockups/index.html) for the approved templates.

**Status:** milestones M1 (accounts, master résumés), M2 (AI tailoring) and M3 (résumé import and the master
editor) are built. Add your Anthropic API key under **Account → AI**, import your existing PDF or Word résumé
(or upload JSON), review and edit it, then paste a job posting under **Applications** to get a tailored,
fact-checked résumé you can export as Markdown or JSON. Styled PDF/DOCX templates and cover letters come in
later milestones.

## Run it

You only need Docker.

```bash
cp .env.example .env              # then set APP_SECRET_KEY (openssl rand -base64 32)
docker compose up -d --build
docker compose logs app | grep "Setup token"
```

Open http://localhost:8080/setup, paste the setup token and create the admin account. After that, other
people can register (open registration is the default; switch to invite-only under **Admin → Registration**).
Each person adds their own Anthropic API key under **Account → AI**; it's verified, stored encrypted, and never
shown again. AI usage is billed to that key, under a monthly cap ($20 by default).

To try the app without an API key, set `AI_PROVIDER=fake` in your env file: a deterministic offline stand-in
fills in the AI steps (mechanically, so the output isn't real tailoring).

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
docker compose exec app resume-tailor keys rotate    # after changing APP_SECRET_KEY (set APP_SECRET_KEY_PREVIOUS)
```

## Develop

```bash
make dev     # hot-reloading backend on :8080 and Vite dev server on http://localhost:5173
make test    # backend (pytest) and frontend (tsc + vitest), both in Docker
make api-types   # after changing the API: regenerate schema/openapi.json and the frontend types
```

| Path | What |
|---|---|
| `backend/` | FastAPI app (Python 3.13): `app/auth` sign-in and sessions, `app/masters` schema normalization, `app/importers` sandboxed PDF/DOCX extraction, fidelity checks and draft conversion, `app/ai` model client, prompts and stages, `app/pipeline` imports, hydration, fact checks, coverage and the job queue, `app/api` routes |
| `frontend/` | React 19 + TypeScript + Tailwind single-page app: `src/editor` the structured master editor (and its Monaco JSON tab), `src/preview` the PDF.js viewer |
| `schema/` | Generated JSON Schema for master résumés, an example, and the OpenAPI document |
| `mockups/` | Static template mockups (Meridian, Atlas, Ledger, Vanguard) |
| `deploy/` | Caddy config for the `https` profile |

Your master résumé is JSON; point your editor at the schema for autocomplete by adding
`"$schema": "http://localhost:8080/schema/master-resume.schema.json"` to the file. The example is in
[`schema/examples/master-resume.example.json`](schema/examples/master-resume.example.json).
