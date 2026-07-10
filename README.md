# WRCC Content Studio

Social content generation + course catalog studio for
[Western Riverina Community College](https://wrcc.nsw.edu.au/).

- **Generate** — 3 post ideas per request for **Facebook, Instagram and
  LinkedIn**, with tone/format adapted per platform. Ground each request in a
  **real course from the scraped catalog** (name, code, price, upcoming dates,
  locations) or in a free `topic` + optional `reference_url` + `notes`.
- **History** — every generated variant is persisted with an approval workflow
  (`draft → pending_approval → approved/rejected`, plus edit / archive /
  restore / duplicate / regenerate), all audited.
- **Catalog** — a polite scraper crawls the WRCC site (aXcelerate-rendered
  courses + scheduled offerings) and stages a diff; **nothing touches the live
  catalog until a human approves the changeset**.
- **Login** — seeded admin user, argon2 + JWT in an httpOnly cookie.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2 async + asyncpg, Alembic |
| DB | PostgreSQL (aiosqlite in unit tests) |
| LLM | `google-genai` (Gemini) behind an `LLMClient` protocol with a deterministic mock (`LLM_MOCK=true` by default) |
| Scraper | httpx (politeness delay + bounded retries) + BeautifulSoup |
| Frontend | Next.js 14, React 18, TypeScript, CSS modules |
| Tests | pytest + pytest-asyncio (103 tests, HTML fixtures); vitest + Playwright |

## Getting started

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate         # Windows · source .venv/bin/activate on Unix
pip install -e ".[dev]"

cp .env.example .env           # set DATABASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD
alembic upgrade head           # creates users/audit_logs/catalog/content tables
python -m app.db.seed          # creates the admin user (fails if env missing)
uvicorn app.main:app --reload  # http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                    # http://localhost:3000 → redirects to /login
```

Point the frontend at a non-default API host with
`NEXT_PUBLIC_API_BASE=http://localhost:8000`.

### Commands

| Where | Command | What |
|---|---|---|
| backend | `pytest` | full suite (no network, no Postgres needed) |
| backend | `pytest --cov=app` | coverage (currently ~89%) |
| backend | `ruff check app tests` · `mypy app` | lint / types |
| frontend | `npm run test` | vitest component tests |
| frontend | `npm run test:e2e` | Playwright smoke (starts its own dev server) |
| frontend | `npm run typecheck` · `npm run build` | types / production build |

## Environment contract

See [`backend/.env.example`](backend/.env.example). Highlights:

- **Mock-first (D3)**: the app boots with zero credentials. `LLM_MOCK=false`
  requires `GEMINI_API_KEY` (validated at startup, fail-fast).
- **No hardcoded secrets**: the admin seed reads `ADMIN_EMAIL` /
  `ADMIN_PASSWORD` and refuses to run without them; production rejects the
  `AUTH_SECRET` placeholder.

## Architecture notes

```
backend/app/
├── auth/        argon2 + JWT cookie, login rate limit, get_current_user
├── scraper/     discovery → parser → normalize → diff (pure) → repository
│                └ service.py: background crawl, run lifecycle
├── services/    courses.py — HITL review (approve applies the changeset)
├── agents/      content_generator (PLATFORM_PROFILES, 3 variant styles),
│                validation (deterministic ranking baseline)
├── llm/         LLMClient protocol · MockLLMClient · GeminiLLMClient
├── content/     schemas · state machine · repository · services (generate + workflow)
└── api/         routers: content, courses (+ sync), auth, health
```

- **Sync HITL**: `POST /api/courses/sync` opens a `scraper_runs` row and crawls
  in the background; the diff is staged as a JSON changeset (`pending`). Only
  `POST /api/courses/sync/{id}/approve` writes the live catalog; `removed`
  always means *deactivate*, never delete. A crawl that yields zero offerings
  fails the run rather than staging a mass-deactivation.
- **Generation**: 3 variant styles per platform (`direct`, `story_led`,
  `question_led`), ranked by rule-baseline violations (length/hashtags/CTA per
  platform profile). Reference URLs are fetched best-effort — failures become
  warnings, never errors.
- **Auditing**: every mutation (generation, workflow transition, sync review)
  writes an `audit_logs` row with the acting user.

## Deliberately out of scope

Publishing to the networks (Meta/LinkedIn APIs), scheduling, analytics,
campaigns, editable brand-voice profiles, media, user management beyond the
seeded login. See `docs/PLAN.md` for the full plan and decisions D1–D4.
