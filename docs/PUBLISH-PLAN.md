# Publish to Facebook / Instagram / LinkedIn — implementation plan

Extends [`docs/PLAN.md`](PLAN.md). Publishing was listed there as *deliberately
out of scope*; this document brings it in and records the decisions **D5–D8**
that shape it.

---

## 1. Scope

Turn an **approved** `content_item` into a live post on the network it was
written for, from a button in the UI, and keep an auditable record of every
attempt.

**In scope**

- Connect the WRCC Facebook Page, its linked Instagram Business account, and
  the WRCC LinkedIn Company Page through an in-app OAuth flow.
- Publish one approved item (text + optionally an image) to its platform, on
  demand. *Several* images — a Facebook multi-photo story, an Instagram
  carousel, a LinkedIn multi-image post — arrived later with D12.
- Per-attempt history: what was sent, the remote post id, the permalink, or the
  error — surfaced in the UI, written to `audit_logs`.
- Preflight validation so a post is rejected by us, with a readable reason,
  before it is rejected by the network.

**Out of scope for this phase** (deliberate, listed so it is not accidental)

- Scheduling / a "publish at 9am Tuesday" queue — see §12 for what to leave
  open so it drops in later.
- ~~Carousels~~ — brought in by [`docs/MEDIA-PLAN.md`](MEDIA-PLAN.md) (D12).
  Stories, reels, video and link-preview customisation remain out.
- Analytics, comment ingestion, reply management.
- Deleting or editing a post after it has gone out.

### Decisions

| | Decision | Rationale |
|---|---|---|
| **D5** | **In-app OAuth connect flow**, tokens encrypted in the DB | LinkedIn tokens die every 60 days. A `.env` token means a silent breakage and a manual Graph Explorer session every two months, with no UI signal. A Settings page that shows expiry and reconnects in one click is ~2 days more work and removes a recurring chore. |
| **D6** | **LinkedIn posts as the WRCC Company Page** (`urn:li:organization:…`) | Requested. Note this is the one external gate that keeping the Meta app private does *not* avoid — see §2.3. The author URN stays config, so member posting (`urn:li:person:…`, self-serve) is a one-line fallback if approval stalls. |
| **D7** | **Backend is publicly reachable over HTTPS** | Required. Instagram's Content Publishing API cannot accept image bytes at all — it only fetches a public `image_url`. We therefore add a **signed, short-TTL public image endpoint** (§6.2). Facebook's `/photos` uses the same URL, so one mechanism serves both. |
| **D8** | **Publish-now only**, mock-first like `LLM_MOCK` | Smallest correct surface. `PUBLISH_MOCK=true` is the default so the app keeps its "boots with zero credentials" property (D3) and the whole publish path is testable offline. |

---

## 2. External prerequisites (do these first — they gate Phase 4)

These are account/portal tasks, not code. Phases 1–3 can be built in parallel
with them.

### 2.1 Meta app (Facebook + Instagram)

1. Create an app at developers.facebook.com, type **Business**.
2. Add the **Facebook Login for Business** and **Instagram** products.
3. Leave the app in **Development mode**. No App Review needed — but this means
   *only users with a role on the app* can authorise it. Add the WRCC admin as
   an **Administrator** of the app, and make sure that same person is an admin
   of the WRCC Facebook Page.
4. Permissions to request: `pages_show_list`, `pages_read_engagement`,
   `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`,
   plus `business_management` if the Page lives in a Business portfolio.
5. Convert the WRCC Instagram account to **Business** (not Creator) and link it
   to the Facebook Page. Instagram publishing is impossible without this link.
6. Register the OAuth redirect URI: `https://<api-host>/api/social/meta/callback`.

**Reality check on Development mode:** publishing works, and posts are real and
public. The restriction is on *who may authorise the app*, not on what the app
may then do. Since exactly one person connects the accounts, this is fine
indefinitely.

### 2.2 Image prerequisites

Instagram will only accept **JPEG**. Our `content_images.data` holds PNG bytes.
Conversion is mandatory, not cosmetic — see §6.1.

### 2.3 LinkedIn app — the one real gate

1. Create an app at linkedin.com/developers, associated with the WRCC Company
   Page. A Page admin must **verify** the app (a link they click).
2. Add the **Community Management API** product. This requires a LinkedIn-side
   access request. It is normally granted for an app managing *its own* Page,
   but it is an approval with a wait, and it is independent of Meta's App
   Review — keeping the Meta app private does not exempt LinkedIn.
3. Scopes: `w_organization_social`, `r_organization_social`,
   `rw_organization_admin`.
4. Register the redirect URI: `https://<api-host>/api/social/linkedin/callback`.

**If approval stalls**, add the self-serve **Share on LinkedIn** product
(`w_member_social`) and set `LINKEDIN_AUTHOR_URN` to a person URN. The
publisher code is identical; only the author URN and scope change. Build for
organization, keep member as the escape hatch.

---

## 3. Reuse: port from `mcc-growth-agent`, don't rewrite

`C:\Projects\mcc-growth-agent` already runs a production Meta Graph layer. Port
it rather than reinventing — the error taxonomy and the IG two-step in
particular encode real operational learning.

| Source file | Port to | Change on the way in |
|---|---|---|
| `connect/meta/errors.py` | `app/publishing/meta/errors.py` | Take as-is. The `_AUTH_CODES` / `_RATE_LIMIT_CODES` / `_TRANSIENT_CODES` sets are the valuable part. |
| `connect/meta/transport.py` | `app/publishing/meta/transport.py` | **Rewrite the transport on `httpx.AsyncClient`.** The reference uses stdlib `urllib` in a thread executor; wrcc already depends on httpx and uses it async everywhere (`scraper/fetcher.py`, `content/service.py`). Keep the `GraphTransport` Protocol seam and `redact_access_token_from_url` verbatim. |
| `connect/meta/live.py` (lines ~198–309) | `app/publishing/publishers/facebook.py`, `instagram.py` | Drop the carousel/story/video branches (out of scope). Keep `_with_retry`'s bounded exponential backoff and the `_await_container_ready` poll. |
| `connect/meta/client.py` + `mock.py` | `app/publishing/publishers/base.py` + `mock.py` | Collapse to one `Publisher` Protocol covering all three networks (§5.1). |
| `integrations/crypto.py`, `oauth.py` | `app/publishing/crypto.py`, `oauth/base.py` | Keep `TokenCipher` and the `TokenExchanger` Protocol + `TokenResponse` dataclass. Drop the Google specifics. |
| `integrations/meta_oauth.py` | `app/publishing/oauth/meta.py` | Keep the `config_id`-vs-`scope` branch — business-type apps reject bare scopes with "Invalid Scopes", which is a genuinely non-obvious trap. |

**No LinkedIn code exists in the reference project.** `app/publishing/oauth/linkedin.py`
and `publishers/linkedin.py` are net-new (§5.4).

---

## 4. Data model

### 4.1 New enums (`app/db/enums.py`)

```python
class ContentStatus(enum.StrEnum):
    ...
    published = "published"          # NEW — terminal-ish, set on a successful publish


class PublishStatus(enum.StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
```

### 4.2 State machine (`app/content/state.py`)

```
approved  → published     (NEW)
published → archived      (NEW)
```

`draft`/`pending_approval`/`rejected` gain no path to `published` — publishing
is only ever possible from `approved`. A failed attempt leaves the item in
`approved` so it stays retryable.

### 4.3 `social_accounts`

One row per connected destination. Tokens are encrypted at rest and never
leave the backend.

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `platform` | `ContentPlatform` | fb / ig / li |
| `external_id` | Text | Page id, IG user id, or organization id |
| `display_name` | Text | "Western Riverina Community College" |
| `handle` | Text \| None | `@wrcc` for IG, vanity name for LI |
| `access_token_encrypted` | Text | Fernet ciphertext. **Never** in a response model |
| `refresh_token_encrypted` | Text \| None | LinkedIn only; Meta has no refresh token |
| `token_expires_at` | DateTime(tz) \| None | Drives the "reconnect soon" banner |
| `scopes` | PortableJSON | Granted scopes, for diagnosing 403s |
| `metadata_` | PortableJSON | e.g. IG's parent `page_id`, LI's org URN |
| `is_active` | Boolean | The account used for this platform |
| `connected_by` / `connected_at` | FK users / DateTime | |
| `created_at` / `updated_at` | | |

Unique on `(platform, external_id)`. Partial unique on `(platform)` where
`is_active` — one active destination per network.

### 4.4 `content_publications`

One row per **attempt**, so retries and failures are inspectable.

| Column | Type | Notes |
|---|---|---|
| `id` | Uuid PK | |
| `content_item_id` | FK → content_items, CASCADE | |
| `social_account_id` | FK → social_accounts, SET NULL | survives a disconnect |
| `content_image_id` | FK → content_images, SET NULL | which image went out |
| `status` | `PublishStatus` | |
| `external_post_id` | Text \| None | `{page}_{post}`, IG media id, or LI post URN |
| `permalink` | Text \| None | |
| `request_summary` | PortableJSON | char counts, image present, target — **never** the token |
| `error` / `error_code` | Text \| None | mapped from the typed platform errors |
| `attempted_by` | FK users SET NULL | |
| `created_at` / `completed_at` | | |

Indexes: `(content_item_id, created_at)`, plus a **partial unique index on
`content_item_id` where `status = 'succeeded'`** — the database, not just
application logic, prevents publishing the same item twice.

### 4.5 Migration `0006_publishing.py`

Two `create_table` calls, plus the enum extension. `contentstatus` is a
**native Postgres enum** (see `0003_content_items.py`), so adding a member is
not a no-op:

```python
with op.get_context().autocommit_block():
    op.execute("ALTER TYPE contentstatus ADD VALUE IF NOT EXISTS 'published'")
```

The `autocommit_block` avoids the "cannot be executed inside a transaction
block" failure on older Postgres and the "unsafe use of new value" error when
the value is referenced in the same transaction. SQLite (tests) builds from
`Base.metadata.create_all` and is unaffected.

No `oauth_states` table: state is a **signed, 10-minute JWT** carrying
`{user_id, platform, nonce}`, verified on callback. One less table, and it
cannot be replayed after expiry.

---

## 5. Backend architecture

```
backend/app/publishing/
├── __init__.py
├── crypto.py            # Fernet TokenCipher, keyed by TOKEN_ENCRYPTION_KEY
├── state.py             # signed OAuth state: sign() / verify()
├── schemas.py           # Pydantic in/out — token fields structurally absent
├── accounts.py          # SocialAccountService: connect, list, activate, disconnect, verify
├── rules.py             # PURE preflight rules per platform (§5.5)
├── media.py             # PNG→JPEG, dimension/size checks, signed public URL builder
├── service.py           # PublishService: the orchestration in §5.6
├── oauth/
│   ├── base.py          # TokenExchanger Protocol, TokenResponse
│   ├── meta.py          # authorize URL, code→long-lived user token→Page token, IG discovery
│   └── linkedin.py      # authorize URL, code→token, refresh, organization discovery
└── publishers/
    ├── base.py          # Publisher Protocol, PublishRequest, PublishResult, PublishError
    ├── mock.py          # PUBLISH_MOCK=true — deterministic, zero network
    ├── facebook.py
    ├── instagram.py
    └── linkedin.py

backend/app/api/publishing.py   # /api/social/*  +  /api/content/{id}/publish
backend/app/api/public_media.py # unauthenticated signed image endpoint
```

Every module stays under ~250 lines; `live.py` in the reference project is 727
lines and is the thing *not* to copy.

### 5.1 The `Publisher` seam

```python
@dataclass(frozen=True, slots=True)
class PublishRequest:
    text: str
    image_url: str | None      # signed public URL; required for Instagram
    image_alt: str | None
    account: ResolvedAccount   # external_id + decrypted token + metadata

@dataclass(frozen=True, slots=True)
class PublishResult:
    external_post_id: str
    permalink: str | None

class Publisher(Protocol):
    async def publish(self, request: PublishRequest) -> PublishResult: ...
```

`get_publisher(platform, settings)` returns `MockPublisher` when
`settings.publish_mock` is true. This mirrors `get_llm_client` /
`get_image_client` exactly, so the existing test fixtures and the "no
credentials to boot" invariant carry over unchanged.

### 5.2 Facebook

Long-lived Page token, form-encoded POST to `https://graph.facebook.com/{version}`.

- **Text only** — `POST /{page_id}/feed` with `message` (+ `link` when the item
  has a `reference_url`). Response `{"id": "{page}_{post}"}`.
- **With image** — `POST /{page_id}/photos` with `caption` and the image as a
  **multipart `source` upload**. Response carries `post_id` (the story, which
  is what a permalink must point at); fall back to `id`.
- Permalink: `https://www.facebook.com/{post_id}`.

> **Implemented differently to this plan, deliberately.** The plan and the
> reference project both pointed Graph at a `url`. Uploading bytes instead
> removes the requirement that this backend be publicly reachable, so Facebook
> publishing works from a laptop and the signed public image endpoint is left
> as Instagram's problem alone — Instagram has no bytes option.

Errors go through the ported `raise_for_graph_error`. Code `190` →
`PublishError(code="reauth")`, which the UI renders as "Reconnect the Facebook
Page" rather than a raw Graph string.

### 5.3 Instagram — two steps, and it is fussy

```
POST /{ig_user_id}/media          image_url=<public https JPEG>&caption=<text>  → {id: creation_id}
GET  /{creation_id}?fields=status_code   poll until FINISHED (backoff, ~60s cap)
POST /{ig_user_id}/media_publish  creation_id=<id>                              → {id: media_id}
GET  /{media_id}?fields=permalink
```

Hard constraints, all enforced in `rules.py` *before* we call out:

- **JPEG only.** PNG is rejected. Conversion is not optional.
- An image is **required** — there is no text-only Instagram feed post.
- Aspect ratio 4:5 → 1.91:1; width 320–1440px. Our 1024×1024 images sit
  comfortably inside this, but validate rather than assume.
- ≤ 8 MB, caption ≤ 2200 chars, ≤ 30 hashtags.
- **25 published posts per rolling 24h.** Check
  `GET /{ig_user_id}/content_publishing_limit` in preflight and surface the
  remaining quota.

The IG user id is discovered once at connect time via
`GET /{page_id}?fields=instagram_business_account` and stored on the
`social_accounts` row.

### 5.4 LinkedIn — net-new

Versioned REST API. Every request carries:

```
Authorization: Bearer <token>
LinkedIn-Version: <LINKEDIN_API_VERSION>     # YYYYMM, e.g. 202506
X-Restli-Protocol-Version: 2.0.0
```

**Image upload** (three legs):

```
POST https://api.linkedin.com/rest/images?action=initializeUpload
     {"initializeUploadRequest": {"owner": "urn:li:organization:{id}"}}
  → {"value": {"uploadUrl": "...", "image": "urn:li:image:..."}}
PUT  <uploadUrl>   raw bytes, Authorization header
```

**Create the post** — `POST https://api.linkedin.com/rest/posts`:

```json
{
  "author": "urn:li:organization:123",
  "commentary": "escaped post text",
  "visibility": "PUBLIC",
  "distribution": {
    "feedDistribution": "MAIN_FEED",
    "targetEntities": [],
    "thirdPartyDistributionChannels": []
  },
  "content": {"media": {"id": "urn:li:image:...", "altText": "..."}},
  "lifecycleState": "PUBLISHED",
  "isReshareDisabledByAuthor": false
}
```

The post URN comes back in the **`x-restli-id` response header**, not the body.
Permalink: `https://www.linkedin.com/feed/update/{urn}`.

**Commentary escaping is mandatory and easy to miss.** The `commentary` field
uses LinkedIn's "little text" format: the characters
`\ | { } @ [ ] ( ) < > # * _ ~` must each be backslash-escaped or the request is
rejected. Our generated posts routinely contain `(`, `)` and `#`. This is a
pure function with its own unit test — `escape_commentary()` in
`publishers/linkedin.py`.

Token lifecycle: access token 60 days, refresh token 365 days (refresh is
enabled alongside Community Management API).

**Not built — reconnect is manual.** The plan originally had
`SocialAccountService.resolve()` refresh transparently inside 5 days of expiry.
It does not: `resolve()` only decrypts, and nothing calls LinkedIn's
`grant_type=refresh_token`. The `refresh_token` column is populated and unused.

Descoped deliberately rather than left as a silent gap. LinkedIn only issues
refresh tokens to apps approved for it, so until this app is through that
approval the refresh code would be unreachable — and unreachable code that
looks like a safety net is worse than none. What covers it instead: Settings
shows the expiry date, turns amber inside 7 days, red once expired, and
**Check connection** pings the token on demand. The cost is a manual reconnect
roughly every 60 days, which the operator is warned about a week ahead.

Revisit when Community Management API approval lands (§2) — at that point the
refresh path becomes testable, and this should be built.

### 5.5 Preflight rules (`rules.py`, pure)

One dependency-free function per platform, returning `(blockers, warnings)`:

| Rule | FB | IG | LI |
|---|---|---|---|
| Item status is `approved` | ✔ | ✔ | ✔ |
| A connected, active account exists | ✔ | ✔ | ✔ |
| Token not expired | ✔ | ✔ | ✔ |
| No successful publication already | ✔ | ✔ | ✔ |
| Image required | — | **blocker** | — |
| Text length | 63,206 | 2,200 | 3,000 |
| Hashtag count | warn > 10 | **blocker** > 30 | warn > 5 |
| Image is convertible to JPEG within spec | — | ✔ | — |
| Daily quota remaining | — | ✔ | — |

Pure functions with no I/O, so they are cheap to test exhaustively and are the
single source of truth — the frontend calls the preflight endpoint rather than
reimplementing them (§7).

### 5.6 `PublishService.publish()`

```
1. load item; 409 unless status == approved
2. 409 if a succeeded publication already exists → return its permalink in the detail
3. resolve the active social_account for item.platform (404 if unconnected)
   → decrypt token, refresh if near expiry
4. resolve the image: explicit image_id, else the most recent for the item
   → 422 if Instagram and no image
5. run preflight; 422 with the blocker list if not clear
6. INSERT content_publications(status=pending) and COMMIT
      ── a crash between here and step 8 leaves evidence, not silence
7. build the signed public image URL (TTL 15 min), call the publisher
8. success → row: succeeded + external_post_id + permalink + completed_at
             item.status = published   (via assert_transition)
   failure → row: failed + error + error_code; item stays approved
9. audit row either way (action "content_published" / "content_publish_failed")
10. COMMIT; return the publication
```

Step 6's separate commit is deliberate. Everything else in this codebase
commits once at the end, but a publish has an irreversible side effect on
someone else's server — a `pending` row that never completed is the only way to
detect "we may have posted and lost the response". A `pending` row older than
5 minutes is displayed as *unknown — check the Page*, and blocks a silent
retry.

---

## 6. Media pipeline

### 6.1 PNG → JPEG (`media.py`)

Add **Pillow** (`pillow>=11`) to `pyproject.toml` — the first new runtime
dependency.

```python
def to_jpeg(png: bytes, *, quality: int = 88) -> bytes
def validate_for_instagram(jpeg: bytes) -> list[str]   # aspect, dimensions, bytes
```

Conversion is done on the fly at serve time; the stored PNG stays canonical, so
nothing about the existing image feature changes.

**No cache was built.** The plan said "cached in-process by image id" and that
is not what shipped — every fetch re-converts. Left alone on purpose: the
endpoint is hit a handful of times per published post, by Meta, inside a
15-minute window, and a keyed byte cache is memory that only ever grows. What
did matter was the blocking: conversion runs under `asyncio.to_thread` so a
Meta fetch cannot stall the event loop for every other request.

### 6.2 Signed public image endpoint

Meta fetches the image itself, from Meta's servers. It cannot send our session
cookie, so this one endpoint must be unauthenticated — which makes it the most
security-sensitive addition in this plan.

```
GET /api/public/images/{image_id}.jpg?exp=<unix>&sig=<hex>
```

- `sig = HMAC-SHA256(MEDIA_SIGNING_SECRET, f"{image_id}|{exp}")`, compared with
  `hmac.compare_digest`.
- TTL 15 minutes, generated per publish attempt.
- Rejects with **404** (not 403) on a bad or expired signature — no oracle for
  which image ids exist.
- Returns `image/jpeg` with `Cache-Control: private, max-age=900`.
- The URL is unguessable but bearer-style for its lifetime. Acceptable: the
  image is about to be posted publicly. Documented as such rather than left
  implicit.
- `MEDIA_SIGNING_SECRET` is its own env var, not `AUTH_SECRET` — a leak of one
  must not forge sessions with the other.

**Local development:** without a public host, Facebook photo posts and all
Instagram posts fail with a clear `PublishError(code="unreachable_media")`.
Text-only Facebook and LinkedIn (which takes raw bytes) still work. The README
gets a one-line `ngrok http 8000` + `PUBLIC_API_BASE_URL` note for testing.

---

## 7. API surface

All under the existing `get_current_user` dependency except the public image
endpoint.

```
GET    /api/social/accounts                     → SocialAccountOut[]   (no tokens, ever)
GET    /api/social/{platform}/connect           → {authorize_url}
GET    /api/social/{platform}/callback          → 302 to FRONTEND_ORIGIN/settings?connected=…
POST   /api/social/accounts/{id}/activate       → make this the destination for its platform
POST   /api/social/accounts/{id}/verify         → ping the platform, refresh expiry/scopes
DELETE /api/social/accounts/{id}                → disconnect (best-effort remote revoke)

GET    /api/content/{item_id}/publish/preflight → {ready, blockers[], warnings[], account, image_id, text, char_count}
POST   /api/content/{item_id}/publish           → PublicationOut     {account_id?, image_id?}
GET    /api/content/{item_id}/publications      → PublicationOut[]

GET    /api/public/images/{image_id}.jpg        → signed, unauthenticated
```

The **callback keeps the auth dependency**: it is a top-level GET navigation,
so the `SameSite=lax` session cookie *is* sent. Both the cookie and the signed
`state` are verified — the state alone would not tell us the browser is still
logged in.

`SocialAccountOut` has no token field at all. Not "excluded", not "redacted" —
structurally absent from the Pydantic model, so a future careless edit to the
serializer cannot leak one.

**Preflight is server-side on purpose.** Duplicating the §5.5 rule table into
TypeScript guarantees drift the first time a platform changes a limit; one
round-trip when the dialog opens is cheaper than a wrong "looks fine" badge.

---

## 8. Frontend

### New — `/settings` (Connections)

Three cards, one per network:

- Disconnected: the network, what connecting allows, a **Connect** button
  hitting `/connect` and redirecting to `authorize_url`.
- Connected: Page/organization name and handle, granted scopes, an expiry line
  (`Token valid until 12 Oct 2026` → amber under 7 days → red when expired
  with **Reconnect**), plus **Verify** and **Disconnect**.

Design note per `web/design-quality.md`: this must not read as three identical
grey cards. Status is the hierarchy — a connected card carries the network's
own colour as a left rule and states its destination in large type; a
disconnected one is quiet and outline-only. The expiry countdown is the one
piece of live data on the page and should look like it.

### Changed — `VariantCard.tsx`

- **Publish** action, shown only when `item.status === "approved"`.
- Opens `PublishDialog` (portal + modal, mirroring `ImagePanel`'s existing
  pattern — reuse its focus trap and Escape handling rather than writing a
  second one):
  - destination account, with a link to `/settings` when unconnected;
  - the image that will be attached — thumbnail, picker over the item's images,
    and for Instagram a blocker when there is none;
  - the exact composed text from `composePostText()` with a character counter
    against the platform limit;
  - blockers (red, publish disabled) and warnings (amber, publish allowed);
  - after success: a green state with **View post ↗** to the permalink.
- **As built**, two things the spec above left implicit:
  - *Readiness is never computed client-side.* The button is enabled only when
    `preflight.ready` says so. A second, drifting copy of the §5.5 rules in the
    browser is exactly how a post gets sent that the backend would refuse.
  - *Sending takes a second, explicit confirmation* inside the dialog ("Yes,
    publish now"). The dialog is where you inspect; arming is where you commit.
    One misplaced click should not be enough for the only irreversible action
    in this app.
- A **failed** attempt returns HTTP 200 with a `failed` record (§7), so the
  dialog reads `publication.status`, not the HTTP status. Reading the latter
  would report a post as live that never went out. A `reauth` failure links
  straight to Settings.
- The image picker offers the post's existing images only. There is no "send it
  without an image" option when images exist: `image_id` omitted means *latest*,
  not *none*. Worth adding to the API if it is ever wanted.
- Published items show the permalink inline in the card header and lose every
  mutating action except **Archive** and **Duplicate**. An item that is live on
  Facebook must not be silently editable in our UI.

### Changed — elsewhere

- `types/content.ts`: `"published"` in `ContentStatus`; new `Publication`,
  `SocialAccount`, `PublishPreflight` types.
- `lib/api.ts`: `fetchPublishPreflight`, `publishContent`, `fetchPublications`,
  and the `/api/social/*` calls. `publishContent` stays a separate function
  rather than a `WorkflowAction` — the payload and response differ from every
  other action.
- `Badges.tsx`: a `published` status badge, visually distinct from `approved`
  (approved = "ready to go", published = "gone"). These being confusable is a
  real operational risk.
- History filters + `NavLinks`: `Published` option, `Settings` link.

---

## 9. Configuration

```bash
# ── Publishing (mock-first, D8) ──
PUBLISH_MOCK=true
# Public HTTPS origin of THIS backend. Required when PUBLISH_MOCK=false:
# it builds OAuth redirect URIs and the image URLs Meta fetches.
PUBLIC_API_BASE_URL=https://api.example.com

# Encrypts stored access/refresh tokens. urlsafe-base64 32 bytes:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY=
# Signs public image URLs. MUST differ from AUTH_SECRET.
MEDIA_SIGNING_SECRET=

# ── Meta (Facebook + Instagram) ──
META_APP_ID=
META_APP_SECRET=
META_GRAPH_VERSION=v23.0
# Set when using a Facebook Login for Business configuration; omits `scope`.
META_LOGIN_CONFIG_ID=

# ── LinkedIn ──
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_API_VERSION=202506
# urn:li:organization:{id} — or urn:li:person:{id} for the member fallback (D6)
LINKEDIN_AUTHOR_URN=
```

`Settings._validate_required_when_live` gains a branch: when
`publish_mock is False`, require `PUBLIC_API_BASE_URL`, `TOKEN_ENCRYPTION_KEY`,
`MEDIA_SIGNING_SECRET`, and the credential pair for each platform. Same
fail-fast contract as `LLM_MOCK`.

Confirm `META_GRAPH_VERSION` and `LINKEDIN_API_VERSION` against the live
changelogs at implementation time — both providers ship breaking versions on a
schedule, which is exactly why they are env vars.

New dependencies: `pillow>=11` (JPEG conversion), `cryptography>=44` (Fernet).

---

## 10. Security

Beyond the general checklist, the items specific to this feature:

- **Tokens** — encrypted at rest with a key that is not `AUTH_SECRET`; absent
  from every response model by construction; redacted in logs via the ported
  `redact_access_token_from_url`; never written to `audit_logs`
  (`request_summary` stores counts and ids, not payloads).
- **OAuth CSRF** — signed state with a 10-minute expiry, bound to the user id
  and platform, single-use, verified alongside the session cookie.
- **Open redirect** — the callback redirects only to `FRONTEND_ORIGIN` built
  from config, never to a URL taken from the request.
- **SSRF** — every outbound URL is constructed from config plus a UUID; no
  user-supplied URL is ever fetched by the publishers. (`reference_url` is
  fetched by the *generation* path, which already sandboxes it as best-effort.)
- **The public image endpoint** is the one unauthenticated surface: constant-time
  signature compare, short TTL, 404-not-403 on failure, and no listing.
- **Irreversibility** — publish is the only action in this app that cannot be
  undone from this app. Hence the `approved`-only gate, the confirm dialog, and
  the DB-level unique index against double-posting.
  - That index covers `pending` as well as `succeeded` (migration `0007`).
    Guarding only `succeeded` looked sufficient and was not: two concurrent
    requests could both pass the application check, both insert a `pending`
    row, and both reach the network. The index then stopped the second from
    being *recorded* — after it had already been *posted*, and with the losing
    session rolling back the only evidence it happened. Blocking the second
    `pending` refuses the duplicate while refusing still means something.
- **A stuck `pending` needs a human.** An attempt killed mid-flight leaves a
  `pending` row that blocks the item forever, by design — "we may have posted"
  must not silently become "try again". There is no self-service way to clear
  it. Check the account, then delete the row:
  `DELETE FROM content_publications WHERE id = '…' AND status = 'pending';`

Run the `security-reviewer` agent over `app/publishing/` and
`app/api/public_media.py` before the feature is merged.

---

## 11. Testing

Backend target ≥ 80% (currently 89% — do not regress). Everything below runs
offline: `PUBLISH_MOCK=true` for service tests, `httpx.MockTransport` for wire
tests, following the existing `test_fetcher.py` pattern.

File names below are **as built** — the three planned `test_publisher_*.py`
files landed as one `test_live_publishers.py`, and the OAuth work split by
concern instead of by the single planned `test_social_accounts.py`.

| File | Covers |
|---|---|
| `test_publishing_crypto.py` | encrypt/decrypt round trip; wrong key fails; ciphertext ≠ plaintext |
| `test_oauth_state.py` | OAuth state sign/verify; expiry; tampering; cross-platform replay |
| `test_oauth_providers.py` | the Meta 4-step exchange; LinkedIn org vs member mode; the mock provider |
| `test_oauth_api.py` | connect/callback routing; state bound to the user; no open redirect |
| `test_publishing_rules.py` | the §5.5 table, exhaustively; plus the shared `compose_post_text` contract |
| `test_publishers.py` | the seam: `get_publisher`/`get_verifier` and the offline mock |
| `test_live_publishers.py` | all three wire contracts under `httpx.MockTransport`: FB text vs photo body; IG two-step incl. an ERROR container; LI three-leg upload, headers and `x-restli-id`; **commentary escaping incl. `#`, `(`, `)`**; the Graph error taxonomy; **and the double-post guard (below)** |
| `test_publish_service.py` | approved-only gate; idempotency (2nd call 409s with the permalink); failure leaves `approved` + a `failed` row; audit rows written; stale `pending` blocks retry; **a concurrent attempt is refused before it reaches the network** |
| `test_publishing_api.py` | auth required; 404/409/422 mapping; **response bodies contain no token substring** |
| `test_publishing_media.py` | PNG→JPEG conversion, Instagram spec checks, URL signing |
| `test_public_media.py` | valid signature serves JPEG; bad/expired → 404; tampered `exp` → 404 |

### The double-post guard, and why its tests look odd

Every test in the "double-post guard" block of `test_live_publishers.py` pins
`publish_max_attempts` **above 1**. That is not incidental. The original
publishers shipped with a bug — a network response that accepted the post but
omitted its id was raised as `transient`, which the retry wrapper duly retried,
posting the same content up to three times — and the whole suite was green,
because every "no id" test pinned attempts to 1 and so never entered the retry
path at all. A test that cannot reach the code where the bug lives proves
nothing about it.

Two rules came out of that, both enforced by tests that fail on the old code:

- `ambiguous` is its own error code and is **never** retried. It means the
  network took a post we cannot name, so something is probably live.
- Instagram and LinkedIn run their post-creating call **outside** the retry, so
  a retry can only ever repeat preparation (a container, an image upload) —
  never a publish. Facebook's whole operation is that one call, so it still
  retries as a unit.

Frontend (vitest): `PublishDialog` renders blockers and disables publish; the
Publish action appears only on `approved`; a published card shows the permalink
and hides mutating actions; `Badges` renders `published` distinctly.

Playwright: extend the smoke spec to reach `/settings` and assert the three
disconnected cards render.

---

## 12. Build order

Phases 1–3 need none of the external approvals, so start them immediately and
run §2 in parallel.

| Phase | Work | Est. |
|---|---|---|
| **0** | External setup (§2). Mostly waiting — LinkedIn approval is the long pole. | ~1–3 days elapsed, ~2h hands-on |
| **1** | Config + `crypto.py` + `state.py`; migration `0006`; models + enums + state machine; `Publisher` protocol + `MockPublisher`; `PublishService`; `POST /publish` end-to-end on the mock; tests. **Ships something demonstrable with zero credentials.** | 1.5 days |
| **2** | Pillow; `media.py` JPEG conversion; signed public image endpoint + tests. | 0.5 day |
| **3** | OAuth: `oauth/base.py`, `meta.py`, `linkedin.py`; `SocialAccountService`; `/api/social/*`; the `/settings` page. | 2 days |
| **4** | Real publishers: port `facebook.py` + `instagram.py` from §3, write `linkedin.py` net-new; transport-mocked tests; first live post to each network. | 2 days |
| **5** | `PublishDialog`, `VariantCard` changes, badges, history filter, preflight wiring, vitest. | 1.5 days |
| **6** | README + `.env.example` + `docs/PLAN.md` scope update; coverage back to ≥89%; `ruff`/`mypy`/`tsc` clean; `security-reviewer` + `code-reviewer` pass. | 0.5 day |

**≈ 8 working days**, plus the LinkedIn approval wait, which only blocks the
LinkedIn half of Phase 4.

### Left open for scheduling (D8)

Two cheap choices now that make the scheduling phase additive rather than a
refactor: `content_publications` already models an *attempt* rather than a
state, and `PublishService.publish()` takes an explicit `actor_id` instead of
reading a request-scoped user. A scheduler adds a `scheduled_for` column, a
worker that calls the same service with a system actor, and a queue view —
nothing in this plan needs rewriting.

---

## 13. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| LinkedIn Community Management API not approved | No Company Page posting | Author URN is config → switch to `w_member_social` member posting (self-serve, instant). FB/IG unaffected. |
| Page token silently dies (password change, revoked permission, expired user token) | Publishing 500s with a cryptic Graph message | Code `190` maps to a typed reauth error; Settings shows expiry; `verify` endpoint pings on demand; UI says "Reconnect the Facebook Page". |
| Instagram rejects the image (aspect, size, format) | Failed publish after the user hits the button | `rules.py` validates before any network call; the dialog shows the blocker up front. |
| IG 25-posts/24h quota | Publish fails mid-batch | Preflight reads `content_publishing_limit` and shows remaining quota. |
| Response lost after the post landed | Double-post on retry | `pending` row committed before the call; stale `pending` shows *unknown — check the Page* and blocks a silent retry; partial unique index makes a second success impossible. |
| Graph / LinkedIn version deprecation | Publishing breaks with no code change on our side | Both versions are env vars; the `verify` endpoint surfaces deprecation warnings; note the review dates in the README. |
| Public image URL leaks | The image is visible to anyone holding the link, for 15 min | Accepted and documented — the image is about to be posted publicly. Unguessable id + short TTL + no listing. |
