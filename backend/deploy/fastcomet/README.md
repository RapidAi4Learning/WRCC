# Deploying the WRCC backend to FastComet

For subsequent updates via SSH / GitHub Actions, see
[Automated deployment](AUTOMATION.md). The instructions below cover initial setup.

Shared cPanel hosting, PostgreSQL 13, Passenger. A fresh database — no data is
carried over from anywhere.

Two directories here:

| Directory | What it is |
|---|---|
| `probe/` | Pre-flight checks. Already run, already green. Keep it until the real app is live, then delete the `probe` application and its subdomain. |
| `app/` | The real deployment: Passenger entry point, bootstrap script, dependency list. |

---

## What Passenger changes about this app

Two things, and neither is a configuration setting:

**The app is ASGI; Passenger speaks WSGI.** `passenger_wsgi.py` bridges them
with `a2wsgi`, which keeps one event loop alive in a daemon thread for the life
of the process. The database pool lives in that loop, so the bridge is built
once and reused — but **once per process, on that process's first request**,
never at import. FastComet serves the app through LiteSpeed's LSAPI, which
preloads it in a parent and forks children to handle requests, and a fork
carries over memory but not threads. A bridge built at import therefore leaves
every child holding an event loop nobody is driving, and each request waits on
it forever. See "Troubleshooting: every request hangs" at the bottom.

**Passenger stops idle processes.** The catalog sync
(`app/scraper/service.py:101`) dispatches a multi-minute crawl to
`asyncio.create_task` and returns immediately. If the process is stopped while
that crawl is in flight, the `scraper_runs` row is left at `running` — and
`has_open_run()` (`app/scraper/repository.py:234`) then refuses **every future
sync, permanently**, because from the database's point of view one is still
going. There is no timeout and no recovery path.

Nothing else in the app is affected: publishing, generation, media and auth are
all request-scoped and finish before the response does.

See "Known issue: a stalled sync" at the bottom.

---

## 1. Database

cPanel → **PostgreSQL Databases**

1. Create a database, e.g. `wrcc`. cPanel prefixes it: `dasdasda_wrcc`.
2. Create a user, e.g. `wrccapp` → `dasdasda_wrccapp`. Use a fresh password,
   not one reused from Railway.
3. **Add User To Database** → grant **ALL PRIVILEGES**.

Note the full prefixed names. They go into `DATABASE_URL` below.

`localhost` is deliberate: the backend and the database sit on the same server,
so the connection never leaves it and the database needs no public exposure.

---

## 2. Subdomain

cPanel → **Domains** → **Create A New Domain**

- Domain: `api.social-media-marketing.ai4l.com.au`
- Document Root: whatever cPanel fills in — **write it down**, the Python app's
  Application root must be exactly this folder.
- If a "share document root" checkbox appears, leave it **unchecked**.

Then cPanel → **SSL/TLS Status** → tick the subdomain → **Run AutoSSL**.

Do not continue until `https://api.social-media-marketing.ai4l.com.au` serves
over HTTPS without a certificate warning. The session cookie is set `Secure` in
production and a browser will silently drop it over plain HTTP — the symptom is
a login that appears to succeed and then bounces straight back to the login
page.

---

## 3. Python application

cPanel → **Setup Python App** → **Create Application**

| Field | Value |
|---|---|
| Python version | `3.12.14` |
| Application root | the document root folder from step 2 |
| Application URL | the subdomain in the dropdown, **path field empty** |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

---

## 4. Upload

Into the Application root, preserving structure:

```
<app root>/
├── passenger_wsgi.py     from deploy/fastcomet/app/
├── bootstrap.py          from deploy/fastcomet/app/
├── requirements.txt      from deploy/fastcomet/app/
├── alembic.ini           from backend/
├── app/                  the whole package from backend/app/
└── migrations/           the whole directory from backend/migrations/
```

Do **not** upload `tests/`, `.venv/`, `media/`, `deploy/`, `pyproject.toml`, or
any `.env`. `.venv` in particular is a Windows virtualenv and would shadow the
Linux one cPanel builds.

---

## 5. Configuration

Generate the file locally:

```bash
cd backend
python -m scripts.make_env --out .env.production
```

It writes every variable, generates `AUTH_SECRET` and `MEDIA_SIGNING_SECRET`
fresh, and leaves the values only you have marked `FILL_IN`. Fill those in,
then upload it to the application root **renamed to `.env`** — both entry
points chdir to their own directory, so it is found wherever Passenger starts.

A file rather than the cPanel editor because that screen takes one name and one
value per click, and there are twenty-five of them.

Three things to get right:

* **`DATABASE_URL` is a DSN, not a hostname.** Bare `localhost` passes the
  config validator and then fails on the first query, so the app looks broken
  rather than misconfigured. Use the prefixed cPanel names:
  `postgresql+asyncpg://acct_wrccapp:PASSWORD@localhost:5432/acct_wrcc`
* **`DB_POOL_SIZE=3`.** The default is 10, and SQLAlchemy adds an overflow of
  10 on top — up to 20 connections per process, times however many workers
  Passenger starts, against a `max_connections` shared with other accounts.
* **`TOKEN_ENCRYPTION_KEY` is the one secret not to regenerate.** It Fernet-
  encrypts the OAuth tokens in `social_accounts`. On a database that has never
  held one a new key is safe, but reconnecting accounts later against a
  different key than the one that encrypted them is the failure this rule
  exists to prevent.

Rotate the rest. `OPENAI_API_KEY`, `META_APP_SECRET` and
`LINKEDIN_CLIENT_SECRET` have to be rotated **in their own dashboards** —
changing them in the file alone does nothing.

If you also set variables in the cPanel screen, remember `os.environ` wins over
the `.env`. Setting the same key in both is how a stale value silently beats
the one you just corrected.

### Why `SameSite=lax` is enough

The frontend is `wrcc.social-media-marketing.ai4l.com.au`, the API is
`api.social-media-marketing.ai4l.com.au`. Different **origins**, but both under
the registrable domain `ai4l.com.au`, so the browser treats them as the same
**site** and sends a `Lax` cookie on the frontend's `fetch` calls. CORS is
already configured from `FRONTEND_ORIGIN` with credentials allowed
(`app/main.py`). Nothing else is needed.

---

## 6. Install and bootstrap

**Dependencies.** In the app's config screen, `Configuration files` →
`requirements.txt` → **Add** → **Run Pip Install**.

**Schema and admin user.** Same screen, **Execute python script** → enter
`bootstrap.py` → Run.

It applies every Alembic revision and creates the admin. Both steps are
idempotent: running it twice changes nothing. It prints the driver name but
never `DATABASE_URL`, which carries the password.

Then click **Restart**.

---

## 7. Verify

Open the bare hostname in a browser. It answers:

```json
{"service":"WRCC Social Media Marketing API","status":"ok",
 "health":"/api/health/ready","docs":"/docs"}
```

A `404 {"detail":"Not Found"}` here is not a dead deployment — it is the
application answering from a copy of `app/` uploaded before the `/` route was
added. Re-upload `app/main.py`.

Then `/docs` — FastAPI's Swagger UI, already built in — lists every endpoint
and lets you call them. It is the quickest way to see the deployment is really
running the application and not just returning a page.

From a terminal:

```bash
curl https://api.social-media-marketing.ai4l.com.au/api/health
# {"status":"ok","env":"production"}

curl https://api.social-media-marketing.ai4l.com.au/api/health/ready
# {"status":"ready","database":"up"}
```

The second one is the one that matters — it proves the app reached PostgreSQL.
A `503 {"database":"down"}` means `DATABASE_URL` is wrong or the grant is
missing.

If either returns a 500 page reading "WRCC backend failed to start", set
`DEPLOY_DEBUG=1` in the environment variables, Restart, and reload: the entry
point will then print the traceback in the browser instead of an opaque error.
**Remove `DEPLOY_DEBUG` once the app is up** — a traceback names paths,
versions and sometimes configuration, and this endpoint is public.

Then log in through the frontend once, and confirm a post generates.

### A decision about `/docs`

`/docs`, `/redoc` and `/openapi.json` are public and unauthenticated — FastAPI
enables them by default and this app does not turn them off. `/openapi.json` is
42 KB describing every endpoint, parameter and schema in the service.

Nothing is *reachable* through them that is not already protected: every route
but the signed image endpoint requires a session. The exposure is
reconnaissance — a complete map of an application that stores OAuth tokens and
posts to real social accounts.

For an internal tool with one operator that is a defensible thing to leave on,
and it is genuinely useful for checking a deploy. Worth deciding on purpose
rather than by default. Turning them off is one line in `create_app()`:

```python
app = FastAPI(title=..., version=..., docs_url=None, redoc_url=None, openapi_url=None)
```

Gating them behind the existing session instead is a little more work and keeps
them usable.

---

## 8. Point the frontend at it

Vercel → project → **Settings** → **Environment Variables**:

- `NEXT_PUBLIC_API_BASE` = `https://api.social-media-marketing.ai4l.com.au`
- Remove `BACKEND_PROXY_URL` if it is set — it points at Railway, and leaving it
  would keep proxying `/api/*` there.

Redeploy. Nothing in the frontend source needs to change: every URL already
comes from these two variables (`lib/api.ts:34`, `next.config.mjs:2`).

### Update the OAuth dashboards

`PUBLIC_API_BASE_URL` builds the OAuth redirect URIs, and it is changing. The
new value must be registered in both dashboards or connecting an account fails
with a redirect-URI mismatch:

- **Meta** → App → Facebook Login → Valid OAuth Redirect URIs
- **LinkedIn** → App → Auth → Authorized redirect URLs

Add the `api.` versions. Leave the old ones in place until Railway is gone.

---

## 9. Retire Railway

Only after a real post has been published from the new deployment. Keep the
Railway service running but idle in the meantime — with the frontend pointed
elsewhere it costs nothing to leave up, and it is the rollback.

To roll back: set `NEXT_PUBLIC_API_BASE` back to the old value and redeploy.
Nothing else moved, so nothing else has to move back.

---

## Known issue: a stalled sync

Described at the top. If a catalog sync is interrupted, every later sync is
refused with *"A sync is already running or awaiting review."*

**Manual recovery**, via cPanel → phpPgAdmin:

```sql
UPDATE scraper_runs
SET status = 'failed', error = 'interrupted', finished_at = now()
WHERE status = 'running';
```

Two proper fixes, neither done yet:

1. **Treat an old `running` row as failed.** A few lines in `has_open_run()`
   plus a `SCRAPER_RUN_STALE_SECONDS` setting. Self-healing, and it works no
   matter why the crawl died.
2. **Move the crawl to a cPanel cron job.** Cron processes are not subject to
   Passenger's idle stop, so the crawl always runs to completion. Changes how
   the sync is triggered, so it is a product decision as much as a technical
   one.

(1) is the smaller change and fixes the symptom that will actually be hit.

---

## Troubleshooting: every request hangs

**Symptom.** Every URL — `/api/health`, a path that does not exist, anything —
accepts the TCP connection instantly, serves TLS correctly, and then returns
nothing. After about two minutes LiteSpeed answers with its own page:

```html
<h2>Request Timeout</h2>
This request takes too long to process, it is timed out by the server.
```

`stderr.log` shows no application error at all, only lines like
`Killing runaway process PID: N with SIGTERM` and `Child process with pid: N
was killed by signal: 15`. Nothing wrote `startup_error.log`, and
`app/__pycache__/*.pyc` carry a fresh timestamp — so the app imported fine.

**Cause.** The ASGI-to-WSGI bridge was built at import, in the LSAPI parent
that preloads the app, and the event-loop thread it started did not survive the
fork into the worker children. Every request was queued onto a loop nobody was
running. This is the hardest class of bug to read from the outside: the app is
healthy, the config is right, and the failure is silence.

**Fix.** Already in `app/passenger_wsgi.py`: the bridge is created lazily, per
process, and rebuilt whenever the pid changes.

**Telling this apart from a hosting problem next time.** The entry point
answers `/__wsgi_ping` in pure WSGI, without touching the bridge:

```bash
curl -m 20 https://api.<domain>/__wsgi_ping     # instant "pong"
curl -m 20 https://api.<domain>/api/health      # the real app
```

`pong` fast plus a hanging `/api/health` means the request reached Python and
the async plumbing is at fault. Both hanging means the problem is in front of
Python — LiteSpeed, LSAPI, the virtualenv path in `.htaccess`, or the app not
starting at all. One request instead of an afternoon.
