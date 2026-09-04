# Post media — upload, selection and per-network preview

Extends [`docs/PUBLISH-PLAN.md`](PUBLISH-PLAN.md). That document listed
**carousels** under *out of scope*; this one brings them in, along with
operator-uploaded images and a per-network preview, and records the decisions
**D9–D14**.

---

## 1. Scope

Today a post image can only be *generated*, only one of them ever reaches a
network (silently: the most recent), and the last thing an operator sees before
publishing is a `<pre>` block of plain text. This phase changes all three.

**In scope**

- **Upload** operator-supplied images alongside the AI-generated ones, with the
  two actions visibly distinct in the UI.
- A **media library scoped to the generation group**, so an image uploaded for
  the Facebook variant is available to the Instagram and LinkedIn variants of
  the same generation without re-uploading.
- **Explicit, ordered selection** of which images go out with each post —
  including none, one, or several.
- **Multi-image publishing**: Facebook multi-photo, Instagram carousel,
  LinkedIn multi-image.
- A **per-network preview** in the publish dialog: the post rendered inside an
  approximation of Facebook / Instagram / LinkedIn chrome, using the exact text
  the server will send.

**Out of scope for this phase** (deliberate, listed so it is not accidental)

- Video, stories, reels, alt-text authoring workflows beyond a single field.
- In-app cropping, filters or any image editing. An image that violates a
  network's aspect rules is reported, not silently cropped — same rule as today.
- Moving image bytes out of Postgres to an object store. See §10 for the growth
  arithmetic that will eventually force this, and why not now.
- A group-level "preview all networks side by side" screen. The preview lives
  in the publish dialog only.

### Decisions

| | Decision | Rationale |
|---|---|---|
| **D9** | **Media assets are group-scoped, selection is per item.** `content_images` becomes `media_assets` (owned by a `generation_group`); a new `content_item_media` join table records *which* assets a given item posts, and *in what order*. | An item is one platform. Making images belong to the item means uploading the same photo three times for one campaign. Making the *selection* per item is what lets LinkedIn diverge from Facebook when the operator wants that. Both properties are needed; one table cannot hold both. |
| **D10** | **Uploads are re-encoded at ingest**, never stored as received: sniffed with PIL, capped at 2048px on the long edge, metadata stripped, written back as JPEG (or PNG when the source has alpha). | Three problems, one fix. A phone photo carries GPS coordinates in EXIF and we serve these bytes from an unauthenticated endpoint. A 24 MP upload is 8 MB in a column that lives in the database. And trusting a client-declared content-type is how a non-image ends up served under our origin. Re-encoding settles all three and keeps `to_jpeg` / `instagram_problems` working unchanged. |
| **D11** | **Selection is explicit and ordered; publishing sends exactly it.** No implicit "latest image" fallback for newly selected posts. | Today's fallback is invisible: generate four images and the fourth goes out, with nothing in the UI saying so. Order is not cosmetic either — it is the carousel sequence, and on Instagram the first image's aspect ratio crops all the others. |
| **D12** | **Multi-image is built per platform, with the retry boundary in the same place as today.** Scaffolding (unpublished photos, carousel children, uploaded LinkedIn assets) is retried freely; the one call that creates the post is never retried. | This is the existing rule in `retry.py` and the Instagram publisher, applied to N images instead of one. It is the property that keeps `ambiguous` rare and a double post impossible. |
| **D13** | **The preview renders `preflight.text` verbatim**; it never recomposes the post client-side. | The whole point of the preview is "this is what will be sent". A second composer in the preview component would be a third copy of `compose_post_text`, and the one that lies is the one the operator is looking at. |
| **D14** | **Ship in five phases, each independently deployable**, with multi-image publishing (Phase 3) after upload + selection (Phase 2). | Phase 2 is demoable to the client on its own — upload, library, selection, one image still goes out. It de-risks the client conversation before the expensive publisher work starts. |

---

## 2. External prerequisites

Only one, and it gates Phase 3 for LinkedIn alone:

**LinkedIn multi-image posts** use `content.multiImage` on the Posts API and
require the same Community Management API approval the current single-image
path already needs (§2.3 of the publish plan). Confirm the shape against the
`LINKEDIN_API_VERSION` in use before building — LinkedIn ships breaking
versions on a schedule, which is why that value is an env var. If multi-image
turns out to be unavailable on the approved version, LinkedIn degrades to
"first selected image only" and the preflight says so; Facebook and Instagram
are unaffected.

Facebook and Instagram need nothing new. Both mechanisms (`attached_media`,
`CAROUSEL`) are available to a Development-mode app with the permissions
already requested.

---

## 3. Data model

### 3.1 `media_assets` — was `content_images`

Renamed rather than recreated, so the primary keys survive and
`content_publications` keeps pointing at real bytes.

| Column | Change |
|---|---|
| `id` | unchanged |
| `content_item_id` | **dropped** after backfilling `content_item_media` |
| `generation_group` | **new**, `Uuid`, nullable, indexed — the library scope |
| `source` | **new**, `MediaSource` enum: `generated` \| `uploaded` |
| `prompt` | now **nullable** — an uploaded file has no prompt |
| `model` | now **nullable** — same reason |
| `filename` | **new**, `Text`, nullable — sanitised original name, display only |
| `mime_type` | **new**, `Text`, not null — `image/png` or `image/jpeg`, nothing else |
| `width`, `height`, `byte_size` | **new**, `Integer`, not null |
| `checksum` | **new**, `Text`, not null — sha256 of the stored bytes, for dedupe |
| `alt_text` | **new**, `Text`, nullable — the default alt; per-item override lives on the join row |
| `data`, `created_by`, `created_at` | unchanged |

`generation_group` is nullable because `ContentItem.generation_group` is: rows
predating the group, or an item that somehow lost one, fall back to "assets
attached to this item" and the library is simply smaller.

### 3.2 `content_item_media` — the selection

```
id                uuid pk
content_item_id   uuid  fk content_items(id)  on delete cascade
media_asset_id    uuid  fk media_assets(id)   on delete cascade
position          int   not null
alt_text          text  null      -- per-item override; alt copy can differ per network
created_at        timestamptz

unique (content_item_id, media_asset_id)
index  (content_item_id, position)
```

Position uniqueness is **not** a constraint. Reordering rewrites the whole
selection for an item in one statement (delete + insert inside the request's
transaction), so a transient duplicate never exists, and a deferrable unique
index buys nothing while costing a Postgres-only behaviour the SQLite test path
does not share.

### 3.3 `content_publication_media` — what actually went out

```
id               uuid pk
publication_id   uuid  fk content_publications(id) on delete cascade
media_asset_id   uuid  fk media_assets(id)         on delete set null
position         int   not null
```

`content_publications.content_image_id` is **dropped**. Keeping it as a "cover
image" beside this table would be two records of the same fact, and the pair
would drift the first time someone changed one of them. `SET NULL` on the asset
mirrors the existing rule for `social_account_id`: the record of what was
published must outlive the thing it referenced.

### 3.4 Migration `0008_media_assets.py`

Order matters; each step is reversible.

1. `ALTER TABLE content_images RENAME TO media_assets` and add the new columns
   nullable.
2. Backfill: `source = 'generated'`, `mime_type = 'image/png'`, `checksum` and
   `width` / `height` / `byte_size` computed by reading each row's bytes through
   PIL in a batched Python data-migration, `generation_group` copied from the
   owning `content_items` row.
3. Create `content_item_media`; insert one row (`position = 0`) for the **most
   recent asset of each item**. This preserves today's behaviour exactly — the
   implicit "latest image" becomes an explicit selection instead of vanishing.
   Older assets stay in the library, unattached.
4. Create `content_publication_media`; insert one row per publication that has
   a `content_image_id`. Then drop that column.
5. Make the backfilled columns `NOT NULL`, drop `content_images.content_item_id`.

Downgrade reverses it, keeping the first selected asset per item as
`content_item_id` and the first published asset as `content_image_id`. Lossy by
nature — selections beyond the first cannot survive a schema that has no place
for them — and the docstring says so rather than pretending otherwise.

---

## 4. Backend

### 4.1 Ingest (`app/content/media.py`, new — `images.py` grows into it)

Upload is the only place in this application where a caller hands us bytes we
then serve to the public internet, so the pipeline is ordered so that the
cheapest rejection happens first:

1. **Size** — reject on `Content-Length` over `MEDIA_UPLOAD_MAX_BYTES`
   (default 10 MB), *then* read with a hard cap while streaming. The header is a
   claim, not a fact.
2. **Library cap** — no more than `MEDIA_MAX_ASSETS_PER_GROUP` (default 40)
   assets per generation group. Bounds the blast radius of a stuck finger on a
   drag-and-drop.
3. **Format** — `PIL.Image.open` + `verify()`; accept `PNG`, `JPEG`, `WEBP`
   only, decided by the decoded header. The declared content-type and the
   filename extension are ignored entirely.
4. **Decompression bomb** — `Image.MAX_IMAGE_PIXELS` set explicitly, and a
   pixel-count check before any full decode.
5. **Normalise** — downscale to 2048px on the long edge, strip EXIF/ICC by
   re-encoding from raw pixel data, save as JPEG q=90 (or PNG when the source
   has a real alpha channel). This is the byte sequence we store; the original
   is never persisted.
6. **Dedupe** — sha256 of the stored bytes; an identical asset already in the
   group is attached rather than stored twice.
7. **Audit** — `media_asset.upload`, with filename, byte size and dimensions.

Uploads are rate-limited using the existing `auth/rate_limit.py` bucket.

### 4.2 API surface

```
POST   /api/content/{item_id}/media            multipart, one or more files → MediaAssetOut[]
GET    /api/content/{item_id}/media            → { library: MediaAssetOut[], selection: ItemMediaOut[] }
PUT    /api/content/{item_id}/media/selection  { asset_ids: [...], apply_to_group?: bool } → ItemMediaOut[]
DELETE /api/content/media/{asset_id}           → 204
POST   /api/content/{item_id}/images           unchanged (generate) — now returns MediaAssetOut
GET    /api/content/images/{id}/file           unchanged path, honest content type (§4.3)
```

- `PUT .../selection` replaces the ordered selection atomically. Passing `[]`
  is legal and means "text only" (and the preflight will block it for
  Instagram, which is correct).
- `apply_to_group: true` copies the same selection to the sibling items of the
  generation group. **This is the "Facebook and Instagram must show the same
  images" case**, and it is an action rather than a schema property precisely
  so LinkedIn can be given a different set afterwards. Siblings whose platform
  cannot accept the full set come back as per-item warnings in the response —
  the server never silently truncates someone's selection.
- `DELETE` refuses (409) for an asset referenced by a **succeeded** publication.
  Our record of what is live on someone else's server must not develop holes.

### 4.3 The `/file` endpoint stops lying

It currently hardcodes `media_type="image/png"` and a `.png` filename. With
uploads it must serve `asset.mime_type`, derive the download extension from it,
and send `X-Content-Type-Options: nosniff`. The public signed endpoint
(`/api/public/images/{id}.jpg`) needs no change: it already converts whatever
is stored to JPEG through `to_jpeg`, which is correct for every accepted input.

### 4.4 Preflight rules (`rules.py`, still pure)

`PlatformLimits` gains:

```python
max_images: int      # facebook 10, instagram 10, linkedin 20
carousel_min: int    # instagram 2 — below this it is a single post, not a carousel
```

`PreflightContext.has_image: bool` becomes `image_count: int`, and
`image_problems` carries per-image entries prefixed with their position
(`"Image 2: …"`) rather than one anonymous list. New outcomes:

- **blocker** — more images than the platform accepts.
- **blocker** — Instagram: *every* carousel child must satisfy the size and
  aspect rules, not just the first.
- **warning** — Instagram crops every image in a carousel to the aspect ratio of
  the first one. Worth saying out loud; it is the single most common surprise
  in an IG carousel.
- **warning** — a selection of exactly one image while other assets in the
  library sit unattached. Cheap to say, and it catches the "I generated four and
  forgot to tick them" mistake.

### 4.5 The publisher seam

```python
@dataclass(frozen=True, slots=True)
class PublishImage:
    data: bytes          # always JPEG, converted once by the service
    url: str | None      # signed + short-lived, for the networks that fetch it themselves
    alt: str | None

@dataclass(frozen=True, slots=True)
class PublishRequest:
    text: str
    account: ResolvedAccount
    images: tuple[PublishImage, ...] = ()   # replaces image_url / image_bytes / image_alt
    link: str | None = None
```

A breaking change to the seam, taken deliberately rather than bolting a second
plural field beside the singular ones: the mock publisher and all three live
implementations are updated together, which is exactly what the narrow protocol
in `publishers/base.py` was for.

### 4.6 Per-platform

**Facebook** — three shapes now.

| Images | Calls |
|---|---|
| 0 | `POST /{page}/feed` — unchanged |
| 1 | `POST /{page}/photos` with the caption — unchanged, same permalink shape |
| ≥2 | N × `POST /{page}/photos` `published=false` → collect ids → one `POST /{page}/feed` with `attached_media` |

The unpublished photos are scaffolding in the same sense as an Instagram
container: invisible on the Page, harmless if abandoned, and therefore freely
retried. The `/feed` call that assembles them into a post runs exactly once.

**Instagram** — 1 image keeps today's path verbatim. 2–10 becomes: N child
containers (`is_carousel_item=true`, each with its own signed URL), then a
parent container (`media_type=CAROUSEL`, `children=<csv>`, caption), then one
`media_publish`. Children and parent are retried; `media_publish` is not, and
an accepted publish with no returned media id stays `ambiguous`.

**LinkedIn** — 1 image keeps `content.media`. ≥2 uses N × initializeUpload +
PUT (each retried on its own, an uploaded asset being a private URN and not a
post), then one create-post carrying `content.multiImage.images[]` with the
per-image alt text.

### 4.7 `PublishService`

- `_resolve_image(item, image_id)` becomes `_resolve_media(item, asset_ids)`:
  explicit ids from the request when given (validated to belong to the item's
  generation group), otherwise the item's stored selection. The "latest image"
  fallback survives only for items whose selection is empty *and* which predate
  this phase — it is written as a compatibility branch and commented as one.
- Every selected asset is converted through `to_jpeg` **before** the attempt row
  is written; an unreadable asset is still a refusal, not a failed publish.
- All signed URLs are minted at the start of the request from one clock, so a
  ten-image carousel does not race its own TTL. `MEDIA_URL_TTL_SECONDS` (900)
  covers a ten-child build comfortably, but the plan raises it to 1800 for
  headroom; the container-poll settings stay as they are.
- The attempt writes one `content_publication_media` row per image, in order,
  inside the pre-call commit. `request_summary` gains `"image_count"`.

---

## 5. Frontend

### 5.1 `MediaPanel` — replaces `ImagePanel`

Same modal shell. Three regions instead of two.

**A segmented control at the top of the compose column** is where the client's
"the generate button and the upload button must be different things" is
answered:

```
┌───────────────────────────────────────────────┐
│  [ ✨ Generate with AI ]  [ ⬆ Upload files ]   │
└───────────────────────────────────────────────┘
```

- **Generate** — today's suggestions + editable prompt + Generate, unchanged.
- **Upload** — a drop zone plus a file input
  (`accept="image/png,image/jpeg,image/webp"`, `multiple`), per-file progress,
  and client-side size/type checks that *mirror* the server's and never stand in
  for them. Rejections name the file and the reason.

**The library grid** shows every asset in the generation group, each tile
carrying a source badge (`AI` / `Uploaded`), a selection checkbox, and its order
number once selected. Assets belonging to sibling platforms are visible here —
that is the point of the group scope — and are labelled as such.

**The selection strip** shows the ordered set for *this* post, with ↑/↓ reorder
(arrows rather than drag-and-drop: keyboard-operable, no dependency, and the
lists are short), remove, an `n / max` counter for the platform, and a
**"Use these images on the other platforms too"** action that calls
`apply_to_group`. Saving is one `PUT`, applied optimistically with rollback.

`VariantCard`'s footer button becomes `🖼 Media (n selected · m available)`.
If you would rather have the two actions on the card itself rather than one
level in, that is a small change: two buttons that open the panel on their
respective tab. Decide before Phase 2 starts.

### 5.2 `PostPreview` — new, used by `PublishDialog`

Replaces the `<pre>` block. One component, three chrome variants, driven by
`preflight`:

- **Facebook** — Page avatar, name, timestamp line; text folded at ~477
  characters behind *See more*; the 1/2/3/4+ photo mosaic; a link card when
  there is a `reference_url` and no image.
- **Instagram** — media area at the real aspect ratio of the first image
  (clamped to 4:5 – 1.91:1, showing the crop the operator will actually get);
  carousel dots and arrows; action row; caption as `username` + text, folded at
  ~125 characters behind *more*; hashtags in the link colour.
- **LinkedIn** — company avatar, name, follower line; text folded at ~200
  characters behind *…see more*; multi-image grid.

Rules that keep it honest:

- Text comes from `preflight.text` and nothing else — the server's
  `compose_post_text` output, character for character (D13).
- The fold thresholds live in one `PREVIEW_FOLD` table, commented as cosmetic
  approximations of each network's *UI*. The real API limits stay in the
  server's preflight and are already shown in the character counter beside it.
- The panel is labelled **"Approximate preview"**. It is a rehearsal, not a
  rendering contract, and the label is what stops it being read as one.
- Theme-aware, and the carousel transition respects `prefers-reduced-motion`.

### 5.3 Types and client

`ContentImage` → `MediaAsset` (`source`, `mime_type`, `width`, `height`,
`filename`, nullable `prompt` / `model`), plus `ItemMedia` for a selection row.
`PublishRequestBody.image_id` → `asset_ids: string[]`, and
`PublicationOut.content_image_id` → `media_asset_ids: string[]`. `api.ts` gains
`uploadMedia` (multipart — note it must *not* send the JSON `Content-Type` the
shared `request()` helper sets), `fetchMedia`, `saveSelection`, `deleteAsset`.

---

## 6. Configuration

```
MEDIA_UPLOAD_MAX_BYTES=10485760      # 10 MB per file
MEDIA_MAX_ASSETS_PER_GROUP=40
MEDIA_MAX_DIMENSION=2048             # long edge after normalisation
MEDIA_UPLOAD_RATE_LIMIT=30/minute
MEDIA_URL_TTL_SECONDS=1800           # raised from 900 for ten-child carousels
```

All have working defaults. Nothing here is a secret, and the "boots with zero
credentials" property (D3) is untouched.

---

## 7. Security

The new surface is one authenticated multipart endpoint and a widened public
one, so the list is short and specific:

- **Never trust the declared type.** Format is decided by PIL from the decoded
  header; the extension and content-type header are not consulted.
- **Never store what was sent.** Re-encoding from raw pixels means a polyglot
  file cannot survive ingest, and EXIF GPS from a phone photo cannot reach the
  public endpoint. This is the substance of D10.
- **Bound the read.** Streaming cap, not just a `Content-Length` check.
- **Bound the pixels.** An explicit `MAX_IMAGE_PIXELS` and a pre-decode check;
  a 100 MP PNG is a memory exhaustion, not a picture.
- **`nosniff` and an honest content type** on `/file`, now that the bytes are
  not all PNGs of our own making.
- **Filenames are display data.** Sanitised on ingest, never used to build a
  path or a `Content-Disposition` value; the download name is derived from the
  asset id exactly as it is today.
- The signed public endpoint's guarantees are unchanged: HMAC over `id|exp`,
  constant-time compare, 404 on every failure. Uploaded bytes ride the same
  path as generated ones.

---

## 8. Testing

**Backend** (pytest; the suite is at ~93% and must not regress below 80%)

- Ingest: oversized file; a non-image sent with `image/png`; PNG with alpha
  preserved as PNG; WEBP normalised to JPEG; a 60 MP bomb refused; **EXIF with
  GPS present in the input and absent from the stored bytes**; identical bytes
  deduped to one asset.
- Selection: replace, reorder, empty; over the platform maximum refused;
  `apply_to_group` returning per-item warnings instead of truncating; delete
  refused for an asset referenced by a succeeded publication.
- Preflight: per-platform `max_images`; per-image Instagram problems reported
  with their index; the carousel-crop warning.
- Publishers, through `httpx.MockTransport`, asserting the wire payloads:
  Facebook 0/1/N shapes and the `attached_media` body; Instagram children →
  parent → publish, **and that `media_publish` is not retried**; LinkedIn
  `content.multiImage.images[]`. Existing `ambiguous` / `reauth` behaviour
  re-asserted at N images.
- Migration `0008` up and down against a seeded database: ids preserved,
  `content_publications` still resolves to bytes, the latest-image backfill
  reproduces the pre-migration publish target.

**Frontend** (vitest, currently 66)

- `MediaPanel`: tab switching, upload rejection messages, selection cap
  enforced, reorder, `apply_to_group`.
- `PostPreview`: fold behaviour per platform, carousel dots, Instagram aspect
  clamp, and — the one that matters — that it renders `preflight.text`
  unmodified.
- `PublishDialog` sends `asset_ids` in order.

**Playwright**: generate → upload a fixture image → select two → open Publish →
preview renders both → publish against the mock.

`shared/` gains nothing. The fold thresholds exist in one language and are
cosmetic; a shared fixture there would imply a contract that does not exist.
`post-text-cases.json` stays the only thing in that directory, which is the
point of D13 — the preview reads the server's text rather than growing a second
composer that would have needed one.

---

## 9. Build order

| Phase | What | Ships alone? |
|---|---|---|
| **1** | Migration `0008`, models, `MediaAssetOut` / `ItemMediaOut`, service reads rewritten against the new tables. No behaviour change. | Yes — invisible, and the safest thing to deploy on its own. |
| **2** | Upload endpoint + ingest pipeline, selection endpoints, `MediaPanel` with the two separated actions. Publishing still sends the **first** selected image. | **Yes — and this is the client demo.** Upload, library, selection all working end to end. |
| **3** | `PlatformLimits.max_images`, the `PublishRequest.images` seam, the three publishers, `content_publication_media`. | Yes. |
| **4** | `PostPreview` in the publish dialog. | Yes — independent of 3, and can be pulled forward if the client wants something visual sooner. |
| **5** | `README.md`, `PUBLISH-PLAN.md` §1 (carousels leave the out-of-scope list), this document's status. | — |

Phase 4 has no dependency on Phase 3 beyond rendering more than one thumbnail,
so if the client's next review is close, build 4 before 3.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| LinkedIn `multiImage` unavailable on the approved API version | Verify against the changelog before Phase 3 starts. Degrade to first-image-only for LinkedIn, reported in preflight. Facebook and Instagram are unaffected. |
| A ten-child Instagram carousel outruns the signed-URL TTL | Sign every child at request start from one clock; raise `MEDIA_URL_TTL_SECONDS` to 1800. |
| Facebook leaves orphaned unpublished photos when a run dies between the uploads and `/feed` | They are invisible on the Page and expire. Documented in the publisher docstring rather than swept up — a cleanup pass would itself be a network call in a failure path. |
| The `PublishRequest` seam change touches every publisher at once | It is four implementations behind one Protocol, all with existing `MockTransport` tests. Phase 3 is the only phase where the whole seam moves, and it moves in one commit. |
| **Database growth.** Generated PNGs are ~1–2 MB each; ten uploaded photos per post is a different arithmetic in a `LargeBinary` column. | D10's normalisation (2048px, JPEG q90) puts a typical upload at 300–600 KB, the per-group cap bounds a runaway, and checksum dedupe kills the common re-upload case. Together that keeps this phase inside the current storage story. It does **not** hold forever: at sustained volume the answer is an object store behind the same `media_assets` row, with `data` becoming a key. Not built now (YAGNI), but nothing in this design blocks it — every read already goes through the service. |

---

## 11. What was built differently

Implemented 2026-09-04. Four things diverged from the plan above, each because
building it made the plan look wrong.

**A newly created asset attaches itself; there is no "latest image" fallback.**
§4.7 kept an implicit last-image rule as a compatibility branch. That turned out
to be unnecessary — the migration backfills an explicit selection for every
existing post, so nothing reaches the fallback — and it was solving the wrong
problem anyway. Generating an image *for* a post and having it not go out is the
same invisible behaviour D11 exists to remove, only inverted. So `generate` and
`upload` append the new asset to the requesting post's selection, visibly ticked
in the panel, stopping at the platform ceiling rather than evicting a choice the
operator made. The fallback branch does not exist.

**Deleting an asset is cleaned up in the service, not left to the database.**
The FKs declare `CASCADE` and `SET NULL`, but SQLite does not enforce foreign
keys by default and the ORM does not cascade to rows it has no relationship
for — so production and the test suite would have disagreed about what a delete
does. `MediaService.delete_asset` clears the dependent rows itself and closes
the gaps left in any selection's `position` sequence.

**The preflight parameter is one comma-separated `asset_ids`, not a repeated
`asset_id`.** §4.2's repeated parameter cannot express an empty list, and
"send no images" has to stay distinguishable from "use what is saved" — which
is the whole point of D11. One parameter keeps all three states.

**The migration test builds the pre-0008 schema by hand.** §8 assumed the
revision chain could be replayed on SQLite. It cannot: revisions 0001–0006
declare `postgresql.JSONB` columns directly. Those revisions have already run in
production; 0008 has not, so the test creates the four tables 0008 touches,
stamps 0007, and exercises the upgrade and the downgrade against that. It
required one change to `migrations/env.py`: an explicitly supplied
`sqlalchemy.url` now wins over the environment, and a synchronous URL runs
through a synchronous engine.

### Not done

**The Playwright flow in §8.** `playwright.config.ts` starts the frontend alone
and says so in a comment — "full-stack flows are covered by backend integration
tests" — so a generate → upload → select → publish journey would mean standing
a backend up in the E2E harness, which is a change to the project's testing
strategy rather than part of this feature. The same ground is covered by 21
backend API tests, 19 `MediaPanel` tests, 14 `PostPreview` tests and 8
`PublishDialog` selection tests. Worth revisiting as its own decision.

---

## 12. Left open

- **Alt text** has a column on both the asset and the join row but no authoring
  UI in this phase; the publishers already send `alt` where a network accepts
  it (falling back to the prompt, then the filename). A field in the selection
  strip is a small follow-up.
- **A group-level preview** across all activated networks is deliberately out
  (§1). `PostPreview` takes `platform`, `text`, `images` and `account` as props
  and holds no state, so a comparison screen is a layout around the existing
  component rather than a rewrite of it.
- **Two buttons on the card** instead of one `🖼 Media` entry with the two
  actions inside it. Still a ten-minute change if the client prefers it.
- **Object storage** — see §10.
