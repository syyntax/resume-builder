# Resume Tailor

A self-hosted, multi-user web app that tailors a master résumé and writes a cover letter for each job
posting with Claude, then exports polished PDF, DOCX, Markdown or JSON. See [DESIGN.md](DESIGN.md) for
the full design and [mockups/](mockups/index.html) for the approved templates.

**Status:** all seven milestones are built (the first live eval run is still to come; see Develop). Add your Anthropic
API key under **Account → AI**, import your existing PDF or Word résumé (or upload JSON), review and edit it,
then paste a job posting under **Applications** to get a tailored, fact-checked résumé and cover letter. Edit both
side by side with a live PDF preview: rewrite or reorder lines, ask the AI for suggestions, see where every line
came from, and let a second AI pass flag claims that overstate their sources. Choose from four templates (Meridian,
Atlas, Ledger, Vanguard), fit the résumé to its page target in one click, and download each document as PDF, Word,
plain text, Markdown or JSON, or both as one application packet. Accounts can use two-step verification, the app can
send email (password resets, invites, address confirmation), and an imported résumé can be merged into a master you
already have.

## Run it

You only need Docker.

```bash
cp .env.example .env              # then set APP_SECRET_KEY (openssl rand -base64 32)
docker compose up -d --build
docker compose logs app | grep "Setup token"
```

Open http://localhost:8080/setup, paste the setup token and create the admin account. After that, other
people can register (open registration is the default; switch to invite-only under **Admin → Settings**).
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
| Email | Set `SMTP_HOST` and `SMTP_FROM` (and `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_PORT`, `SMTP_SECURITY` as your provider needs). People can then reset their own password, invites are emailed, and open sign-ups confirm their address. Without it, admins share reset and invite links themselves. |
| Two-step verification | Anyone can turn it on under **Account**. To require it for admins or everyone, use **Admin → Settings** (or `REQUIRE_MFA` for the initial value). |

## Admin tasks

```bash
docker compose exec app resume-tailor admin list
docker compose exec app resume-tailor admin create --email you@example.com --name "Your Name"
docker compose exec app resume-tailor admin reset-password --email you@example.com
docker compose exec app resume-tailor setup-token   # new setup token, before the first account exists
docker compose exec app resume-tailor keys rotate    # after changing APP_SECRET_KEY (set APP_SECRET_KEY_PREVIOUS)
docker compose exec app resume-tailor backup         # database and uploads, to /data/backups/*.tar.gz
docker compose cp app:/data/backups/<file> .         # copy a backup off the volume
```

Restore with the app stopped: `docker compose stop app`, then
`docker compose run --rm app resume-tailor restore /data/backups/<file> --yes`, then `docker compose start app`.
A backup holds API keys and two-step secrets only in encrypted form: keep `APP_SECRET_KEY` safe, and separate.

## Develop

```bash
make dev     # hot-reloading backend on :8080 and Vite dev server on http://localhost:5173
make test    # backend (pytest) and frontend (tsc + vitest), both in Docker
make api-types   # after changing the API: regenerate schema/openapi.json and the frontend types
make thumbnails  # after changing a template: regenerate the gallery thumbnails
make evals       # the eval harness against the offline model (checks the harness, not the AI)
```

The evals (DESIGN.md §17) run 10 job postings against three master résumés, and import 5 résumé files, through
the whole app, then grade the results: fact-check errors and warnings, keyword coverage against a baseline,
page targets, import fidelity, and an AI judge's scores for relevance and letter quality. A live run uses the
Claude API with its own key variable, so a key in your shell is never spent by accident, and costs roughly $1 per
case:

```bash
EVAL_ANTHROPIC_API_KEY=sk-ant-... make evals ARGS="--live"                    # report in eval-results/
EVAL_ANTHROPIC_API_KEY=sk-ant-... make evals ARGS="--live --update-baseline"  # accept this run's coverage
```

CI (`.github/workflows/ci.yml`) runs the tests, ruff, bandit, pip-audit, pnpm audit, a Trivy image scan, an
OWASP ZAP baseline scan, and an axe-core accessibility audit of every page.

| Path | What |
|---|---|
| `backend/` | FastAPI app (Python 3.13): `app/auth` sign-in and sessions, `app/masters` schema normalization, `app/importers` sandboxed PDF/DOCX extraction, fidelity checks and draft conversion, `app/ai` model client, prompts and stages, `app/pipeline` imports, hydration, fact checks, coverage and the job queue, `app/render` templates, bundled fonts and the Chromium PDF renderer, `app/api` routes |
| `frontend/` | React 19 + TypeScript + Tailwind single-page app: `src/editor` the structured master editor (and its Monaco JSON tab), `src/preview` the PDF.js viewer |
| `schema/` | Generated JSON Schema for master résumés, an example, and the OpenAPI document |
| `mockups/` | Static template mockups (Meridian, Atlas, Ledger, Vanguard) |
| `deploy/` | Caddy config for the `https` profile |

Your master résumé is JSON; point your editor at the schema for autocomplete by adding
`"$schema": "http://localhost:8080/schema/master-resume.schema.json"` to the file. The example is in
[`schema/examples/master-resume.example.json`](schema/examples/master-resume.example.json).
