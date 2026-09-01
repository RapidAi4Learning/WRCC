# WRCC Content Studio — Plan de implementación

Proyecto nuevo e independiente en `C:\Projects\wrcc-content-studio` para
**Western Riverina Community College** (https://wrcc.nsw.edu.au/), reutilizando
y generalizando el feature de generación de contenido social y el scraper de
catálogo de `mcc-growth-agent`.

---

## 1. Alcance

**Incluye**
1. Generación de contenido multi-plataforma: **Facebook, Instagram, LinkedIn**,
   con tono/formato adaptado por plataforma.
2. **3 ideas de post por solicitud** a partir de `topic` + `reference_url` +
   `notes` opcionales, o a partir de un **curso real del catálogo scrapeado**.
3. **Historial persistente** de todo lo generado (topic, plataforma, variantes,
   estado, timestamps) con flujo de aprobación HITL (draft → pending →
   approved/rejected) y consulta/reutilización (duplicate/regenerate).
4. **Scraper de cursos WRCC** con split `courses` / `course_offerings`,
   migraciones Alembic y sync staged con aprobación humana (mismo patrón que
   MCC: crawl → normalize → diff → stage → approve/reject → apply).
5. **Integración catálogo → generación**: elegir un curso y generar las 3 ideas
   con sus datos reales (nombre, código, precio, próximas fechas, ubicaciones).

**Incluye además** (pedidos post-plan, en orden cronológico):
- **Login básico** — ver §4a y D2.
- **Imágenes de post** — generación con `gpt-image-1`, bytes guardados en
  `content_images.data` (migración `0005`), panel en `VariantCard`.
- **Publicación a las redes** — Facebook, Instagram y LinkedIn, con OAuth
  in-app, tokens cifrados y un gate HITL de `approved` → `published`. Tiene su
  propio documento: [`PUBLISH-PLAN.md`](PUBLISH-PLAN.md), decisiones D5–D8.

**Fuera de alcance (deliberado, para acotar diffs)**
- Scheduling, analytics, campañas, brand-voice profiles editables,
  comentarios/DMs.
- ~~Publicación a las redes~~ e ~~imágenes/media~~: ambas salieron de este
  apartado más tarde (ver arriba). El resto de la lista sigue vigente.
- Gestión de usuarios avanzada (roles/permisos, registro self-service,
  recuperación de contraseña); el login es básico: usuarios seeded + sesión.
- El historial de revisiones por item (`content_revisions`) queda como
  extensión futura; el historial pedido se cubre con `content_items`.

---

## 2. Stack (idéntico a mcc-growth-agent)

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2 async + asyncpg, Alembic |
| DB | PostgreSQL (SQLite aiosqlite para tests unitarios donde aplique) |
| LLM | `google-genai` (Gemini flash) detrás de `BaseLLMClient` con **MockLLMClient determinista** (flag `LLM_MOCK=true` por defecto) |
| Scraper | `httpx` async + politeness delay + retries, `beautifulsoup4` (el sitio WRCC es server-rendered — sin headless browser) |
| Frontend | Next.js 14 + React 18 + TypeScript, CSS modules |
| Tests | pytest + pytest-asyncio + fixtures HTML guardadas; vitest + Playwright en frontend |

Convenciones que se conservan: agentes/nodos puros sin imports de DB/framework,
services con commit + `record_audit`, repositorios finos, schemas Pydantic
separados, máquina de estados con `assert_transition`, mock-first para todo lo
externo.

---

## 3. Estructura del proyecto

```
wrcc-content-studio/
├── docs/PLAN.md
├── backend/
│   ├── pyproject.toml, alembic.ini, Dockerfile
│   ├── app/
│   │   ├── main.py, config.py            # create_app(), pydantic-settings
│   │   ├── db/                           # base.py, enums.py, models.py
│   │   ├── auth/                         # hashing, jwt, deps, router (§4a)
│   │   ├── llm/client.py                 # Base/Mock/Gemini + platform prompts
│   │   ├── agents/
│   │   │   ├── content_generator.py      # nodo puro: contexto + variantes
│   │   │   └── validation.py             # baseline de reglas p/ ranking
│   │   ├── content/
│   │   │   ├── schemas.py, repository.py, service.py, state.py
│   │   ├── scraper/
│   │   │   ├── types.py, fetcher.py, discovery.py, parser.py,
│   │   │   ├── normalize.py, diff.py, repository.py, service.py
│   │   ├── services/courses.py           # sync HITL (approve/reject)
│   │   ├── audit.py
│   │   └── api/                          # routers: content, courses, sync, health
│   ├── migrations/versions/
│   └── tests/  (+ tests/fixtures/wrcc/*.html)
└── frontend/
    ├── package.json, next.config.mjs, tsconfig.json
    ├── app/
    │   ├── generate/page.tsx             # compose: curso o topic/URL/notas
    │   ├── history/page.tsx              # historial + filtros + acciones
    │   └── catalog/page.tsx              # cursos + sync + approve/reject
    ├── components/ , lib/api.ts , styles/
```

---

## 4. Esquema de datos y migraciones

### Migración `0001_initial` — users + audit_logs (Fase 0, base del auth)

### Migración `0002_catalog` — courses / course_offerings / scraper_runs

**courses** — agrupación estable (patrón MCC `0021_course_offerings`)
| columna | tipo | nota |
|---|---|---|
| id | uuid pk | |
| course_code | text unique | código nacional (HLTAID011…) o slug estable |
| title | text | |
| category | text null | una de las ~10 categorías del sitio |
| description | text null | |
| is_accredited | bool | derivado del código (patrón `^[A-Z]{3,6}\d{3,5}`) |
| source_url | text null | página de detalle |
| is_active | bool | false = desapareció del sitio (soft delete vía sync) |
| created_at / updated_at | timestamptz | |

**course_offerings** — una fila por instancia agendada
| columna | tipo |
|---|---|
| id uuid pk · course_id fk → courses · offering_code text unique (aXcelerate instance id) |
| price numeric null · gst text null · status text (`active`/`cancelled`) |
| places_available int null · places_text text |
| location text null · start_date date null · finish_date date null · time_text text null |
| session_count int null · session_hours numeric null |
| enrollment_url text null · detail_url text null |
| is_active bool · created_at / updated_at |

**scraper_runs** — ciclo de vida del sync HITL
`id, status enum(running|pending|approved|rejected|failed), courses_found int,
offerings_found int, changeset jsonb (staged diff), error text null,
started_at, finished_at, reviewed_by fk null → users, reviewed_at, created_at`

**users** — login básico (patrón MCC simplificado; ver §4a y D2)
`id uuid pk, email text unique, password_hash text (argon2), display_name
text, is_active bool, created_at`

**audit_logs** — `id, user_id fk null → users, action, entity_type, entity_id,
payload_diff jsonb, created_at`

### Migración `0003_content_items`

**content_items** — el historial pedido en el requisito 3
| columna | tipo | nota |
|---|---|---|
| id | uuid pk | |
| platform | enum(`facebook`,`instagram`,`linkedin`) | |
| topic | text null | entrada libre |
| reference_url | text null | |
| notes | text null | |
| course_id | uuid fk null → courses | grounding en curso real |
| generation_group | uuid null | enlaza las 3 variantes de una solicitud |
| variant_style | text | `direct` / `story_led` / `question_led` |
| generated_body | text | |
| edited_body | text null | |
| hashtags | jsonb | |
| call_to_action | text null | |
| status | enum(`draft`,`pending_approval`,`approved`,`rejected`,`archived`) | |
| ai_metadata | jsonb | modelo, mock, contexto, tone aplicado, timestamps |
| created_by | uuid fk null → users | |
| reviewed_by / reviewed_at | uuid fk null / timestamptz null | |
| created_at / updated_at | timestamptz | índices por (platform,status,created_at) |

Regla de validación (Pydantic): la solicitud debe traer `topic` **o**
`course_id` (grounding obligatorio, igual que el `_require_target` de MCC).

---

## 4a. Login básico

Patrón de MCC simplificado (misma stack: `argon2-cffi` + `pyjwt`):

- **Backend** (`app/auth/`): verificación argon2, JWT firmado
  (`AUTH_SECRET`, expiración configurable) emitido en **cookie httpOnly
  SameSite=Lax** por `POST /api/auth/login`; `POST /api/auth/logout` la
  limpia; `GET /api/auth/me` devuelve el usuario actual. Dependencia
  `get_current_user` protege **todas** las rutas de API salvo
  `/api/health` y `/api/auth/login`. Comparación en tiempo constante /
  respuesta uniforme para credenciales inválidas (patrón login-timing de MCC).
- **Usuarios**: sin registro self-service — un usuario admin se crea por seed
  (`ADMIN_EMAIL` / `ADMIN_PASSWORD` desde env, nunca hardcodeado; el seed
  falla si faltan).
- **Frontend**: página `/login` + `middleware.ts` de Next que redirige a
  `/login` cuando no hay cookie de sesión (igual que MCC); `lib/auth.ts`
  con `me/login/logout`.
- **Actor en workflow**: `created_by`/`reviewed_by` en `content_items`,
  `reviewed_by` en `scraper_runs` y `user_id` en `audit_logs` referencian a
  `users`, igual que el patrón MCC.

---

## 5. Flujo de generación

```
POST /api/content/generate
  { topic?, reference_url?, notes?, course_id?, platforms: ["linkedin", ...] }
        │
        ▼
ContentGenerationService.generate_variants()
  1. course = repo.get(course_id)  → facts reales (título, código, precio,
     próximas 3 ofertas con fecha/lugar/cupos, categoría, descripción)
  2. reference_url → fetch (httpx, mismo fetcher polite) + extracción de texto
     (BS4) truncado, inyectado al contexto. Fallo de fetch = warning, nunca
     bloquea (best-effort, patrón insights de MCC)
  3. por cada plataforma × 3 estilos (direct / story_led / question_led):
     build_generation_context() → llm.generate_social_post() → draft
  4. ranking determinista por violaciones del baseline de reglas
     (validate_generated_content: longitud por plataforma, hashtags, CTA)
  5. persistir 3 content_items por plataforma con generation_group común,
     status=draft, audit row
```

### Adaptación por plataforma — `PLATFORM_PROFILES`

Constante en `agents/content_generator.py`, inyectada al prompt (equivale al
rol que en MCC cumplía brand-voice + platform):

| | LinkedIn | Facebook | Instagram |
|---|---|---|---|
| tono | profesional, orientado a desarrollo laboral/empleadores | conversacional, comunidad | visual, energético, emoji-friendly |
| longitud objetivo | 600–1300 chars | 250–600 chars | 125–400 chars |
| hashtags | 3–5 sobrios | 2–5 | 8–15 |
| CTA | "Enrol / upskill your team" con URL | "Book your spot" | "Link in bio / enrol now" |
| estructura | hook + valor + credencial (código acreditado) + CTA | hook + beneficio + fecha/lugar + CTA | hook corto + emoji + CTA + wall de hashtags |

`MockLLMClient` genera cuerpos deterministas que respetan el perfil (permite
tests y demo offline); `GeminiLLMClient` renderiza el mismo contexto como
prompt.

### Workflow HITL sobre el item (patrón `ContentWorkflowService`)

`submit → pending_approval`, `approve`, `reject(reason)`, `edit(body)`
(vuelve a draft), `archive/restore`, `duplicate`, `regenerate(instruction?)`.
Todo transiciona vía `assert_transition` y escribe `audit_logs`.

---

## 6. Scraper WRCC (hallazgos verificados del sitio)

- WordPress server-rendered; datos de cursos servidos por **aXcelerate**.
- ~10 páginas de categoría (`/first-aid/`, `/plant-and-equipment/`, …) con
  cards que enlazan a `/course-details/?course_id=<id>&course_type=w`.
- La página de detalle es HTML server-rendered con: nombre+código, descripción,
  precio (`$185`), y **tabla de ofertas agendadas** (fecha, horario, sede —
  Griffith/Leeton/Deniliquin…, cupos "N spaces") con botón Apply →
  `/course-enrol?...instance_id`.

**Pipeline (espejo de MCC):**
1. `discovery.py` — `CATEGORY_SEEDS` (los 10 slugs, verificados y guardados
   como snapshot; drift = warning no fatal) → extrae los links
   `course-details/?course_id=…` de cada categoría.
2. `parser.py` — parsea la página de detalle → `ScrapedOffering` por fila de la
   tabla de fechas (offering_code = instance id del Apply link; cursos
   online-only sin fechas → 1 offering sintética `on-demand`).
3. `normalize.py` — dedup por offering_code, agrupa por código/título →
   `ScrapedCourseGroup`, deriva `is_accredited`.
4. `diff.py` — changeset vs filas vivas: `courses_added/updated/removed`,
   `offerings_added/updated/removed` (removed = desactivar, no borrar).
5. `service.py` — `POST /api/courses/sync` abre run `running`, despacha crawl a
   background (mismo patrón de `_background_tasks` + retries +
   zero-offerings=failure), stagea el changeset como `pending`.
6. **Aprobación humana**: `POST /api/courses/sync/{run_id}/approve|reject` —
   solo approve escribe el catálogo vivo (`apply_changeset`), todo auditado.

Fixtures: se guardan 2 páginas de categoría + 2 de detalle reales como HTML en
`tests/fixtures/wrcc/` para tests de parser/discovery sin red.

---

## 7. API

Todas las rutas requieren sesión salvo `/api/health` y `/api/auth/login`.

| Método/Ruta | Descripción |
|---|---|
| `POST /api/auth/login` · `POST /api/auth/logout` · `GET /api/auth/me` | login básico (§4a) |
| `POST /api/content/generate` | 3 ideas × plataforma(s) → items draft |
| `GET /api/content?platform=&status=&course_id=` | historial con filtros |
| `GET /api/content/{id}` | detalle |
| `POST /api/content/{id}/submit\|approve\|reject\|archive\|restore\|duplicate\|regenerate` | workflow |
| `PUT /api/content/{id}` | editar body |
| `GET /api/courses?category=&search=&accredited=` | catálogo (para el picker) |
| `GET /api/courses/{id}` | curso + ofertas |
| `POST /api/courses/sync` · `GET /api/courses/sync/{run_id}` · `POST .../approve` · `POST .../reject` | sync HITL |
| `GET /api/health` | |

## 8. Frontend (4 páginas)

0. **Login** — form email/contraseña; `middleware.ts` redirige aquí sin
   sesión; el resto de páginas muestran el usuario y un logout.
1. **Generate** — form: picker de curso (búsqueda sobre `/api/courses`) *o*
   topic + reference URL + notas; checkboxes de plataformas; muestra las 3
   variantes por plataforma en cards A/B/C con acciones rápidas.
2. **History** — tabla con filtros (plataforma, estado, curso), detalle
   expandible, acciones del workflow, "duplicate" para reutilizar.
3. **Catalog** — lista de cursos/ofertas, botón "Run sync", panel del run
   pendiente con resumen del changeset y Approve/Reject.

---

## 9. Decisiones (con recomendación)

- **D1 — Entrada por topic/reference_url**: el feature MCC actual se apoya en
  `campaign_id`/`course_id` (no tiene topic/URL libres). Se **generaliza**: el
  request acepta `topic + reference_url + notes` y/o `course_id`, con al menos
  uno obligatorio. *(Es la única desviación funcional del patrón; el resto es
  espejo.)*
- **D2 — Login básico** (pedido explícitamente): argon2 + JWT en cookie
  httpOnly, usuario admin seeded desde env, `get_current_user` protegiendo
  toda la API, página `/login` + middleware en el frontend (§4a). Sin roles,
  registro ni password-reset — extensiones futuras.
- **D3 — Mock-first**: `LLM_MOCK=true` y scraper contra fixtures por defecto;
  `GEMINI_API_KEY` + `LLM_MOCK=false` activa el modelo real. Ningún secreto
  hardcodeado.
- **D4 — Sin brand-voice table**: los perfiles por plataforma son constantes
  versionadas en código (`PLATFORM_PROFILES`); una tabla editable es extensión
  futura.

## 10. Tareas

**Fase 0 — Esqueleto + auth** 
- [ ] Estructura de carpetas, `pyproject.toml`, `config.py`, `main.py` +
      `create_app()`, `db/base.py`, `alembic.ini` + env, `GET /api/health`.
- [ ] Migración `0001_initial` (users + audit_logs) + `app/auth/` (argon2 +
      JWT cookie, `get_current_user`, router login/logout/me) + seed de admin
      desde env — tests de login OK/KO y de ruta protegida sin sesión.
- [ ] Frontend scaffold Next 14 + `lib/api.ts` + `lib/auth.ts` + layout +
      página `/login` + `middleware.ts`.

**Fase 1 — Scraper + catálogo** *(TDD: fixtures primero)*
- [ ] Capturar fixtures HTML reales de WRCC (2 categorías + 2 detalles).
- [ ] `db/models.py` (courses, course_offerings, scraper_runs) + migración
      `0002_catalog`.
- [ ] `scraper/types.py`, `fetcher.py` (httpx polite), `discovery.py`,
      `parser.py`, `normalize.py` — tests contra fixtures.
- [ ] `diff.py` + `repository.py` (stage/apply changeset) + `service.py`
      (run lifecycle background) + `services/courses.py` + router — tests de
      integración del flujo sync→pending→approve.

**Fase 2 — Generación + historial**
- [ ] Migración `0003_content_items` + enums + modelo.
- [ ] `llm/client.py` (Base/Mock/Gemini, prompt por plataforma) +
      `agents/content_generator.py` (`PLATFORM_PROFILES`, 3 variant styles) +
      `agents/validation.py` — tests unitarios (mock determinista).
- [ ] `content/service.py` (generate_variants con course grounding +
      reference_url fetch best-effort, workflow completo) + repository +
      schemas + state + router — tests de servicio e integración.

**Fase 3 — Frontend**
- [ ] Página Generate (picker de curso + topic/URL/notas + plataformas +
      variantes A/B/C).
- [ ] Página History (filtros + workflow actions).
- [ ] Página Catalog (sync + approve/reject changeset).
- [ ] Tests vitest de componentes clave + smoke E2E Playwright.

**Fase 4 — Cierre**
- [ ] README (setup, env vars, comandos), `.env.example`, seed de demo.
- [ ] ruff + mypy + `tsc --noEmit` limpios; cobertura backend ≥80% en módulos
      nuevos; git init + commits convencionales por fase.

## 11. Riesgos

- **Estructura del sitio WRCC**: el parser se fija a los fixtures capturados;
  drift del DOM → warnings + run failed con alerta, nunca datos corruptos
  (mismo contrato que MCC).
- **Politeness**: delay configurable entre requests + retries acotados; el
  crawl corre en background para no exceder timeouts de request.
- **Reference URL hostil/caída**: fetch best-effort con timeout corto; nunca
  bloquea la generación.
