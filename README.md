# Thinkuy

**Radar de comunicación científica (producto de Tinkuy Lab).**

> Filosofía central: **«No busques el paper. Deja que el paper te encuentre.»**

Thinkuy no es otro Scholar: es el mapa de la **conversación en la que ya está tu campo**.
Cada alerta explica *por qué* aparece (cita el corpus de referencia, encaje con el CFP
vigente, o solapamiento con el campo). Widget embebible en OJS + PWA + extensión.

El motor es **agnóstico al campo de conocimiento**: cada disciplina se configura con
un perfil (`profiles/<campo>.json`) y su propia base de datos.

---

## Arquitectura del MVP

```
                    ┌────────────────────────────────────────────────────┐
                    │                    BACKEND  (FastAPI)              │
                    │                                                    │
   SciELO ─────────►│  harvester/     pipeline (cada 6 h, APScheduler)  │
   Crossref ───────►│  scielo.py      discovery de revistas SciELO      │
   OpenAlex ───────►│  crossref.py    cosecha por ISSN + ventana        │
    Redalyc ────────►│  openalex.py    lotes de ISSN, cursor, API key    │
                    │  redalyc.py     OAI-PMH (best effort)             │
                    │       │                                            │
                    │       ▼                                            │
                    │  SQLite (data/radar.db)  ──►  API REST /api/*     │
                    │  matching.py (keywords + porqué)                  │
                    │  citations.py (APA 7, BibTeX, RIS/Zotero)         │
                    └───────────────┬────────────────────────────────────┘
                                    │  localhost:8000
                    ┌───────────────▼────────────────────────────────────┐
                    │  PWA (pwa/)  instalable en cualquier dispositivo   │
                    │  Extensión (extension/) Chrome + Firefox (MV3)     │
                    └────────────────────────────────────────────────────┘
```

| Pieza | Ruta | Tecnología |
|---|---|---|
| Backend + API REST | `backend/radar/` | Python 3.10+ · FastAPI · APScheduler · httpx |
| Harvesters | `backend/radar/harvester/` | SciELO Article Meta API, Crossref REST, OpenAlex, Redalyc OAI-PMH |
| PWA | `pwa/` | HTML/CSS/JS vanilla · manifest + service worker |
| Extensión | `extension/` | Manifest V3 (Chrome + Firefox) |

## Inicio rápido

**Opción A — doble clic (Windows):** ejecuta `inicio.bat` (menú: arrancar, cosechar 30 días, o cosecha completa). Abre la PWA en `http://localhost:8000/app/`.

**Opción B — manual:**

```bash
# 1) Backend
cd backend
uv venv .venv
uv pip install --python .venv fastapi "uvicorn[standard]" apscheduler httpx

# 2) Primera cosecha (construye el catálogo; ventana de 1 año)
uv run python -m radar.harvester.cli --days 365 --max-articles 2500

# 3) API + PWA (escucha en IPv4 E IPv6, así 'localhost' funciona siempre)
uv run python run_server.py
#    → API:      http://localhost:8000/api/health
#    → PWA:      http://localhost:8000/app/
#    → Docs API: http://localhost:8000/docs
```

> **Nota localhost/IPv6:** en Windows, `localhost` puede resolverse a `::1` (IPv6).
> Por eso `run_server.py` lanza dos instancias de uvicorn en el puerto 8000
> (127.0.0.1 + ::1). No uses `--host ::` solo: en Windows no habilita IPv4.

> **Actualización automática cada 6 horas:** añade `RADAR_AUTO_HARVEST=1` al entorno
> (con `uv run` en Windows: `RADAR_AUTO_HARVEST=1 uv run uvicorn ...`). Alternativa:
> programar `python -m radar.harvester.cli --days 30` con el planificador del sistema.

### Instalar la PWA
Abre `http://127.0.0.1:8000/app/` en Chrome/Edge/Android y usa **"Instalar Radar"**
(o menú del navegador → Instalar aplicación). En iOS: Compartir → Añadir a pantalla de inicio.

### Cargar la extensión
- **Chrome/Edge:** `chrome://extensions` → modo desarrollador → *Cargar descomprimida* → carpeta `extension/`
- **Firefox:** `about:debugging#/runtime/this-firefox` → *Cargar complemento temporal* → `extension/manifest.json`
- Abre **⚙ Opciones** para apuntar la extensión a tu servidor si no es `localhost:8000`.

## API REST

| Endpoint | Descripción |
|---|---|
| `GET /api/widget?mode=conversation\|cfp\|latest&lang=es\|en&limit=5` | Payload compacto para el embed OJS (conversación con el corpus / CFP / recientes) |
| `GET /api/cfp` | CFPs vigentes y ejes editoriales del campo |
| `GET /api/feed?keywords=a,b&langs=es,pt&sources=scielo,crossref,openalex&limit=5&days=180&sort=relevance\|recent\|cited` | Feed personalizado; `sort=recent` (más recientes) o `cited` (más citados, vía Crossref/OpenAlex) |
| `GET /api/articles/{doi}` | Metadatos completos del artículo (JSON) |
| `GET /api/articles/{doi}/citation?format=apa\|bibtex\|ris` | Cita descargable |
| `GET /api/authors?sort=new\|emerging\|active&days=365` | Autores nuevos / emergentes (1ª publicación ≤ período y ≥ 2 artículos) / activos |
| `GET /api/watch` · `GET /api/watch/total` | Keywords ancladas y su conteo de publicaciones nuevas |
| `POST /api/watch` `{keywords, label?}` · `DELETE /api/watch/{id}` | Anclar / desanclar keywords para alertas pasivas |
| `GET /api/watch/{id}/new?mark=0\|1` | Nuevas publicaciones del ancla desde la última revisión (`mark=1` marca como visto) |
| `GET /api/stats` · `GET /api/sources` | Totales y estado de las fuentes |
| `GET /api/journals?q=` · `GET /api/suggest?q=` | Catálogo y autocompletado de keywords (FTS5) |
| `POST /api/harvest/run?days=90&sources=scielo,crossref` | Cosecha manual |

Ejemplo:

```bash
curl "http://127.0.0.1:8000/api/feed?keywords=desinformaci%C3%B3n,periodismo%20digital&limit=3&langs=es,pt"
```

## Transparencia bibliométrica

Cada artículo del feed devuelve `matched`, la lista de keywords del usuario que
dispararon la alerta y en qué campo aparecieron (título = 3 ptos, palabras clave =
2, resumen = 1). El score ordena el radar; la explicación se muestra siempre en la UI.

## Jerarquización y alertas ancladas

- **Orden del feed:** `relevance` (score + fecha), `recent` (más recientes) o
  `cited` (más citados). El conteo de citas lo aportan Crossref
  (`is-referenced-by-count`) y OpenAlex (`cited_by_count`) y aparece como badge
  en cada tarjeta.
- **Separadores de keywords:** las palabras clave se entienden separadas por coma
  `,`, punto y coma `;`, barra `|`, salto de línea **o guion con espacios**
  (`a - b` / `a – b`). El campo del radar acepta cualquiera de ellos.
- **Ventana por defecto:** 1 año. Si una búsqueda no da resultados en una ventana
  más corta, el feed devuelve `hints.wider_window` con cuántas coincidencias hay
  ampliando a 1 año, y la UI ofrece un botón para ampliarla.
- **Keywords ancladas:** el botón «📌 Anclar» guarda tus keywords y el radar solo
  cuenta **publicaciones nuevas desde entonces** (por id creciente, no por fecha
  de publicación: huye de falsos "nuevos"). Cada ancla muestra su conteo, permite
  «Ver nuevas» (marca como visto) y desanclar. Las notificaciones del navegador
  (PWA) y del sistema (extensión, cada 6 h) avisan cuando hay novedades.
- **Autores emergentes:** heurística sobre el catálogo — primera publicación en la
  ventana y ≥ 2 artículos. Frecuente en `GET /api/authors?sort=emerging`.

## Radar de Proximidad Epistemológica (Modelo Pajek)

Visualiza quién orbita una pregunta/tema o un artículo concreto (por DOI) y cómo se estructuran las redes de coautoría, citación y revista compartida en capas multiplex.

### Parámetros de Ajuste Algorítmico

Disponibles vía API (`GET /api/radar` y `POST /api/radar/discover`) y en la PWA (panel desplegable ⚙ **Ajustes Avanzados**):

| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `topic` | `string` | `""` | Pregunta o tema central libre para proyectar en el radar. |
| `doi` | `string` | `""` | DOI del artículo objetivo para situarlo en el centro. |
| `weights` | `string` | `"0.4,0.3,0.2,0.1"` | Pesos de proximidad: `afinidad,conexion,actualidad,productividad`. |
| `min_works` | `int` | `1` | Umbral mínimo de obras para incluir al autor en la proyección base. |
| `affinity_divisor` | `int` | `60` | Divisor de escala de afinidad temática (`min(1.0, max_affinity / C)`). |
| `productivity_constant` | `float` | `5.0` | Constante de saturación $C$ en la fórmula de productividad $n / (n + C)$. |
| `min_dist` | `float` | `11.0` | Distancia mínima de relajación force-directed entre nodos (evita solapamientos). |
| `recency_decay` | `string` | `"linear"` | Función de decaimiento temporal: `"linear"` o `"exponential"`. |
| `normalize_weights` | `bool` | `True` | Normaliza los pesos de cada capa multiplex (coautoría, citación, revista) al rango $[0, 1]$. |
| `excluded` | `string` | `""` | Claves, nombres u ORCIDs de autores a excluir (separados por coma). |
| `included` | `string` | `""` | Autores forzados a ingresar en la órbita (separados por coma). |

### Ejemplo de Consulta API

```bash
# GET con parámetros ajustados
curl "http://localhost:8000/api/radar?topic=desinformacion&affinity_divisor=50&recency_decay=exponential&normalize_weights=true"

# POST /api/radar/discover con parámetros de layout y recencia
curl -X POST "http://localhost:8000/api/radar/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "polarizacion politica",
    "days": 365,
    "affinity_divisor": 50,
    "recency_decay": "exponential",
    "normalize_weights": true
  }'
```

## Cobertura de revistas (meta: 300+)

- **Red semilla curada**: ~70 revistas iberoamericanas de Comunicación (`journals_seed.py`).
- **Auto-descubrimiento SciELO**: en cada cosecha se escanean 15 colecciones
  (BR, CL, CO, MX, AR, ES, PT, CU, PE, UY, VE, EC, BO, CR, PY) y se registran
  automáticamente todas las revistas cuya área temática/título corresponde a
  Comunicación — *la red crece sola*.
- **Crossref**: cosecha por ISSN (impreso + online) de todas las revistas del catálogo.
- **OpenAlex**: cosecha global por lotes de ISSN (OR por pipe), con paginación por cursor
  y polite pool (`mailto=`); cubre lagunas de depósito de Crossref (p. ej. Comunicar).
- **Latindex Catálogo 2.0**: descubre revistas del campo solo entre las calificadas
  (exportación nativa JSON de Iberoamérica, `exportar/indiceRegion/json/94/0/1`).
  Aporta ISSN para Crossref/OpenAlex y supera la meta de 300+ revistas.
- **Latindex Descubridor de Artículos**: cosecha artículos (título, autores, DOI,
  resumen, enlace OJS) publicados en revistas del Catálogo 2.0 — calidad contrastada
  (`Solr/Busqueda?idModBus=3`, paginado con `page-size=200`).
- **Calidad editorial (SJR)**: cada revista se clasifica Q1-Q4 desde el índice
  ScimagoJR local (`data/sjr/sjr.json`, construible con `python -m radar.quality
  --build-index scimagojr.csv`). El feed prioriza Q1/Q2 y baja en cascada a Q3/Q4
  solo si no hay resultados (param `quality_mode=auto|high|all`).
- **Fase 2**: dumps mensuales de Redalyc para ampliar cobertura.

## Criterios de éxito del MVP y cómo medirlos

| Criterio | Meta | Medición |
|---|---|---|
| Tiempo de carga del feed | < 2 s | DevTools/Network + `generated_at` en `/api/feed` |
| Actualización | ≤ 6 h | Scheduler APScheduler + alarm de la extensión (360 min) |
| Cobertura | 300 revistas | `GET /api/stats` → `journals` (crece con cada cosecha) |
| Instalación PWA | > 15 % | Evento `beforeinstallprompt` + analytics del semillero |
| Retención 30 días | > 40 % | Métrica externa (PWA/semillero) |

## Estado conocido de las fuentes (verificado en vivo, sept. 2026)

- **SciELO (Article Meta API)**: operativa y sin API key. `search.scielo.org` está
  tras un anti-bot (Bunny Shield), por eso se usa `articlemeta.scielo.org`.
- **Crossref**: operativa, polite pool con `mailto=`. Algunas revistas depositan con
  retraso (p. ej. Comunicar no registra DOIs recientes) — OpenAlex cubre ese vacío.
- **OpenAlex**: operativa. Desde feb-2026 el polite pool por `mailto=` fue sustituido
  por **API key con créditos**: sin key quedan ~100 créditos/día (luego HTTP 409).
  Define `THINKUY_OPENALEX_API_KEY` y todas las llamadas (harvester, live search,
  Editorial Radar, SCIVIS, tracker) se autentican con `Authorization: Bearer`.
  Abstracts vía `abstract_inverted_index`, keywords por ML.
- **Redalyc**: el OAI-PMH público devolvía 502/503 durante el desarrollo. El módulo
  reintenta y registra el estado; para cobertura completa se puede usar la API oficial
  (`api.redalyc.org`, token vía `REDALYC_TOKEN`) o el dump mensual de Zenodo.

## Auditoría SCIVIS y el WebGraph de Common Crawl

La auditoría (`GET /api/scivis/audit`) usa **exclusivamente datos reales**, nunca simulados:

- **Centralidad Armónica y PageRank**: rankings oficiales del release indexado
  (`tools/download_cc_ranks.py` + `tools/index_cc_ranks.py` → `THINKUY_CC_RANKS_DB`).
  El percentil se calcula sobre el total real de dominios del release (tabla `cc_index_meta`).
- **Capturas en vivo**: verificación en el índice CDX oficial de Common Crawl.
- **Serie histórica (multi-release)**: `tools/cc_history.py` descarga e indexa releases
  2023–2026 en `THINKUY_CC_HISTORY_DIR`; la trayectoria se dibuja **solo** con releases reales.
  Sin releases indexados la tarjeta muestra el estado, nunca valores inventados.
- **In-links reales**: `tools/build_cc_inlinks.py` recorre `vertices+edges` del grafo y produce
  `THINKUY_CC_INLINKS_DB` con los dominios que enlazan a cada revista (referring domains).
- **Caché y serie propia**: cada auditoría se persiste en `data/scivis_store.db` (TTL por defecto
  24 h, `?refresh=1` fuerza nueva medición), acumulando una trayectoria verificable de la propia
  herramienta.

> **Integridad**: si el dataset no está instalado, o un release histórico no está indexado,
> SCIVIS declara "no disponible" en lugar de interpolar. El PSL guard evita atribuir la centralidad
> de un TLD/sufijo público (`edu.co`, `org.mx`…) a una revista.

> **Resolución dominio-primero**: el Web Graph mide dominios, no títulos. La auditoría acepta
> dominio directo (vía más precisa), título/ISSN con coincidencia exacta normalizada (sin falsos
> positivos por substring), y OpenAlex solo como refuerzo. Cada respuesta declara la proveniencia
> (`domain_direct` / `curated_registry` / `catalog_url` / `openalex_homepage`) y marca `shared_host`
> cuando el dominio es un portal OJS compartido (p. ej. `revistas.ucm.es`): en ese caso se advierte
> que la métrica corresponde al portal, no a la revista concreta.
>
> Para un análisis exhaustivo de incidencias, errores de homonimia en clustering de OpenAlex y calibración de filtros de coherencia disciplinar, consultar: [docs/BITACORA_METODOLOGICA_HALLAZGOS.md](docs/BITACORA_METODOLOGICA_HALLAZGOS.md).

## Hoja de ruta (fuera del MVP)

- **Fase 2**: expansión semántica automática de keywords (tesauros del campo:
  Tesauro de Comunicación de Chile, UNESCO, EuroVoc), widgets nativos móviles,
  login y perfiles.
- **Fase 3**: aprendizaje implícito por comportamiento (qué abres/ignoras),
  funciones sociales/collaborativas (compartir feeds), API pública.

## Configuración (variables de entorno)

| Variable | Default | Descripción |
|---|---|---|
| `RADAR_DB_PATH` | `data/radar.db` | Ruta de la base SQLite |
| `RADAR_AUTO_HARVEST` | `0` | Arrancar el scheduler (cada 6 h) con el API |
| `RADAR_HARVEST_INTERVAL_HOURS` | `6` | Intervalo de cosecha |
| `RADAR_DEFAULT_DAYS` | `365` | Ventana temporal por defecto |
| `RADAR_MAX_ARTICLES` | `1500` | Tope por corrida |
| `RADAR_REQUEST_DELAY` | `0.15` | Pausa entre peticiones a fuentes (cortesía) |
| `REDALYC_TOKEN` | `""` | Token opcional de api.redalyc.org |
| `THINKUY_OPENALEX_API_KEY` | `""` | API key OpenAlex (Bearer). Sin ella: ~100 créditos/día y luego 409 |
| `THINKUY_CC_RANKS_DB` | `D:\cc_domain_ranks.db` | Base SQLite con los rankings de dominios del release activo de Common Crawl |
| `THINKUY_CC_RANKS_GZ` | `D:\cc_domain_ranks.txt.gz` | Archivo `domain-ranks.txt.gz` del release activo |
| `THINKUY_CC_EDGES_GZ` | `D:\cc_edges.txt.gz` | Archivo `domain-edges.txt.gz` (grafo real, para in-links) |
| `THINKUY_CC_VERTICES_GZ` | `D:\cc_vertices.txt.gz` | Archivo `domain-vertices.txt.gz` (id→dominio, para in-links) |
| `THINKUY_CC_HISTORY_DIR` | `D:\cc_ranks_history` | Carpeta con releases históricos indexados (serie temporal real) |
| `THINKUY_CC_INLINKS_DB` | `D:\cc_inlinks.db` | Base de referring domains calculada con `tools/build_cc_inlinks.py` |
| `THINKUY_CC_RELEASE` | `cc-main-2026-jun-jul-aug` | Identificador del release activo del WebGraph |
| `THINKUY_CC_AUDIT_TTL_HOURS` | `24` | TTL de la caché de auditorías SCIVIS (`/api/scivis/audit`) |

## Estructura del repositorio

```
radar-obcc/
├── backend/
│   ├── pyproject.toml
│   └── radar/
│       ├── config.py  db.py  normalize.py  matching.py  citations.py
│       ├── harvester/  (journals_seed, scielo, crossref, redalyc, pipeline, cli)
│       └── api/        (main.py = FastAPI, scheduler.py)
├── pwa/        (index.html, css/, js/, sw.js, manifest.webmanifest, icons/)
├── extension/  (manifest.json MV3, popup, options, background, icons/)
├── tools/      (make_icons.py)
├── data/       (SQLite en runtime)
└── README.md
```

---

## Widget OJS

En un Custom Block de OJS:

```html
<script src="https://TU-SERVIDOR/app/embed.js" data-mode="conversation" data-lang="es" data-limit="5"></script>
```

Vista previa local: `http://localhost:8000/widget`

Modos: `conversation` (citas + corpus + CFP), `cfp` (encaje con el call vigente), `latest`.

---

Thinkuy está pensado para autores, autores potenciales y mesa editorial de cualquier
revista del campo. El corpus de referencia del perfil es el centro de gravedad;
SciELO, Redalyc y Crossref alimentan el resto del campo iberoamericano.