# WRCC Social Media Marketing

Social content generation + course catalog studio for
[Western Riverina Community College](https://wrcc.nsw.edu.au/).

- **Generate** — 3 post ideas per request for **Facebook, Instagram and
  LinkedIn**, with tone/format adapted per platform. Ground each request in a
  **real course from the scraped catalog** (name, code, price, upcoming dates,
  locations) or in a free `topic` + optional `reference_url` + `notes`.
- **History** — every generated variant is persisted with an approval workflow
  (`draft → pending_approval → approved/rejected`, plus edit / archive /
  restore / duplicate / regenerate), all audited.
- **Publish** — send an approved post to the Facebook Page, Instagram Business
  account or LinkedIn Company Page it was written for, from inside the app.
  Accounts are connected once via OAuth; tokens are encrypted at rest.
- **Catalog** — a polite scraper crawls the WRCC site (aXcelerate-rendered
  courses + scheduled offerings) and stages a diff; **nothing touches the live
  catalog until a human approves the changeset**.
- **Login** — seeded admin user, argon2 + JWT in an httpOnly cookie.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2 async + asyncpg, Alembic |
| DB | PostgreSQL (aiosqlite in unit tests) |
| LLM | `google-genai` (Gemini) or `openai` (GPT) behind an `LLMClient` protocol with a deterministic mock (`LLM_MOCK=true` by default; provider via `LLM_PROVIDER`) |
| Scraper | httpx (politeness delay + bounded retries) + BeautifulSoup |
| Frontend | Next.js 14, React 18, TypeScript, CSS modules |
| Tests | pytest + pytest-asyncio (416 tests, HTML fixtures, `httpx.MockTransport` for wire contracts); vitest (66) + Playwright |

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
| backend | `pytest --cov=app` | coverage (currently ~93%) |
| backend | `ruff check app tests` · `mypy app` | lint / types |
| frontend | `npm run test` | vitest component tests |
| frontend | `npm run test:e2e` | Playwright smoke (starts its own dev server) |
| frontend | `npm run typecheck` · `npm run build` | types / production build |

## Environment contract

See [`backend/.env.example`](backend/.env.example). Highlights:

- **Mock-first (D3)**: the app boots with zero credentials. `LLM_MOCK=false`
  requires the API key of the selected `LLM_PROVIDER` — `GEMINI_API_KEY` for
  `gemini` (default) or `OPENAI_API_KEY` for `openai` (validated at startup,
  fail-fast).
- **No hardcoded secrets**: the admin seed reads `ADMIN_EMAIL` /
  `ADMIN_PASSWORD` and refuses to run without them; production rejects the
  `AUTH_SECRET` placeholder.
- **Publishing (D8)** follows the same contract: `PUBLISH_MOCK=false` requires
  the public origin, both signing/encryption secrets and every network
  credential — see *Going live* below.

## Architecture notes

```
backend/app/
├── auth/        argon2 + JWT cookie, login rate limit, get_current_user
├── scraper/     discovery → parser → normalize → diff (pure) → repository
│                └ service.py: background crawl, run lifecycle
├── services/    courses.py — HITL review (approve applies the changeset)
├── agents/      content_generator (PLATFORM_PROFILES, 3 variant styles),
│                validation (deterministic ranking baseline)
├── llm/         LLMClient protocol · MockLLMClient · GeminiLLMClient · OpenAILLMClient
├── content/     schemas · state machine · repository · services (generate + workflow)
├── publishing/  crypto (Fernet) · media (JPEG + signed URLs) · rules (preflight)
│                · service (the one irreversible path) · accounts
│                ├ oauth/       meta · linkedin · mock, behind get_oauth_provider
│                └ publishers/  facebook · instagram · linkedin · mock + retry
└── api/         routers: content, courses (+ sync), auth, health, publishing,
                 public_media
```

- **Sync HITL**: `POST /api/courses/sync` opens a `scraper_runs` row and crawls
  in the background; the diff is staged as a JSON changeset (`pending`). Only
  `POST /api/courses/sync/{id}/approve` writes the live catalog; `removed`
  always means *deactivate*, never delete. A crawl that yields zero offerings
  fails the run rather than staging a mass-deactivation.
- **Partial approval**: approve takes an optional `skip` body naming entry codes
  per changeset section (`{"skip": {"courses_added": ["WHS101"]}}`), so a
  reviewer can apply part of a changeset and pass over the rest. Only codes are
  sent — the rows applied are always the ones the server staged. A skipped entry
  leaves its live row untouched, so the next crawl stages it again. The run keeps
  the full changeset; the audit row records what was applied and what was
  skipped.
- **Generation**: 3 variant styles per platform (`direct`, `story_led`,
  `question_led`), ranked by rule-baseline violations (length/hashtags/CTA per
  platform profile). Reference URLs are fetched best-effort — failures become
  warnings, never errors.
- **Auditing**: every mutation (generation, workflow transition, sync review)
  writes an `audit_logs` row with the acting user.
- **`shared/`**: fixtures both test suites read, for logic that exists once per
  language and must not drift. Today that is `post-text-cases.json`, the
  contract between `compose_post_text` (what gets posted) and `composePostText`
  (what the Copy button produces). Asserting hardcoded strings on each side
  would let one change while both suites stayed green.

## Publishing

An **approved** post can be sent to the network it was written for. Connect an
account under **Settings → Connections**, then hit **Publish** on the card. See
[`docs/PUBLISH-PLAN.md`](docs/PUBLISH-PLAN.md) for the full design and
decisions D5–D8.

- **Facebook** — Page feed, with or without a photo. Image bytes are uploaded
  directly, so Facebook publishing does not need a public host.
- **Instagram** — the container → poll → publish two-step. Always needs an
  image, and the image must be reachable by Meta, which is what the signed
  public URL below is for.
- **LinkedIn** — Company Page via the versioned REST API (three-leg image
  upload); posting as a member is the fallback if the Community Management API
  is not approved.

Publish is the only action in this app whose effect is on someone else's
server, so it is guarded at four levels rather than one: only `approved` items
qualify; the server's own preflight must pass; the dialog asks for a second,
explicit confirmation; and a partial unique index makes a second *successful*
publication of the same item impossible at the database level. The `pending`
attempt row is committed **before** the network call, so "we may have posted
and lost the response" stays distinguishable from "we never tried".

A published item keeps only **Archive** and **Duplicate**. It cannot be edited
or regenerated here — our copy must not drift from what is live.

`PUBLISH_MOCK=true` (the default) keeps the app bootable with zero credentials,
exactly like `LLM_MOCK`, and the whole flow is exercisable offline: connect
from Settings, approve a post in History, publish it from the card.

### Going live

Setting `PUBLISH_MOCK=false` requires `PUBLIC_API_BASE_URL`,
`TOKEN_ENCRYPTION_KEY`, `MEDIA_SIGNING_SECRET` and the credential pair for each
network — validated at startup, fail-fast. Outside the app you also need:

1. A Meta app left in **Development mode** (no App Review), with whoever
   authorises it holding a role on the app.
2. The Instagram account converted to **Business** and linked to the Facebook
   Page.
3. LinkedIn's **Community Management API** approved, for Company Page posting.
4. A public HTTPS origin for the backend — Instagram fetches the image
   server-side. `ngrok http 8000` is enough to test against the real networks.

Confirm `META_GRAPH_VERSION` and `LINKEDIN_API_VERSION` against the live
changelogs before going live; both providers ship breaking versions on a
schedule, which is why they are env vars.

### The one unauthenticated endpoint

`GET /api/public/images/{id}.jpg` serves an image to Meta without a session,
because Instagram will not send a cookie. It is guarded by an HMAC signature
over the id and expiry, compared in constant time, with a ~15-minute TTL, and
every failure answers **404 rather than 403** so it cannot be used to test
whether an id exists. `MEDIA_SIGNING_SECRET` must differ from `AUTH_SECRET` —
enforced at startup — so a leaked image key cannot forge a session.

## Deliberately out of scope

Scheduling, analytics, campaigns, editable brand-voice profiles, user
management beyond the seeded login. See `docs/PLAN.md` for the full plan and
decisions D1–D4.
