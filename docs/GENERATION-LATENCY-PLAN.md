# Tiempo de generación — Plan de implementación (opción A)

Arregla el **502 en producción al generar posts** acotando y reduciendo el
tiempo de cada generación. Sin cambio de esquema, sin cambio de API pública y
sin tocar el frontend.

---

## 1. Diagnóstico (medido, 2026-09-11)

LiteSpeed (FastComet) corta toda petición a **~120 s** y mata el proceso: el
navegador recibe un 502. Hoy una generación hace **3 llamadas al LLM por
plataforma, una detrás de otra** (`agents/content_generator.py:112`,
`content/service.py:134`), con `gpt-5-mini` en esfuerzo de razonamiento
`medium` (el valor por defecto, porque no se pasa ninguno), **sin timeout**
(`AsyncOpenAI` espera 600 s por defecto) y con **reintentos duplicados**
(2 del SDK × 3 nuestros).

Benchmark con los prompts reales de la app (43 llamadas, <USD 0,20):

| Configuración | Por llamada | 3 plataformas × 3 variantes |
|---|---|---|
| Hoy: `medium`, en serie | ~23 s (con curso ~45 s) | ~200 s → 502 |
| `low` | ~6,7 s | **10,2 s en paralelo** (medido) |
| `minimal` | ~3,3 s | ~5 s (estimado) |

Calidad: `low` queda muy cerca de `medium` y usa bien los datos del curso;
`minimal` inventó un "WRCC Griffith campus" cuando no había curso, porque el
perfil de Facebook pide "fecha/lugar" aunque no existan (ver D7).

**Objetivo:** 3 plataformas en **<20 s típicos**, **nunca >95 s**, **nunca
un 502**: si algo sale mal, un 503 con un mensaje que la persona entiende.

---

## 2. Decisiones

| # | Decisión | Por qué |
|---|---|---|
| D1 | `OPENAI_REASONING_EFFORT=low` por defecto, configurable desde cPanel. Solo se envía a modelos de razonamiento (`gpt-5*`, `o1`/`o3`/`o4`); vacío = no se envía | Es la palanca grande (23 s → 7 s). El filtro por modelo evita un 400 si alguien cambia `OPENAI_MODEL` a `gpt-4.1-mini` |
| D2 | Las 9 llamadas en paralelo (`asyncio.gather`) con un semáforo `LLM_MAX_CONCURRENCY=9` | Tiempo total ≈ la llamada más lenta. El semáforo es la válvula por si la cuenta de OpenAI limita concurrencia |
| D3 | Timeout por llamada `LLM_TIMEOUT_SECONDS=40`, `max_retries=0` en el SDK y `LLM_MAX_ATTEMPTS=2` en nuestro envoltorio | Un solo nivel de reintentos. Peor caso por variante: 40 + 0,5 + 40 ≈ 81 s |
| D4 | Tope global `GENERATION_DEADLINE_SECONDS=95` (`asyncio.timeout`) | Siempre por debajo de los 120 s de LiteSpeed: respondemos nosotros, no el proxy |
| D5 | `LLMError` y el tope vencido → **503** con `detail` legible (el frontend ya lo muestra tal cual vía `errorMessage`) | Hoy un fallo de la IA es un 500 sin mensaje y un tiempo excedido es un 502 opaco |
| D6 | Todo o nada: si una variante falla tras sus intentos, no se guarda ninguna | Como hoy. Guardar generaciones parciales complicaría la UI y el ranking por un caso raro |
| D7 | Prompt sin curso: estructura sin "fecha/lugar" ni "código acreditado", y la regla final dice "no hay datos de curso: no menciones precios, fechas, lugares, códigos ni acreditaciones que no estén en el topic, las notas o la referencia" | Hoy pide datos que no existen y a la vez prohíbe inventarlos. El modelo los rellena |
| D8 | Los mismos límites (timeout, un nivel de reintentos) para Gemini y para imágenes (`IMAGE_TIMEOUT_SECONDS=100`, 1 intento) | Mismo riesgo: sin timeout, una imagen lenta también acaba en 502 |
| D9 | Una línea de log `INFO` por generación: plataformas, llamadas, segundos, modelo y esfuerzo | Para confirmar en `stderr.log` de cPanel que el cambio funciona y detectar regresiones |

**Fuera de alcance:** generar en segundo plano (job + polling), 3 variantes en
una sola llamada (opción C) y streaming. Ninguna hace falta con ~10 s.

---

## 3. Fases

Cada fase en TDD (test en rojo → implementación → verde) y con su commit.

### Fase 0 — Baseline de tests independiente del `.env` (15 min)

`app/main.py:98` crea la app al importar y lee `backend/.env`; como ese archivo
tiene ahora `APP_ENV=production`, la suite **no arranca** (hoy pasa 525/525
solo forzando `APP_ENV=local`).

- `tests/conftest.py`: fijar `os.environ["APP_ENV"] = "local"` **antes** de
  importar `app.main` (con un comentario del porqué).
- Verificar: `pytest` en verde sin variables extra.

### Fase 1 — Configuración (30 min)

`app/config.py` + `.env.example` + `tests/test_config.py`:

| Variable | Default | Validación |
|---|---|---|
| `OPENAI_REASONING_EFFORT` | `low` | `""`, `minimal`, `low`, `medium`, `high` |
| `LLM_TIMEOUT_SECONDS` | `40` | > 0 |
| `LLM_MAX_ATTEMPTS` | `2` | 1–3 |
| `LLM_MAX_CONCURRENCY` | `9` | 1–20 |
| `GENERATION_DEADLINE_SECONDS` | `95` | > 0 y < 115 (margen frente a LiteSpeed) |
| `IMAGE_TIMEOUT_SECONDS` | `100` | > 0 y < 115 |

Tests: defaults, valores inválidos rechazados, el deadline no puede superar el
límite del proxy.

### Fase 2 — Clientes con límites (1 h)

`app/llm/client.py`, `app/llm/images.py`, `tests/test_llm_client.py`:

- `OpenAILLMClient`: `AsyncOpenAI(timeout=…, max_retries=0)`; `reasoning_effort`
  solo si hay valor y el modelo es de razonamiento (`_supports_reasoning(model)`).
  Aplica a `generate_social_post` y a `suggest_image_prompts`.
- `generate_with_retries(label, attempt_once, attempts=…)`: los intentos pasan a
  ser un parámetro (hoy es la constante fija de 3).
- `GeminiLLMClient`: `http_options` con timeout en ms, mismos intentos.
- `OpenAIImageClient`: `timeout=IMAGE_TIMEOUT_SECONDS`, `max_retries=0`, 1 intento.
- Tests con un `AsyncOpenAI` falso que captura los kwargs:
  - `gpt-5-mini` recibe `reasoning_effort="low"`;
  - `gpt-4.1-mini` no lo recibe;
  - con valor vacío no se envía;
  - timeout y `max_retries=0` configurados;
  - los intentos respetan `LLM_MAX_ATTEMPTS`.

### Fase 3 — Generación en paralelo con tope (1,5 h)

`app/agents/content_generator.py`, `app/content/service.py`,
`tests/test_content_agents.py`, `tests/test_content_api.py`:

- `run_content_generator_variants`: las variantes con `asyncio.gather`, mismo
  orden y mismo ranking que hoy.
- `ContentGenerationService.generate`: todas las plataformas a la vez, con el
  semáforo (D2) y `asyncio.timeout(GENERATION_DEADLINE_SECONDS)` (D4). Las
  llamadas no tocan la sesión de base de datos: los `ContentItem` se crean
  **después** del `gather`, así que cancelar por el tope no deja nada a medias.
- Excepción `GenerationTimeoutError`; `regenerate` pasa por el mismo tope.
- Log de D9.
- Tests con un LLM falso lento (`asyncio.sleep(0.2)` por llamada):
  - 3 plataformas tardan ≈ 0,2 s y no 1,8 s;
  - los ítems salen en el mismo orden y con el mismo ranking;
  - con `GENERATION_DEADLINE_SECONDS=0.1` → 503 y **ningún** ítem en la base;
  - con `LLM_MAX_CONCURRENCY=1` vuelve a ser en serie (el semáforo funciona).

### Fase 4 — Prompt sin curso (45 min)

`app/agents/content_generator.py` (perfiles), `app/llm/client.py`
(`_render_prompt`), `tests/test_content_agents.py`:

- Cada perfil gana `structure_without_course`: Facebook `hook + benefit + CTA`,
  LinkedIn `hook + value + CTA`; Instagram no cambia.
- `_render_prompt` elige la estructura y la regla final según haya curso (D7).
- Tests:
  - sin curso, el prompt no menciona "date/location" ni "only use the course
    data provided" y sí la regla nueva;
  - con curso, el prompt no cambia respecto de hoy;
  - `MockLLMClient` sigue igual.

### Fase 5 — Errores legibles (30 min)

`app/api/content.py`, `app/api/images.py`, tests de API:

- `LLMError` → 503: *"The AI could not write the posts right now. Please try
  again in a minute."*
- `GenerationTimeoutError` → 503: *"The AI took too long to answer. Try again,
  or generate for fewer platforms."*
- El mismo mapeo en regenerar y en sugerencias de imagen.
- Tests: ambos casos devuelven 503 con ese `detail`.

### Fase 6 — Verificación y despliegue (1 h)

1. `ruff`, `mypy`, `pytest` completos en verde.
2. Prueba real en local con el benchmark (`LLM_MOCK=false`): una generación de
   3 plataformas sin curso y otra con curso, midiendo el tiempo total.
   **Criterio: <20 s cada una.**
3. Despliegue en FastComet siguiendo `backend/deploy/fastcomet/README.md`:
   - subir los archivos cambiados de `app/`;
   - en cPanel → Setup Python App → Environment variables, añadir
     `OPENAI_REASONING_EFFORT=low` (el resto usa los defaults);
   - reiniciar la app.
4. Comprobación en producción:
   - generar para 3 plataformas sin curso y con curso;
   - ver en `stderr.log` la línea de tiempo de D9 y ningún
     `Killing runaway process`.

**Rollback sin redesplegar:** `OPENAI_REASONING_EFFORT=medium` en cPanel y
reiniciar. Vuelve la calidad de hoy y, gracias al paralelo, tarda ~45 s en vez
de ~200 s. Si hiciera falta volver del todo, se restauran los archivos
anteriores.

---

## 4. Archivos que se tocan

| Archivo | Cambio |
|---|---|
| `backend/tests/conftest.py` | `APP_ENV=local` antes de importar la app |
| `backend/app/config.py`, `backend/.env.example` | 6 variables nuevas |
| `backend/app/llm/client.py` | timeouts, reintentos, `reasoning_effort`, prompt sin curso |
| `backend/app/llm/images.py` | timeout e intentos de imágenes |
| `backend/app/agents/content_generator.py` | variantes en paralelo, perfiles sin curso |
| `backend/app/content/service.py` | plataformas en paralelo, semáforo, tope, log |
| `backend/app/api/content.py`, `backend/app/api/images.py` | 503 legibles |
| `backend/tests/…` | tests de las fases 0–5 |

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| OpenAI limita la concurrencia de la cuenta (429) | En el benchmark, 9 llamadas a la vez dieron 0 errores. Si aparece, `LLM_MAX_CONCURRENCY` baja sin desplegar |
| `low` rinde peor en algún caso real | Se ajusta con `OPENAI_REASONING_EFFORT` desde cPanel. D7 reduce las invenciones en cualquier nivel |
| Cancelar por el tope deja trabajo a medias | Nada se escribe en la base hasta que terminan todas las llamadas |
| Coste | Baja: con `low` se generan ~4 veces menos tokens de salida por post que con `medium` |

## 6. Registro de ejecución (2026-09-11)

Rama `fix/generation-latency`, un commit por fase:

| Fase | Commit | Resultado |
|---|---|---|
| 0 | `3ede0e8` | La suite ya no depende del `.env` local: 525/525 sin variables extra |
| 1 | `14f54c4` | 6 ajustes nuevos con validación (deadline < 115 s) |
| 2 | `b73fcc5` | Timeouts, un solo nivel de reintentos, `reasoning_effort` solo para modelos de razonamiento, imágenes con 1 intento |
| 3 | `1230cbd` | Plataformas y variantes en paralelo (`TaskGroup`), semáforo, tope global, nada se guarda si se corta, log por generación |
| 4 | `71829fe` | Prompt sin curso: sin fecha/lugar ni código acreditado |
| 5 | `ac19c4b` | 503 legibles; las imágenes ya no responden 502 |

**Verificación:**
- Backend: **567 tests** en verde (525 + 42 nuevos); `ruff` y `mypy` limpios (67 archivos).
- E2E contra la **API real de OpenAI** (app completa por HTTP, base de datos en
  memoria, nada publicado):

  | Caso | Antes (estimado: llamada medida × 9, en serie) | Ahora (medido) |
  |---|---|---|
  | Topic libre, 3 plataformas | ~200 s → 502 | **13,2 s** |
  | Con curso, 3 plataformas | ~400 s → 502 | **18,0 s** |
  | Regenerar un post | ~23 s (1 llamada) | 7,1 s |
  | Sugerencias de imagen | ~23 s (1 llamada) | 12,0 s |

  18 posts completos (3 por plataforma), 1 sola infracción de regla en 18,
  sin datos de curso en el contexto del topic libre y con la línea de log.
- Frontend: suite Playwright completa (smoke, regresión visual, axe) + un test
  nuevo que comprueba que el mensaje del 503 llega a la pantalla y el
  formulario queda usable.

**Pendiente:** desplegar en FastComet (paso 3 de la fase 6) y comprobarlo en
producción. Requiere acceso a cPanel.

## 7. Estimación

~5 h en total. Ninguna fase depende de un servicio externo excepto la
verificación real de la fase 6.
