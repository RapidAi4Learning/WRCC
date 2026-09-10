# WRCC Social Media Marketing — Plan de rediseño de UI

Rediseño completo del frontend hacia el estilo del mockup de marca WRCC
(`133d8242-….png`: header blanco con logo + regla lima, títulos en morado
profundo, fondo lavanda con pétalos, CTA lima, inputs con icono, chips de
plataforma con logo real, empty state ilustrado).

**Regla de orden:** primero se **unifican** los componentes (Fase 1, sin cambio
visual), después se **reviste** (Fases 2–5). Así el cambio de estilo se hace
una vez, en los primitivos, y no en 14 módulos CSS por separado.

---

## 0. Diagnóstico — qué está duplicado hoy

Inventario del frontend actual (≈ 3 000 líneas de CSS en 14 módulos). Los tests
consultan por **rol y nombre accesible**, nunca por clase, así que reorganizar
CSS/markup es seguro mientras se conserven roles, labels y textos.

| # | Patrón | Dónde se repite hoy | Primitivo destino |
|---|---|---|---|
| D1 | Botón primario (accent + blanco, hover strong, disabled) | `generate .submit`, `catalog .syncButton`, `settings .primaryButton`, `VariantCard .primary`, `MediaPanel .primary`, `PublishDialog .publish`, `SyncReview .approve`, `login .submit` | `<Button variant="primary">` |
| D2 | Botón secundario / outline | `settings .secondaryButton`, `PublishDialog .secondary`, `SyncReview .reject/.cancel`, `UserMenu .logout`, `CoursePicker .clear` | `<Button variant="secondary">` |
| D3 | Botón pequeño / ghost | `VariantCard .action/.copy`, `MediaPanel .small/.toggle`, `SyncReview .bulk` | `<Button variant="ghost" size="sm">` |
| D4 | Botón peligro / link | `SyncReview .confirmReject`, `settings .dangerButton/.linkButton`, `SyncReview .showAll` | `<Button variant="danger" \| "link">` |
| D5 | Botón icono / cerrar | `MediaPanel .iconButton/.close`, `PublishDialog .close` | `<IconButton label>` |
| D6 | Callouts error/aviso/info/hold | `.error` en 8 archivos, `.warning`, `.warnings`, `.notice` ×2, `.hold` ×3, `.ambiguous`, `.runningNote`, `SyncReview .warning` | `<Callout tone="danger\|warn\|info\|success\|neutral">` |
| D7 | Label + input/textarea/select | `generate`, `login`, `history .select`, `catalog .search`, `CoursePicker .input`, `MediaPanel .textarea`, `SyncReview .rejectInput`, `VariantCard .textarea` | `<Field>` + `<TextInput icon>` `<TextArea icon>` `<Select>` |
| D8 | Modal (portal + backdrop + scroll-lock + Esc + click-fuera + header título/hint/cerrar) | `MediaPanel` y `PublishDialog` (código casi idéntico) | `<Modal>` + `useBodyScrollLock` + `useEscapeKey` |
| D9 | Tabs / segmented / chips toggle | `generate .tab/.tabActive`, `MediaPanel .tabs` (segmented), `generate .platformOption` (checkbox chip) | `<Tabs variant="pills\|segmented">`, `<ToggleChip>` |
| D10 | Fila expandible en lista | `history .list/.row/.rowButton/.expanded` ≡ `catalog` (CSS idéntico + mismo patrón `expandedId`) | `<DisclosureList>` / `<DisclosureRow>` |
| D11 | Empty / loading | `generate .empty`, `history .empty`, `catalog .empty`, `settings .loading`, `MediaPanel .empty/.selectionEmpty/.skeleton`, `SyncReview .emptyNote` | `<EmptyState>`, `<Skeleton>` |
| D12 | Pills / badges | `Badges`, `catalog .accredited`, `settings .destination`, `PublishDialog .required`, `SyncReview .pill/.skipTag/.sectionCount`, `MediaPanel .badgeAi/.badgeUpload` | `<Badge tone>` (Platform/StatusBadge encima) |
| D13 | Badge de orden numérico | `MediaPanel .orderBadge/.pickBadge`, `PublishDialog .thumbOrder` | `<OrderBadge n>` |
| D14 | Miniatura seleccionable con orden y tope | `MediaPanel` grid ≡ `PublishDialog` thumbs (misma lógica toggle + máximo) | `<SelectableThumb>` + `toggleOrdered()` puro |
| D15 | Encabezado de página (h1 + lede + acciones) | `.page/.header/.title/.lede` idénticos en generate, history, catalog, settings | `<PageHeader title lede actions>` |
| D16 | Etiqueta de sección (mayúsculas pequeñas) | `generate .legend`, `MediaPanel .sectionTitle`, `PublishDialog .sectionTitle`, `PostPreview .chromeLabel` | `<SectionLabel step?>` |
| D17 | Superficie tarjeta | form de generate, `VariantCard`, cards de settings, `SyncReview .panel`, login card | `<Card variant="raised\|outline\|dashed">` |
| D18 | `errorMessage(err, fallback)` | copiado en settings, MediaPanel, PublishDialog; inline en generate, history, catalog, login, VariantCard | `lib/errors.ts` |
| D19 | Etiquetas de plataforma/estado | `Badges` (`PLATFORM_LABELS`, `STATUS_LABELS`), `history` (`PLATFORM_OPTIONS`, `STATUS_OPTIONS`), `settings` (`PLATFORMS`), `generate` (`ALL_PLATFORMS`) | `lib/platforms.ts` (fuente única) |
| D20 | Visually-hidden | `settings .srOnly`, `MediaPanel .fileInput` | utilidad global `.sr-only` / `<VisuallyHidden>` |
| D21 | Colores sueltos | `#fff`, `rgba(20,28,24,…)`, `rgba(0,0,0,…)` en 6 archivos | tokens `--color-on-accent`, `--color-overlay`, `--shadow-modal` |

---

## 1. Decisiones

| # | Decisión | Recomendación | Motivo |
|---|---|---|---|
| U1 | Estilos | Seguir con **CSS Modules + tokens** (sin Tailwind) | Ya es el stack; los primitivos consumen tokens, el reskin se hace cambiando tokens. |
| U2 | Iconos | **`lucide-react`** (ISC, tree-shakable) | El mockup usa iconos de línea (buscar, lápiz, link, documento, sparkles, chevron). Hoy se usan emojis. |
| U3 | Logos de red | SVG inline propios (`components/icons/PlatformIcon.tsx`, trazados de Simple Icons, CC0) | Los chips del mockup muestran el logo real de FB/IG/LinkedIn. |
| U4 | Tipografía | `next/font/google`: **Outfit** (títulos, 700–800) + **Figtree** (texto, 400–600) | Se acercan a la sans geométrica del mockup; `next/font` hace self-host, sin CLS ni requests a Google en runtime. Máximo 2 familias. |
| U5 | Logo WRCC y tagline "Skills for a Stronger Community" | **Assets oficiales en SVG/PNG entregados por el cliente**, en `frontend/public/brand/` | Son marca registrada del college; no se redibujan ni se imitan con una fuente script. |
| U6 | Paleta | Muestreada del mockup (abajo); **reemplazar por los hex del manual de marca** si existe | Evita que el morado/lima "casi" coincidan con el logo. |
| U7 | `window.prompt` / `window.confirm` | Sustituir por `<ConfirmDialog>` / `<PromptDialog>` sobre `<Modal>` (Fase 5) | Rompen el estilo y no se pueden tematizar. Cambia comportamiento → toca tests de Settings y VariantCard. |
| U8 | Organización de carpetas | `components/ui/` (primitivos), `components/layout/`, `components/content/`, `components/catalog/`, `hooks/` | Por feature, como pide la guía web; los primitivos quedan aislados y documentados. |
| U9 | Tema oscuro | **Fuera de alcance** | El mockup es claro; se deja el sistema de tokens preparado, sin diseñarlo. |

### Paleta objetivo

Base oficial tomada del CSS de https://wrcc.nsw.edu.au/ (Fase 0):
**morado `#582281`**, **morado-magenta `#781D7D`**, **lima `#aebd37`**. El
resto de la escala se deriva de esos tres.

```css
--brand-purple-900: #3a1656;  /* títulos "Generate content", texto sobre lima */
--brand-purple-700: #582281;  /* OFICIAL — nav, labels de sección, links */
--brand-magenta-700: #781d7d; /* OFICIAL — acentos secundarios */
--brand-purple-500: #8a62ad;  /* iconos, bordes activos suaves */
--brand-purple-100: #efe7f5;  /* avatar, hover suave */
--brand-lavender-50: #f8f5fb; /* fondo de página */
--brand-lime-500:   #aebd37;  /* OFICIAL — CTA, nav activo, regla del header */
--brand-lime-600:   #9aa92c;  /* hover del CTA */
--brand-lime-800:   #5c6614;  /* lima para TEXTO pequeño (contraste AA) */
--brand-lime-100:   #f2f5dc;  /* chip seleccionado */
--color-border:     #e3d8ec;
--color-border-dashed: #cfbadf;
--color-text:       #2a2233;
--color-text-muted: #6a6275;
```

### Assets de marca (estado tras Fase 0)

- **Logo**: `frontend/public/brand/wrcc-logo.png` (296×70), descargado del
  propio sitio del college. Suficiente en 1x; se sustituye por el SVG oficial
  cuando llegue.
- **Tagline "Skills for a Stronger Community"**: no está publicada como imagen
  en el sitio. El header deja su hueco preparado (`BrandTagline`) y **no lo
  muestra** hasta tener el asset oficial; no se imita con una fuente script.

Reglas de contraste que salen del mockup:
- **Texto sobre lima = morado 900**, nunca blanco (blanco sobre `#b8d430` no pasa AA).
- El lima como color de texto (el "1 ·" de las secciones) solo en tamaño grande/negrita; en texto pequeño usar `--brand-lime-800`.
- Los colores semánticos (danger/warn/success) se mantienen, reajustados para convivir con el morado.

---

## 2. Estructura destino

```
frontend/
├── styles/
│   ├── tokens.css        # paleta, tipo, espaciado, radios, sombras, z-index, --header-height
│   └── globals.css       # reset, base, .sr-only, fondo decorativo
├── public/brand/         # logo WRCC, tagline (assets del cliente)
├── components/
│   ├── ui/               # Button, IconButton, Field, TextInput, TextArea, Select,
│   │                     # Callout, Badge, OrderBadge, Card, Modal, ConfirmDialog,
│   │                     # Tabs, ToggleChip, EmptyState, Skeleton, SectionLabel,
│   │                     # PageHeader, DisclosureList, SelectableThumb, VisuallyHidden
│   ├── icons/            # PlatformIcon (FB/IG/LI), re-export de lucide usados
│   ├── layout/           # AppHeader, BrandLogo, NavLinks, UserMenu, PageBackground
│   ├── content/          # VariantCard, MediaPanel, PublishDialog, PostPreview, CoursePicker, Badges
│   └── catalog/          # SyncReviewPanel
├── hooks/                # useBodyScrollLock, useEscapeKey, useAsyncAction
└── lib/                  # errors.ts, platforms.ts, selection.ts (+ los existentes)
```

---

## 3. Fases

Cada fase termina con `npm run typecheck`, `npm test` y `npm run build` en verde
y es un commit (o varios) convencional. Ninguna fase toca el backend.

### Fase 0 — Red de seguridad (½ día)

1. Capturas Playwright **del estado actual** de login, generate (vacío y con
   resultados), history (fila expandida), catalog (con panel de review),
   settings, MediaPanel y PublishDialog abiertos, a 375 / 1024 / 1440 px.
   Quedan como referencia "antes" en `frontend/e2e/__screenshots__/baseline/`
   (no como test que falle: el diseño va a cambiar a propósito).
2. Ruta de desarrollo `/ui-kit` (en `(app)`, devuelve `notFound()` en
   producción) que renderiza cada primitivo en todos sus estados. Es el sitio de
   revisión visual de las Fases 1–2.
3. Confirmar U5/U6: pedir al cliente logo + tagline en SVG y los hex oficiales.

### Fase 1 — Unificación sin cambio visual (2–3 días)

**Invariante:** la app se ve igual que antes. Los tests existentes pasan
**sin cambiar sus aserciones** (solo rutas de import si un archivo se mueve).

**1a. Utilidades puras** (TDD, cada una con test propio)
- `lib/errors.ts` → `errorMessage(err, fallback)`; reemplaza D18.
- `lib/platforms.ts` → `PLATFORMS` ordenado, `PLATFORM_LABELS`,
  `STATUS_LABELS`, opciones de filtro; reemplaza D19.
- `lib/selection.ts` → `toggleOrdered(list, id, max)` y `move(list, i, delta)`;
  lo usan MediaPanel y PublishDialog (D14).
- `hooks/useBodyScrollLock`, `hooks/useEscapeKey` (D8).
- `hooks/useAsyncAction` → `{ run, isBusy, error }`; solo se adopta donde
  quite código de verdad (catalog `withBusy`, settings `busy`, VariantCard
  `runAction`).

**1b. Primitivos en `components/ui/`**, con los tokens **actuales**:
`Button`/`IconButton` (D1–D5), `Callout` (D6), `Field`/`TextInput`/`TextArea`/
`Select` (D7), `Modal` (D8), `Tabs`/`ToggleChip` (D9), `DisclosureList` (D10),
`EmptyState`/`Skeleton` (D11), `Badge`/`OrderBadge` (D12–D13),
`SelectableThumb` (D14), `PageHeader` (D15), `SectionLabel` (D16), `Card` (D17),
`VisuallyHidden` (D20). Tokens nuevos para D21.

Reglas de API:
- Los primitivos **no** deciden semántica: `Callout` recibe `role` explícito, así
  cada sitio conserva el `role="alert"`/`"status"` (o ninguno) que tiene hoy.
- `Button` reenvía `ref` y todos los atributos nativos; `loading` deshabilita
  y cambia el texto, sin cambiar el nombre accesible cuando no toca.
- `Modal` añade **focus trap y foco inicial** (hoy no existen). Es la única
  mejora de comportamiento de la fase, con tests propios (Esc, click fuera,
  Tab cicla dentro, foco vuelve al disparador al cerrar).
- Tests unitarios de cada primitivo (variantes, disabled, roles, teclado).

**1c. Migración pantalla por pantalla** (un commit por bloque):
login → PageHeader en las 4 páginas → generate → history + catalog
(DisclosureList) → settings → VariantCard → CoursePicker → MediaPanel +
PublishDialog (Modal, SelectableThumb, selection.ts) → SyncReviewPanel →
AppShell (NavLinks, UserMenu).

**1d. Limpieza:** borrar las clases que quedaron muertas y mover los
componentes a sus carpetas (U8). Métrica esperada: CSS de módulos de ≈ 3 000 a
≈ 1 500 líneas; cero `#fff`/`rgba` sueltos fuera de `tokens.css`.

**Salida:** capturas equivalentes a la baseline de Fase 0 (revisión a ojo) +
suite verde + `/ui-kit` completo.

### Fase 2 — Sistema de diseño de marca (1 día)

1. `styles/tokens.css` con la paleta de §1, escala tipográfica
   (`--text-display` más grande: el h1 del mockup ≈ 3rem), radios (inputs
   8px, cards 14px, botones 10px), sombras suaves con tinte morado,
   `--header-height`, z-index de modal.
2. `next/font` (U4) en `app/layout.tsx`, expuesto como `--font-display` /
   `--font-sans`.
3. Restyle de los **primitivos** al lenguaje del mockup:
   - `Button primary` = lima + texto morado 900 + sparkle opcional; `secondary`
     = borde lavanda; focus ring morado.
   - `TextInput`/`TextArea` con **icono a la izquierda**, borde lavanda, fondo
     casi blanco, focus morado.
   - `SectionLabel step` = "**1** · CREATE A POST" (número lima, texto morado,
     mayúsculas).
   - `ToggleChip` = chip con logo de red, seleccionado en lima-100 + borde lima.
   - `Card` blanca con borde lavanda y sombra suave; `dashed` para las zonas
     vacías.
   - `EmptyState` con ilustración (documento + sparkle + rayos lima) en SVG
     inline, título morado.
   - `Badge` de estado y plataforma re-tonalizados (el `published` sigue siendo
     más fuerte que `approved`, por el mismo motivo de hoy).
4. `PlatformIcon` (U3) y set de iconos lucide (U2).

**Salida:** `/ui-kit` se ve como el mockup; como el resto de la app ya usa
primitivos, **toda la app cambia de estilo a la vez**.

### Fase 3 — Shell y login (1 día)

- `AppHeader`: logo WRCC (asset) · separador vertical · "Social Media
  Marketing" en morado · nav con **pill lima en la ruta activa** · avatar con
  iniciales + chevron que abre un **menú** (email + Log out; hoy es un botón
  suelto) · tagline a la derecha (se oculta < 1200px).
- Regla lima de ~6px bajo el header; header sticky con `--header-height`
  (el `top: 4.5rem` hardcodeado del form de generate pasa a usar el token).
- `PageBackground`: pétalos lavanda/lima en SVG, `position: fixed`,
  `pointer-events: none`, detrás del contenido; se simplifican en móvil.
- Nav < 768px: menú hamburguesa con el mismo estilo.
- Login con el mismo lenguaje (logo, card, CTA lima). El h1 "Social Media
  Marketing" se mantiene: lo busca el smoke test e2e.

### Fase 4 — Pantalla Generate, fiel al mockup (1 día)

- Grid 2 columnas: card del form (≈ 30rem) + zona de resultados; el form
  sigue sticky.
- Secciones "1 · Create a post" y "2 · Platforms" con `SectionLabel`.
- Inputs con icono: búsqueda (CoursePicker), lápiz (topic), link (URL),
  documento (notes).
- Chips de plataforma con logo (`ToggleChip` + `PlatformIcon`), los tres en
  una fila.
- CTA full-width lima con sparkles: "Generate 3 ideas per platform".
- Empty state punteado con ilustración; estado "Generating…" con `Skeleton`
  de 3 tarjetas en vez de solo texto.
- Resultados: tabs de plataforma en estilo pill con logo + contador;
  `VariantCard` con el nuevo lenguaje (ver Fase 5).

### Fase 5 — Resto de pantallas y diálogos (2–3 días)

| Pantalla/componente | Cambios |
|---|---|
| `VariantCard` | Card blanca; header con estilo (A/B/C) + badges; acciones como botones ghost con icono; "Preview" como primario lima cuando está `approved`; Copy con icono y check. |
| History | Filtros con `Select` estilizado en la cabecera; filas `DisclosureList` con logo de red, fecha y badge; skeleton al cargar. |
| Catalog | "Run sync" primario; buscador con icono; filas con código en morado; tabla de fechas con cabecera en mayúsculas; `SyncReviewPanel` con la regla superior en morado→lima y tonos semánticos. |
| Settings | Cards por red con `PlatformIcon` grande y regla de color de la red; estado conectado con dot lima; botones unificados; **`ConfirmDialog`** para "Disconnect" (U7). |
| `MediaPanel` | `Modal` grande; tabs segmented con iconos lucide (se mantiene el texto "Generate with AI" / "Upload files": los tests lo buscan por regex); dropzone punteada lavanda; grid con `SelectableThumb`. |
| `PublishDialog` | `Modal` con la regla superior del color de la red (se conserva); footer como barra de confirmación; CTA lima. |
| `PostPreview` | **Se mantiene neutral**: imita la red, no la marca WRCC. Solo se tokenizan colores sueltos. |
| `VariantCard` reject/regenerate | `PromptDialog` en lugar de `window.prompt` (U7). |

Tests que cambian en esta fase (y solo en esta): `SettingsPage.test.tsx`
(`vi.spyOn(window, "confirm")` → interactuar con el diálogo) y
`VariantCard.test.tsx` (reject/regenerate vía diálogo).

### Fase 6 — QA y cierre (1 día)

- Responsive 320 / 375 / 768 / 1024 / 1440 / 1920, sin overflow horizontal.
- Accesibilidad: contraste AA (especialmente lima), foco visible en todo,
  navegación por teclado de tabs/modales/menú, `prefers-reduced-motion`.
- Capturas Playwright "después" de las mismas vistas de Fase 0; se adoptan
  como baseline de regresión visual desde aquí.
- Lighthouse en login y generate (CLS < 0.1 con las fuentes nuevas).
- Actualizar `docs/PLAN.md` (§ frontend) y enlazar este documento.

---

## 4. Riesgos

| Riesgo | Mitigación |
|---|---|
| Faltan los assets oficiales (logo, tagline, hex) | Fase 0 los pide; mientras tanto se usa un placeholder textual, **nunca** un logo redibujado. |
| Nombres accesibles cambian al quitar emojis ("✨ Generate with AI", "🖼 Media") | Los iconos van con `aria-hidden`; el texto visible se conserva; los tests buscan por regex. |
| Contraste del lima | Regla fija: texto sobre lima = morado 900; lima como texto solo en `--brand-lime-800`. |
| La Fase 1 se come el tiempo sin resultado visible | Es lo que hace que las Fases 2–5 cuesten poco; `/ui-kit` hace visible el avance. |
| Focus trap del `Modal` rompe algún test de MediaPanel/PublishDialog | Se introduce en 1b con tests propios, antes de migrar los diálogos. |
| Fondo decorativo afecta rendimiento o legibilidad | SVG estático, `position: fixed`, sin animación, opacidad baja; se quita en móvil si hace falta. |

## 5. Registro de ejecución

Rama: `feat/ui-redesign`. Un commit por fase.

**Fase 0 — hecha.** `e2e/visual.spec.ts` + `e2e/support/mockApi.ts` capturan
las 9 vistas a 375/1024/1440 contra una API simulada (sin backend). Se ejecuta
con `SHOTS_LABEL=<etiqueta> npx playwright test visual`; las capturas van a
`e2e/shots/<etiqueta>/`, **ignoradas por git** (son comparaciones locales, y la
baseline de regresión versionada llega en la Fase 6). La baseline ya mostró un
bug real: a 375px el header desborda la página hasta ~748px (se arregla en la
Fase 3).

**Fase 1 — hecha.** 160 tests previos pasan sin tocar una sola aserción; +30
tests nuevos (primitivos, Modal, utilidades). Desvíos respecto del plan:
- `useAsyncAction` **descartado**: los tres candidatos no comparten forma
  (Settings guarda *qué* cuenta está ocupada, VariantCard *qué* acción), así que
  el hook no quitaba código real.
- `Card` es la función `cardClass()` en vez de un componente: los sitios que la
  usan son `<form>`, `<article>` y `<section>`, y un componente polimórfico solo
  para eso no compensaba.
- `VisuallyHidden` es la utilidad global `.sr-only`.
- Los blancos translúcidos de `PostPreview` (flechas y puntos del carrusel de
  Instagram) siguen como literales a propósito: imitan la interfaz de la red,
  no la marca.
- `Modal` añade foco inicial, trampa de Tab, devolución del foco y cierre con
  Esc solo del diálogo superior (por profundidad de anidamiento).

Métrica: CSS de pantallas/componentes **2 885 → 1 470 líneas** (−49 %); con
las 793 líneas de los 16 primitivos, el total queda en 2 263 (−22 %). Único
literal de color fuera de `tokens.css`: el chrome de Instagram citado arriba.

**Fase 2 — hecha.** Tokens con los colores oficiales; el lima es el CTA
(siempre con texto morado 900), el morado es acento/foco/selección. Se añadió
un tono `success` propio: "approved" y las altas del catálogo se leen en verde
y "published" sigue siendo el badge más fuerte. Figtree + Outfit por
`next/font`; `lucide-react` 1.44.0 fijado; marcas de red de Simple Icons.

**Fase 3 — hecha.** `AppHeader` (logo oficial, divisor, nombre del producto,
nav con píldora lima y `aria-current`, avatar con menú de cuenta, regla lima),
menú plegable por debajo de 48rem —que corrige el desborde a 375px de la
baseline—, fondo de pétalos (`PageBackground`) y login con el mismo lenguaje.
La tagline sigue sin mostrarse: el hueco está marcado en `AppHeader`.

**Fase 4 — hecha.** Generate replica el mockup: card de composición de ~31rem,
inputs con icono (buscar, lápiz, enlace, documento), regla entre los dos
pasos, chips de plataforma con la marca real a tres columnas (`PlatformName`,
reutilizable en pestañas y tarjetas), CTA a todo el ancho con destellos,
estado vacío punteado con ilustración (`IdeasIllustration`) y, mientras se
genera, tres tarjetas esqueleto con un aviso `role="status"` para lectores de
pantalla. Bug encontrado y corregido de paso: el `matcher` del middleware
también redirigía `/brand/*` al login, así que el optimizador de imágenes
recibía HTML en vez del logo (en producción, el login se habría quedado sin
logo).

## 6. Estimación

| Fase | Días |
|---|---|
| 0 · Red de seguridad | 0.5 |
| 1 · Unificación | 2–3 |
| 2 · Design system | 1 |
| 3 · Shell + login | 1 |
| 4 · Generate | 1 |
| 5 · Resto | 2–3 |
| 6 · QA | 1 |
| **Total** | **8.5–10.5** |
