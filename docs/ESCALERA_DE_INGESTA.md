# Escalera de Ingesta de Thinkuy (decisión vinculante)

> **Origen de la decisión:** propuesta del IP (18-09-2026) de ordenar la ingesta por
> escalones con salto automático, y hallazgo del Hito 39: el vocabulario `oai_dc` entrega
> en **una petición por revista** lo que la ruta por artículo cuesta una descarga cada uno.
> **Estado:** vigente. La implementación se hace por escalones, no de golpe.

---

## La regla

**La ingesta baja por escalones y solo pasa al siguiente cuando el anterior no entregó el
dato.** El orden no es una preferencia estética: es el orden de coste, de legalidad y de
fiabilidad. Determinista antes que modelo; API antes que scraping; scraping antes que
navegador; y **el campo vacío antes que el campo inventado**.

| # | Escalón | Coste | Estado |
| :--: | :--- | :--- | :--- |
| 1 | **OAI-PMH** (`oai_dc`) | 1 petición por revista | **Implementado** |
| 2 | **Metaetiquetas de la ficha + PDF declarado** | 1 petición por artículo | **Implementado** |
| 3 | **APIs de agregadores** | 1 petición por consulta | **Implementado** |
| 4 | **PDF de acceso abierto** | 1 descarga por artículo | **Implementado** |
| 5 | **Navegador sin cabeza** (Playwright) | 1 render por página | **Implementado** (sin caso medido que lo requiera) |
| 6 | **Campo vacío declarado** | cero | **Implementado** |

---

## Escalón 1 — OAI-PMH

Cosecha de metadatos de repositorios y revistas (Dublin Core). Es el escalón preferente
porque una revista OJS completa entra en **una sola petición paginada**.

- **Cliente compartido:** `backend/radar/harvester/oai_dc.py` — `Identify`, `ListSets`,
  `ListRecords` con `resumptionToken`, parseo `oai_dc` → `Article`.
- **Destinos:** `redalyc.py` (Redalyc, UAEMex) y `ojs_oai.py` (cualquier OJS).
- **Detección automática del endpoint:** `ojs_oai.detect_oai_endpoint()`. Prueba rutas
  canónicas (`/index.php/<revista>/oai`, `/oai`, `/index.php/oai`, `/oai/oai2`) y, si
  ninguna responde, **inspecciona la propia página** por si declara un enlace.

**Evidencia medida (18-09-2026):**

| Revista | Endpoint | Resultado |
| :--- | :--- | :--- |
| `dspace.palermo.edu/ojs/index.php/cdc` | detectado en la 5.ª sonda | **24 artículos en 4,1 s (0,17 s/artículo), 100 % con resumen, media 1.015 chars** |
| Redalyc (UAEMex) | operativo | 100 registros/página; 32 % con `dc:description`, 100 % con `dc:subject` |
| `redipe.org/index.php/1` | **ninguno** | no expone OAI → cae al escalón 2 |

**Dato de contraste:** la ruta por artículo de hoy costaba 1 descarga por ficha (2,8–8,0 s
en Redalyc por bajar el PDF). El escalón 1 lo hace en **0,17 s**, y el resumen viene incluido.

**Hallazgo que ordena todo:** el resumen de OJS vive en `DC.Description`, que **es el
vocabulario `oai_dc`**. Por eso el escalón 1 y el 2 leen el mismo contrato de metadatos y
comparten el parseo: tener dos mapeos solo garantizaría que diverjan.

**Caveat medido:** no toda instalación expone OAI (Redalyc publica `dc:description` solo en
el 32 % de los registros, con guiones rotos en los más antiguos) y no toda revista OJS lo
publica: `redipe.org` no respondió a ninguna ruta ni lo declara en su página. El escalón 1
no es suficiente por sí solo; de ahí que la escalera exista.

### Conexión con el Modo Revista

El Modo Revista trabaja sobre **la revista como objeto**, y su unidad natural es el
escalón 1. `POST /api/editorial/journal/profile` detecta el `/oai` de una revista OJS,
cosecha su metadata y devuelve el **Editorial DNA** (qué publica, desde cuándo, en qué
idiomas, con qué palabras clave y con qué cobertura de resumen y DOI), con opción de
ingresar los artículos al catálogo (`guardar: true`).

**Medido en vivo (18-09-2026):** `dspace.palermo.edu/ojs/index.php/cdc` → HTTP 200 en 7,9 s,
endpoint detectado en la 5.ª sonda, 12 artículos, **100 % con resumen**, media 1.268 chars.

---

## Escalón 2 — Metaetiquetas de la ficha

Para cuando no hay OAI (o el registro OAI no trae el dato). Cadena determinista del resumen
en `backend/radar/harvester/abstract_chain.py`, expuesta en `POST /api/metadata/abstract`:

`citation_abstract` → `DC.Description` → `citation_pdf_url` → `description` → **vacío**.

**Evidencia:** 14/14 fichas correctas sobre 15 páginas reales (OJS, SciELO, Redalyc), con
**cero llamadas a modelo**.

---

## Escalón 3 — APIs de agregadores

Ya operativas en el pipeline (`harvester/pipeline.py`, pasos 3–9): Crossref por ISSN,
OpenAlex por ISSN, SciELO ArticleMeta, OpenAIRE Graph v3, CORE (requiere `CORE_API_KEY`),
Europe PMC (XML JATS), Unpaywall y Semantic Scholar para enriquecimiento.

---

## Escalón 4 — PDF de acceso abierto

`POST /api/fulltext/fetch-oa/{doi}`: Unpaywall confirma `is_oa` y ofrece la URL del mejor
PDF abierto; solo entonces se descarga. Extracción con PyMuPDF y segmentación por secciones
(`text_extractor.py`).

---

## Escalón 5 — Navegador sin cabeza

**Implementado** (`backend/radar/harvester/render_js.py`, Playwright + Chromium) y **sin
caso medido que lo requiera**. Se activa solo por petición explícita (`render_js: true` en
`POST /api/metadata/abstract`), sobre **una URL concreta**, con `robots.txt` consultado
antes y el HTML en caché en disco.

### Corrección de una atribución propia (18-09-2026)

Este escalón se había justificado con dos «muros» que, **al medirlos, no lo justifican**:

| Caso atribuido | Qué se supuso | Qué se midió |
| :--- | :--- | :--- |
| SciELO `scielo.php?script=sci_arttext&pid=...` (714 bytes) | muro de JavaScript | **403 del servidor para todos**: también para Googlebot (713 bytes) y también cambiando el UA. Con `https` ni conecta. **El navegador devuelve los mismos 713 bytes.** No es JS ni filtro de UA: esa ruta está bloqueada o retirada. La vía correcta es la **API ArticleMeta** o el dominio nuevo. |
| Redalyc (ficha de ~10 KB sin resumen) | el resumen se carga por JavaScript | El resumen de Redalyc, **cuando existe, está en el registro OAI-PMH** (escalón 1): comprobado con el artículo `10633204`, que tiene `dc:description` de 1.357 chars mientras su ficha HTML (14.987 bytes) no lo trae. Donde no está en el OAI, **tampoco existe**: tres fuentes independientes (ficha, PDF y registro OAI) lo confirman para los artículos de *Alteridad* 2008-2011. |

**Conclusión honesta:** hoy el escalón 5 es **último recurso disponible, no una necesidad
demostrada**. Se mantiene implementado y gateado porque los muros de JavaScript existen en
la web académica, pero **no se ha medido todavía ningún caso del nicho que lo requiera**, y
no se presentará como justificado hasta medirlo.

**Condiciones de entrada (no negociables):** último recurso; una URL por llamada (no hay
método de recorrido ni de descubrimiento); `robots.txt` consultado antes de renderizar
—si devuelve `False` se rechaza, si no se puede verificar se declara en el resultado y **las
dos últimas pruebas fueron lo segundo**—; HTML cacheado para no molestar dos veces al mismo
servidor. Si el render no aporta el dato, se cae al escalón 6.

**Requisito de instalación (el proyecto no fija dependencias en un archivo):**

```
.venv\Scripts\python.exe -m pip install playwright
.venv\Scripts\python.exe -m playwright install chromium      # ~115 MB
```

Si Playwright no está instalado, `render_js.disponible()` devuelve `False` y el endpoint
**declara el motivo** en lugar de fallar: el resto de la escalera sigue funcionando.

---

## Texto citable: el PDF, no la descripción OAI

Hallazgo del 18-09-2026, con tres mediciones encadenadas: la descripción que Redalyc publica
en su OAI viene de un PDF aplanado sin separador en los saltos de línea, de modo que llega
con **palabras pegadas** (`delSoconusco`, `hasido`, `losproblemas`) y, en muchos registros,
con **glifos sustituidos** (`cafetalerq`, `jhales`, `Tijuanq`).

**Se intentó repararlo y se midió que no se debe:**

| Intento | Medición | Veredicto |
| :--- | :--- | :--- |
| Reparar pegotes por reglas (guion de línea, prefijo palabra función, caso) | sobre **500 resúmenes limpios** de la base: la regla de guion modifica el **67,8 %**; la de prefijos, el **98 %** (`community` → `com munity`) | **inseguro: prohibido** |
| Detectar el daño por señales de superficie para marcarlo | señales que disparan en texto limpio: `j` tras consonante **33,2 %** (`objectives`), mayúscula interior **18,2 %** (`BioClima`) | **no discrimina: sin veredicto** |
| **Cambiar la fuente** | mismo artículo (`10633204`): el **PDF** devuelve `del Soconusco` y `ha sido` (pegotes **arreglados**), pero **mantiene** `cafetalerq` y `jhales` | **la vía correcta** |

**Por qué la corrupción de glifos no se arregla:** está **en el PDF de origen** —su fuente
tiene un mapa `ToUnicode` roto—, así que ningún método de ingesta puede recuperarla.
Reconstruirla (`cafetalerq` → `cafetalera`) sería **inventar caracteres**, que es lo que el
protocolo del proyecto prohíbe.

**Regla derivada:**

1. De OAI-PMH se toman **metadatos e identificadores** (título, autores, año, DOI, palabras
   clave).
2. Para **texto citable** (cribado, charting, auditoría de citas) se usa el **PDF** (escalón 4).
3. La única normalización permitida sobre el texto OAI es **colapsar espacios**
   (`normalize.normalizar_espacios`), medida con **0 % de palabras alteradas**.
4. La corrupción de glifos se **acepta y se muestra tal cual**: es una propiedad del
   documento de origen, no un defecto de la herramienta.

---

## Escalón 6 — Campo vacío declarado

Cuando ningún escalón encuentra el dato, el campo queda **vacío y con el motivo declarado**
(`fuente: "none"`, `detalle: "..."`). **Ningún modelo lo rellena.**

Esto no es un detalle: se midió que un SLM fabricó **6 de 7** resúmenes inexistentes en
fichas de Redalyc cuyo registro OAI y cuyo PDF tampoco los traían. El campo vacío es una
respuesta; una invención no.

---

## Fuera de la escalera (y por qué)

| Descartado | Motivo |
| :--- | :--- |
| **Google Scholar / `scholarly`** | Viola los ToS y se bloquea por CAPTCHA. El proyecto consulta APIs abiertas y verificables. No entra. |
| **`pyoai`** | Innecesario: ya existe cliente OAI-PMH propio (`oai_dc.py`, httpx + ElementTree) sin dependencia extra ni código sin mantenimiento. |
| **arXiv** | Fuera del nicho: inglés, preprints de física/CS. El inglés es lengua de ingesta con tope del 30 %, no eje del producto. |
| **PubMed / Entrez (`Biopython`, `metapub`)** | El corpus biomédico ya entra por Europe PMC (XML JATS) sin dependencia pesada. `metapub` es un envoltorio de Entrez: redundante. |

---

## Resumen operativo

1. **OAI primero** (`/oai` de la revista o el repositorio): una petición, toda la revista.
2. Sin OAI → **ficha por artículo** (metaetiquetas) y, si falta el resumen, **el PDF declarado**.
3. Sin ficha accesible → **APIs** por DOI/ISSN.
4. Sin API → **PDF abierto** vía Unpaywall.
5. Con muro de JavaScript → **navegador**, como último recurso y con permiso explícito.
6. Sin dato en ningún escalón → **campo vacío declarado**. Jamás un modelo.
