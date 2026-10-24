# Directrices y Contexto del Proyecto Thinkuy

> **Conversaciones de referencia**: `ea51cf8e-da53-4f97-89ed-4af8d4a2355a`, `1e6bdb1f-82da-4869-9ed7-58c67eec580b` y `1e69276a-3661-4214-b204-665714b0a400`  
> **Fecha**: Septiembre 2026  
> **Proyecto**: Thinkuy — Radar de Comunicación Científica (Tinkuy Lab)

El agente que continúe el trabajo en este espacio de trabajo DEBE tener presente el siguiente contexto consolidado:

### ⚠️ REGLA DE ORO / RESTRICCIÓN NO NEGOCIABLE DE EXPERIENCIA DE USUARIO:
* **NO USAR EL CATÁLOGO LOCAL COMO FUENTE DE BÚSQUEDA PREDETERMINADA**.
* El usuario de Thinkuy no tiene ni debe tener una base de datos local precargada en su máquina.
* Toda búsqueda (`/api/librarian/assist` y home de la PWA) consulta **única y exclusivamente en tiempo real a las bases de datos externas vía API (OpenAlex Works API con filtro de Acceso Abierto e indexación global, OpenAIRE Graph v3 y Dialnet Dismax)** por defecto (`source="live"`).
* El repositorio SQLite local **solo** se consulta si el usuario envía explícitamente `source="local"` (reservado exclusivamente para cuando un investigador decida importar voluntariamente un archivo propio RIS/CSV).
* Los artículos devueltos por la sonda en vivo de OpenAlex/Dialnet/OpenAIRE se indexan dinámicamente en sesión mediante `db.upsert_article` para que el Modo Investigador disponga de IDs internos y persistencia sin requerir un catálogo previo.
* **Hidratación Automática de Dialnet**: Los registros de Dialnet se hidratan concurrentemente con `fetch_article_details` extrayendo el resumen oficial (`<ul id="resumen">...`) y el DOI real de la ficha para habilitar el screening PRISMA sin resúmenes vacíos.
* **Comodines en la consulta**: `?` y `*` se neutralizan antes de llamar a OpenAlex (`live_probe._sin_comodines`). Motivo medido (22-09-2026): toda pregunta de investigación terminada en `?` disparaba **HTTP 400** en OpenAlex (son comodines que exigen búsqueda exacta) y el primer escalón de la sonda fallaba.
* **Re-ranker semántico (BGE-M3) — ENCENDIDO tras medir**: `radar/rerank.py` reordena la sonda por similitud híbrida (denso + léxico) y sugiere vecindarios. **Opcional y degradable**: sin modelo devuelve el orden original y lo declara; es una **señal de ordenación, no una decisión**. **Medido el 22-09-2026 sobre el protocolo 117** (29 obras cribadas con criterio real: 9 incluidas / 16 excluidas): aciertos en el top-10 **0,40 → 0,60**, @15 **0,33 → 0,53**, @20 **0,30 → 0,45** (empate @5). Una prueba rápida previa coincidió: el orden actual ponía **0 de 3** relevantes arriba y el ordenado **3 de 3**. Decisión: instalado el extra en el servidor (`torch 2.14`, `sentence-transformers 6.1`; modelo en caché, carga 3,1 s) y **encendido en `inicio.bat`** (`set THINKUY_RERANK=bge-m3`). **Límite declarado**: una consulta y 29 obras → suficiente para encenderlo, no para declararlo óptimo; repetir la medición en próximas cribas. Extra opcional `backend/requirements-rerank.txt`. Nota técnica: `max_seq_length=512` + `local_files_only=True` evitan un cuelgue medido al codificar 106 textos.

* **Rendimiento del re-ranker (GPU) y precarga**: el `pip` por defecto instaló **torch CPU** (`2.14.0+cpu`), con el que reordenar tardaba **63 s** y los vecindarios **39 s** → el cosechado superaba los 180 s y se cancelaba. Corregido: torch **`2.11.0+cu128`** (`--index-url https://download.pytorch.org/whl/cu128 --force-reinstall`) → la codificación baja a **~3 s** (carga del modelo ~16-18 s, una sola vez). Además: (a) `rerank_y_vecindarios` codifica **una sola vez** (antes rerank y vecindarios codificaban por separado); (b) el modelo se **precarga al arrancar** (`rerank.precargar()` en el `lifespan`) para no cargarlo en la primera búsqueda; (c) los `timeoutMs` del cliente suben a 180 s (home) y 300 s (harvest).
* **Colisión de DOI al minusculizar (arreglado)**: el catálogo llegó a tener `openalex:W7117640167` y `openalex:w7117640167` como dos obras, y la migración `_migrate_screening_links` hacía `UPDATE articles SET doi = LOWER(doi)` → **`IntegrityError` no capturado** (no es `OperationalError`) que **abortaba `init_db`** (el servidor no arrancaría). Corregido: el `UPDATE` **se salta** las filas que chocarían y se captura `sqlite3.Error`; el cosechado ahora **minusculiza los DOI sintéticos**. **Pendiente declarado**: quedan esas 2 filas duplicadas (inofensivas); se pueden fusionar a mano.
* **Deduplicación por título casi idéntico (fuzzy, sin modelo)**: `radar/dedup.py` fusiona la misma obra que entra por dos fuentes con el título apenas distinto (inflexión «política/políticas», acentos, puntuación). El dedup exacto por DOI/título no lo veía. Conserva el registro de mejor calidad (resumen, DOI, citas) y **declara cada fusión** en `duplicados_semanticos`. Umbral `THINKUY_DEDUP_TITULO_UMBRAL` (0.85). Verificado en vivo (22-09-2026): cazó el duplicado OpenAIRE/Dialnet «Participación Ciudadana en las Políticas/Política de Ciencia y Tecnología».
* **Latencia de la sonda y timeout del cliente**: una booleana compleja tarda ~27 s (Dialnet hidrata cada ficha con 1,2 s anti-bot). El cliente HTTP de la PWA cortaba a **20 s** y mostraba un **falso «sin resultados»** (mensaje de respaldo «Hemos consultado el catálogo…»). Medido (22-09-2026): la misma consulta devuelve **62 resultados**; el endpoint tarda 26,8 s. Corregido: la búsqueda en vivo usa `timeoutMs` de 120 s y el harvest del protocolo 180 s. **No confundir un timeout con un vacío.**
* **Snowballing por DOI (expansión EN VIVO)**: `citation_graph.expand_seed_graph` consulta **OpenAlex** para las referencias del semilla (`referenced_works` → `get_works_by_ids`) y para las obras que lo citan (`cites:` → `get_citing_works`), además de las citas internas. Motivo medido (22-09-2026): sin la vía en vivo devolvía **solo la semilla** (6/6 semillas → `expandidos=1`), porque solo el **15%** del catálogo trae referencias. Verificado: semilla externa `10.1098/rsos.231100` → **16 ancestros** (Polanyi 1959, Gettier 1963) + **14 descendientes**.
* **Escuelas de Pensamiento y SPC — corpus CURADO + grafo en vivo**: los endpoints aceptan `protocol_id` y usan como corpus los **artículos INCLUIDOS** del protocolo (contenido curado), no los resultados crudos de la búsqueda. Prioridad: `dois` explícitos → `protocol_id` → catálogo global; se declara en `origen_corpus`. Con corpus, construyen el grafo **EN VIVO** desde OpenAlex (`citation_graph.build_live_graph`: obras del corpus + sus referencias, en una base **temporal en memoria**, sin tocar el catálogo del investigador). Motivo medido (22-09-2026): el catálogo solo trae referencias del **15%** (grafo local de 434 nodos); medido en vivo, 30 DOIs → **281 nodos / 315 aristas** y 40 DOIs → **365 nodos / 570 aristas**. `/schools` filtra por `min_catalog` (defecto **3**) y ambos declaran `fallback_global` + `aviso` si caen al global; `/main-path` expone el tamaño del grafo. **Límite declarado y corregido**: con DOIs arbitrarios el grafo hereda el ruido del corpus (salían escuelas de paleontología o bibliometría); por eso el corpus por defecto es el **curado**. La UI muestra el aviso y la base del grafo.

---

### 🪜 ESCALERA DE INGESTA (DECISIÓN VINCULANTE — 18-09-2026):
* La ingesta **baja por escalones y solo pasa al siguiente cuando el anterior no entregó el dato**. Orden de coste, legalidad y fiabilidad; no es preferencia estética.
* **1) OAI-PMH** (`oai_dc`): una petición entrega una **revista completa**. Cliente compartido `backend/radar/harvester/oai_dc.py`; destinos `redalyc.py` y `ojs_oai.py` (con detección automática del endpoint). Medido: `dspace.palermo.edu/ojs/index.php/cdc` → 24 artículos en 4,1 s (0,17 s/artículo), 100 % con resumen.
* **2) Metaetiquetas de la ficha + PDF declarado**: cadena determinista del resumen `abstract_chain.py` (`citation_abstract` → `DC.Description` → `citation_pdf_url` → `description` → vacío), expuesta en `POST /api/metadata/abstract`. Medido: 14/14 fichas correctas con **cero llamadas a modelo**.
* **3) APIs de agregadores** (ya en `pipeline.py`): Crossref, OpenAlex, SciELO ArticleMeta, OpenAIRE Graph, CORE, Europe PMC, Unpaywall, Semantic Scholar.
* **4) PDF de acceso abierto** + PyMuPDF. Escalera **medida** el 22-09-2026 con `tools/probe_fulltext_routes.py` (muestra aleatoria de 60 iberoamericanos): **85% de cobertura** con (a) Unpaywall `url_for_pdf` → (b) DOI → `citation_pdf_url` de la ficha del editor. Clave: el enlace venía con `&amp;` sin desescapar, y sin desescaparlo SciELO ignora `format=pdf` y devuelve HTML (el falso «no es posible acceder al texto completo»). Implementado en `radar/harvester/fulltext_oa.py` (`resolve_pdf` valida que el cuerpo sea `%PDF` y **cae a la siguiente ruta** si no lo es). Residuo ~15%: WAF (`scielosp.org`), enlaces muertos y casos genuinos sin texto → se declara `not_retrieved`.
* **5) Navegador sin cabeza (Playwright)** — **implementado pero SIN caso medido que lo requiera** (18-09-2026). Se activa solo por petición explícita (`render_js: true`), una URL por llamada y con `robots.txt` consultado antes. **Corrección de una atribución propia:** el 403 de SciELO `sci_arttext` **no es un muro de JavaScript** —lo recibe también Googlebot y con `https` ni conecta— y el resumen de Redalyc, cuando existe, está en el registro OAI (escalón 1), no tras JavaScript. Hoy es último recurso disponible, no necesidad demostrada.
* **6) Campo vacío declarado.** Si ningún escalón encuentra el dato, el campo queda **vacío con el motivo declarado**. **Ningún modelo lo rellena**: se midió que un SLM fabricó 6 de 7 resúmenes inexistentes.
* **Fuera de la escalera:** Google Scholar / `scholarly` (viola ToS y se bloquea por CAPTCHA), `pyoai` (innecesario: ya hay cliente propio), arXiv (fuera del nicho), PubMed/Entrez y `metapub` (el corpus biomédico ya entra por Europe PMC).
* Detalle completo y evidencia en [`docs/ESCALERA_DE_INGESTA.md`](docs/ESCALERA_DE_INGESTA.md).

---

### 🧭 DISCIPLINA DERIVADA, NO DE FÁBRICA (DECISIÓN VINCULANTE — 18-09-2026, CORREGIDA):
* **Ningún perfil de campo es el valor por defecto.** El activo es `general` (neutro y multidisciplinar). Un perfil de disciplina es una **decisión explícita** del investigador (`POST /api/field/set`).
* **Campo de referencia construido:** `ciencia_abierta` — 36 revistas semilla con ISSN verificable (tomadas de la base, no de memoria), 5 temas, **tesauro de 81 entradas** con 80 % de procedencia Wikidata. Activar un campo **no debe sesgar la búsqueda**: tres garantías con prueba automatizada (`backend/test_no_monotematico.py`) — (G1) ningún campo es el defecto; (G2) `live_probe` **no consulta el perfil**, la consulta no se filtra por campo (verificado: el universo es idéntico, `miocarditis` → 4.352 obras con ambos campos); (G3) **el campo puede declarar «fuera de campo»** (`field_id: "ninguno"` → `fuera_del_campo: true`) en lugar de disfrazar la consulta con el tema más parecido. **Antes, un `field_id` desconocido caía al primer tema del perfil: ese era el agujero que hacía monotemática la herramienta.**
* **Para qué sirve Wikidata (`radar/taxonomy.py`), medido:** (a) **enriquecimiento multilingüe de términos** — resuelve 37/38 conceptos con etiquetas **ES 95 % / PT 82 %**; (b) mostrar al investigador el **trayecto** de un concepto (`miocarditis → miocardiopatía → cardiopatía → enfermedad cardiovascular`), que es informativo. **NO sirve como taxonomía de disciplinas** para el nicho: en humanidades el trayecto es somero (`periodismo → actividad → proceso`, `elecciones → voto → toma de decisiones`). La sonda midió concentración, no calidad del nodo; al ejecutarlo se vio que en niveles profundos los nodos son ontología (`quality`, `ocurrencia`, `entidad`), no disciplinas.
* **GUARDIÁN OBLIGATORIO (anti-contaminación), doble criterio:** un nivel solo se usa si (1) **reparte** —más de un nodo y el mayor con **< 50 %**— y (2) **ninguno** de sus nodos es una categoría de la ontología superior (`entidad`, `fenómeno`, `proceso`, `ocurrencia`, `quality`, `sistema conceptual`…). Medido: el **dominio de OpenAlex concentra el 83 %** en «Social Sciences» y los niveles profundos de Wikidata caen en la ontología. **Esos niveles quedan excluidos.**
* **Si el guardián no pasa, la disciplina NO se asigna: se declara.** El eje de campo sigue siendo el **perfil curado** (semillas, temas, vocabulario) más el **tesauro** (`radar/thesaurus.py`); la taxonomía solo asiste.
* **OpenAlex (`topic`/`subfield`/`field`, niveles 1–3) es señal secundaria** y **falla en español** (23/38 resueltos): nunca la disciplina principal.
* **Caché obligatoria** (`data/cache_taxonomia.json`): primera pasada 44 s, después 0,01 s (**×3.780 medido**).
* Detalle y evidencia en los **Hitos 48, 49 y 50** de la bitácora y en `data/demo/sonda_taxonomias.json`.

---

### 🌐 DESPLIEGUE ABIERTO: LA HERRAMIENTA NO VIVE EN LOCAL (REGLA VINCULANTE — 18-09-2026):
* **Thinkuy se aloja como un SERVICIO: la base vive en el servidor y los investigadores abren una dirección.** Nadie accede a la PC de nadie. Guía paso a paso en lenguaje llano (probar en red, túnel para acceso externo, despliegue con Docker): [`docs/SERVIDOR.md`](docs/SERVIDOR.md).
* **BUSCAR ES UNA LECTURA.** Por defecto `THINKUY_INDEX_LIVE_RESULTS=0`: la búsqueda en vivo **no escribe nada** en el catálogo. Solo persiste **transferir resultados a una revisión** (acción explícita). Motivo medido: una sola búsqueda clínica metió 95 artículos de oncología en el catálogo de comunicación de un investigador. Probado en instancia limpia: buscar → la base sigue en 0 artículos.
* **Modo servidor:** `THINKUY_HOST=0.0.0.0` para escuchar en la red (el lanzador imprime la URL para otros equipos); `THINKUY_DATA_DIR` **fuera** del código; `THINKUY_CORS_ORIGINS` **nunca** `*`.
* **Contenedor listo** (`Dockerfile`, `docker-compose.yml` con volumen de datos y healthcheck, `.env` opcional, `backend/requirements.txt` solo con dependencias de servidor). Inventario técnico y riesgos pendientes en [`docs/DESPLIEGUE_MULTIUSUARIO.md`](docs/DESPLIEGUE_MULTIUSUARIO.md).
* **Ningún script de desarrollo escribe en la base de producción.** Pruebas y sondas trabajan sobre copias o bases temporales. **Motivo:** durante la sesión del 18-09 se insertaron y borraron filas de prueba en un protocolo real del IP desde un script de verificación. Se limpiaron, pero una herramienta de verificación **no debe poder alterar los datos del investigador**.
* **Riesgos críticos identificados y aún sin resolver:** (1) `db.set_db()` muta una variable **global del proceso** — en un servidor, cambiar de campo cambiaría la base de **todos** los usuarios; (2) la base es un **estado compartido sin columna de usuario**: protocolos, cribados y charting de cualquier investigador son visibles para los demás; (3) SQLite serializa escrituras y el lanzador abre **dos procesos** (el contenedor ya usa uno solo).
* **Nunca subir secretos al repositorio.** `THINKUY_OPENALEX_API_KEY`, `CORE_API_KEY` y `REDALYC_TOKEN` viven en variables de entorno (`.env`, que no se sube).

---

### 🖥️ INSTANCIA OBSOLETA EN EL PUERTO (AVISO OPERATIVO — 18-09-2026):
* Si la herramienta «no funciona» pero la interfaz carga, **sospechar primero de una instancia obsoleta**, no del código.
* **Diagnóstico en una petición:** `GET /api/health` → campo `build` con la ruta del código cargado en memoria, la fecha de `main.py`, el total de rutas y la presencia de los endpoints clave. Si faltan endpoints, la instancia es vieja: **el disco no es lo que está sirviendo**.
* **`run_server.py` ya lo detecta**: comprueba el puerto antes de arrancar, imprime la huella de la instancia activa y sale con código 2 si está ocupado (una instancia **sin** huella es anterior a su existencia, o sea obsoleta).
* Los procesos de una instancia **elevada** no son direccionables desde una sesión normal (`Get-Process`, `Get-CimInstance` y `taskkill` fallan aunque la tabla TCP los muestre): hay que **cerrar esa ventana** a mano.
* Para dejar un servidor vivo tras cerrar la consola, lanzarlo **desacoplado** (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`); `Start-Process` no basta.

---

### 🔬 PROTOCOLO ESTRICTO DE RIGOR CIENTÍFICO Y CERO COMPLACENCIA (ANTI-SYCOPHANCY):
1. **Prohibición de Fallbacks Silenciosos en Scripts de Evaluación**:
   * Ningún script de parsing o reporte debe contener cláusulas `else:` que asignen por defecto salidas ambiguas o rotas a la clase mayoritaria. Toda salida atípica, rota o fuera de taxonomía debe catalogarse explícitamente como `INVALID_OUTPUT` y computarse como fallo estricto ($0$).
2. **Auditoría de Datos Crudos Obligatoria**:
   * Antes de presentar porcentajes o métricas agregadas (*Accuracy*, $F_1$, etc.), se debe mostrar la distribución de salidas crudas y reportar explícitamente el porcentaje de respuestas sintácticamente válidas vs. inválidas.
3. **Cero Complacencia / Sycophancy y Estabilidad de Criterio**:
   * No validar conclusiones preliminares sin contrastar los datos subyacentes. Si hay ambigüedad o un error de código, reportarlo con serenidad y objetividad, sin oscilar entre el triunfalismo prematuro y la descalificación catastrofista.
4. **Tono Sobrio y Objetivo**:
   * Respuestas concisas, sustentadas en tablas de contingencia, matrices de confusión y evidencia verificable en disco, sin adjetivos grandilocuentes ni celebraciones anticipadas.

---

### 🌎 ALCANCE DEL PRODUCTO (DECISIÓN VINCULANTE — 18-09-2026):
* **Thinkuy es una herramienta para el SUR GLOBAL IBEROAMERICANO.**
* **Lenguas de primera clase: ESPAÑOL y PORTUGUÉS.** El **inglés es lengua de ingesta, no de nicho** (parte de la literatura iberoamericana se indexa en inglés, pero no define el producto). Tope de inglés en el corpus: **≤ 30 %**; objetivo español ≥ 40 %, portugués ≥ 30 %.
* **Bases de referencia:** SciELO (incluye Brasil y Portugal), Redalyc, Dialnet, LA Referencia/OpenAIRE Graph, Latindex 2.0.
* **Eje "tradición epistémica" (decisión A):** la taxonomía `Hegemónica / Medicina Social / Decolonial / Ecología de Saberes / Apropiación Social / Crítica Latinoamericana` se activa **solo bajo perfil LATAM/CCSH**; fuera de ese perfil el modelo responde `No aplica`. Se amplía con **`Saúde Coletiva`** y **`Epistemologias do Sul` / `Educação Popular`** para portugués.
* **Etiquetas como códigos ASCII canónigos** (`SEMINAL`, `SYNTHESIS_REVIEW`, `THEORETICAL_FRAMEWORK`, `METHODOLOGICAL`, `EMPIRICAL`), localizadas en la interfaz. Prohibido emitir variantes libres o cadenas acentuadas como etiqueta interna.
* **T3 se anota en 3 ejes ortogonales** (A postura: `SUPPORT/CONFLICT/NEUTRAL`; B certeza: `STRONG/MODERATE/WEAK`; C función: `REPORT/METHOD_ADOPTION/GAP/CONCESSION_REDEFINITION/OWN_CLAIM`). Las 6 clases originales se solapaban y produjeron el colapso `Concesión_Matización 35/51`.
* Detalle completo en [`docs/ALCANCE_IBEROAMERICANO.md`](docs/ALCANCE_IBEROAMERICANO.md).

### 🧪 CONSTRUCCIÓN DEL DATASET DE ENTRENAMIENTO (REGLA VINCULANTE):
* **El etiquetado NO lo fija un modelo de lenguaje.** Etiqueta un **motor de reglas determinista** (lista cerrada de marcadores ES/PT/EN + detección de agente propio vs. tercero) y **arbitra el investigador**. El SLM solo extrae fragmentos y redacta el `<pensamiento>` a partir de spans verbatim.
* **Motivo:** es el mismo principio que rige la herramienta en producción (el LLM no introduce hechos que el motor puede determinar). Su violación en la capa de datos produjo las etiquetas descartadas el 17-09 (ver `data/_LEGACY/MANIFIESTO.md`).
* **Validación:** 36 casos de control humano estratificados **12 ES / 12 PT / 12 EN**; κ de Cohen **≥ 0,60 por eje**; el eje que no alcance el umbral sale del target y se conserva como metadato.
* **Prohibido** entrenar sin pasar los Gates: Gate 1 (auditoría forense del dataset), Gate 2 (κ humano), Gate 3 (el LoRA debe superar al base zero-shot en el test congelado).
* **Un solo dataset canónico:** `data/thinkuy_v3_gold_standard_chatml.jsonl`, hasheado en [`data/DATASETS.md`](data/DATASETS.md). Nada se borra: lo superado va a `data/_LEGACY/`.
* **Regla técnica:** nunca diagnosticar codificación desde la salida de consola (PowerShell 5.1 falsea acentos); leer siempre con `[System.IO.File]::ReadAllText(ruta, UTF8)`.

---

1. **Modo Investigador (Radar Epistemológico & Scoping Review)**:
   - **Submotor A: Radar Epistemológico**:
     - Vecindarios epistémicos (clustering Union-Find sobre co-citación bibliográfica con umbrales adaptativos).
     - Trayectoria Principal (Main Path Analysis con Search Path Count - SPC para linaje y flujo temporal del debate).
     - Explorador Snowballing por DOI (expansión backward/forward).
   - **Submotor B: Revisión Sistemática (Pipeline PRISMA-ScR / JBI en 4 Pasos)**:
     - **Paso 0 (Clasificación de Roles Epistemológicos)**: Clasificación de las obras de la consulta viva en 5 roles metodológicos (*Seminal, Síntesis/Review, Teórico/Framework, Metodológico, Empírico*) con botón de transferencia directa a cribado.
     - **Paso 1 (Screening PRISMA)**: Cola de decisiones (*Incluir, Excluir, Dudoso*) con justificación obligatoria documentada de exclusión, reordenamiento activo (Active Learning ranker) y diagrama de flujo PRISMA trazable en vivo.
   - **Diagrama de flujo PRISMA 2020 (estricto)**: la identificación sale del **registro de búsquedas por protocolo** (`protocol_searches`: fuente, consulta, límite temporal y fecha — ítem 6), no de la tabla global de artículos. Los **duplicados removidos** se calculan como `identificados − registros únicos` (definición PRISMA). El endpoint `/flow-diagram` expone `prisma_2020` (identificación → removidos antes del cribado → cribado → incluidos) además de las claves retrocompatibles. La **segunda etapa (texto completo)** está modelada de forma **no destructiva** (`stage`: `title_abstract` | `full_text`; decisión `not_retrieved`; unicidad `(protocol_id, doi, stage)`): si el protocolo no tiene cribados de texto completo, los informes buscados/evaluados/excluidos se declaran `None` y el incluido de título/resumen sigue siendo el final; si los tiene, el incluido final pasa a ser el de texto completo. Guía de referencia: [`docs/referencias/PRISMA_2020_es.pdf`](docs/referencias/PRISMA_2020_es.pdf).
     - **Paso 2 (Data Charting JBI PCC)**: Matriz estructurada de extracción (Población, Concepto, Contexto, Metodología, Hallazgos clave) por artículo incluido, exportable a CSV, RIS y BibTeX.
     - **Paso 3 (Síntesis & Rigor)**:
       - *Auditoría de Citas*: Lectura de PDFs con PyMuPDF (`text_extractor.py`), extracción de contextos en el cuerpo del manuscrito (omitiendo listas de referencias finales) y etiquetas asistidas: *"Posible consenso"*, *"Posible disenso"*, *"Posible adopción metodológica"* y *"Posible mención contextual"* con extracción de claim literal.
       - *Agente A.1 Metodólogo*: Redacción del informe sistemático en 7 fases alimentado exclusivamente por `charting_verificado` para erradicar alucinaciones y atención leaks.
       - *Informe PRISMA 2020 (27 ítems)*: `radar/prisma_report.py` expone la lista de verificación completa (`GET /api/review/protocol/{id}/prisma-checklist`) y un informe final en Markdown exportable (`GET /api/review/protocol/{id}/prisma-report?format=md`). Rellena automáticamente lo que la plataforma puede derivar de sus datos (búsquedas, cribado, charting) y **declara** como `manual` lo que exige redacción del investigador; nunca inventa un valor. Sub-pestaña "Informe PRISMA 2020" en el Paso 3.

2. **Editorial Radar & SCIVIS (`backend/radar/scivis.py` y `editorial_radar.py`)**:
   - Mapeo temático dinámico de OpenAlex (Consolidados, Emergentes con velocidad $>1.4x$, Gaps).
   - **Protocolo Anti-Ruido Descendente Works-First (2022-2026)**: Captación de evaluadores desde obras recientes de impacto en OpenAlex (`/works`) con foco en Sur Global (`SUR_GLOBAL_CODES`).
   - Sonda cibermétrica SCIVIS con Harmonic Centrality y PageRank del Web Graph oficial de Common Crawl, soporte a portales multirrevista (`shared_host`) y validación segura de ISSNs con dígito 'X'.

3. **Arquitectura PWA e Interfaz (`pwa/`)**:
   - Selector Dual de Persona en Home: **Modo Investigador** (manuscrito, vacíos, citas y DOI) vs. **Modo Revista / Editorial** (benchmarking y SCIVIS).
   - Telemetría de cabecera conectada a: `Sonda Federada: OpenAlex · OpenAIRE · Dialnet` | `Acceso Abierto Global • Políticas UE • Iberoamérica`.
   - Inicialización limpia con `initEpistemicTabs()` asegurando arranque íntegro del Service Worker.
   - Versión actual de assets y Service Worker: **`thinkuy-v88` (`v=5.64`)**. Se mantiene con `python tools/bump_pwa_version.py` (fuente única; `--check` falla si `index.html` y `sw.js` se desincronizan).
   - La interfaz se sirve como **módulos ES nativos** (`pwa/js/`): `app.js` (orquestador, ~2.400 líneas), `api.js` (cliente HTTP), `dom.js` (`esc`, `showNotification`), `state.js` (config, estado y persistencia), `utils.js` (helpers puros), `bridge.js` (puente explícito app.js→módulos), `review.js` (**cribado PRISMA + charting**), `radar.js` (**proximidad autoral + comparación de revistas**) y `journal.js` (**auditoría editorial, match y huella OAI**). El humo de la PWA se comprueba con `python tools/smoke_pwa.py --start` (Playwright headless; verifica 17 handlers de `window`).
   - Suite de pruebas de backend: **301/301 tests en verde** (`pytest`; config en `pyproject.toml`, aislamiento de datos en `backend/conftest.py`). Verificación completa: `powershell -File scripts/dev_check.ps1` (ruff + pytest + versión).
   - Arquitectura del backend **modularizada** (19-09-2026): `radar/api/` (`main` + `common` + `auth` + `routers/` con 9 subrouters), `radar/scivis/` (5 módulos) y `radar/db/` (7 módulos), con re-exportaciones para retrocompatibilidad.
   - **Aislamiento multiusuario** por `owner_id` en protocolos/cribado/charting + token JWT HS256 (`radar/api/auth.py`). **Límite declarado:** `X-User-Id` no se verifica y el cajón `owner_id='default'` es compartido; para instancia abierta hay que **exigir Bearer y definir `THINKUY_SECRET_KEY`** (ver Hito 58 y `docs/DESPLIEGUE_MULTIUSUARIO.md`).

4. **Avances de Clasificación Epistemológica (Benchmark Duque 2019, 333 artículos)**:
   - **Diagnóstico Zero-Shot Gemma 4 E2B (`entrenamiento/scripts/04_evaluar_gemma4_e2b.py`)**:
     - Puntuación estricta sin fallback: **$167/333$ ($50.15\%$)** | $98.8\%$ formato válido.
     - Confusión principal: $76$ artículos de gobernanza P2 clasificados como P3 por mención superficial de "sociedad civil".
   - **Cirugía Epistémica Few-Shot (`entrenamiento/scripts/05_fewshot_thinkuy_cirugia.py`)**:
     - Integra 10 casos arquetípicos de fallo contrastivo con bloque `<pensamiento>` estructurado en 3 pasos y `<salida_json>` estricto.
     - Rendimiento verificado en prueba de concepto (10 casos): **$80.0\%$ de aciertos** ($8/10$), rescatando casos complejos (IDs 2, 3, 4, 8 y 9) hacia sus categorías canónicas reales.
   - **Entorno Local de Entrenamiento Verificado**:
     - Python: `C:\Users\gipsy\.unsloth\studio\unsloth_studio\Scripts\python.exe`
     - Hardware: NVIDIA GeForce RTX 5060 Laptop GPU (8 GB VRAM), PyTorch `2.11.0+cu128` con CUDA, Unsloth `2026.9.4`, BitsAndBytes `0.50.2`.
     - Modelos GGUF locales: `C:\Users\gipsy\.lmstudio\models\lmstudio-community\gemma-4-E2B-it-GGUF`.

5. **Próxima Implementación Editorial (A retomar a futuro)**:
   - **Micro-cosechador OJS `/oai` y Huella Editorial (Editorial DNA)**:
     - Detección automática del endpoint `/oai?verb=ListRecords&metadataPrefix=oai_dc` al ingresar la URL de una revista OJS.
     - Cosecha ultraliviana de metadatos (títulos, resúmenes/abstracts, keywords de autor) de los últimos 2 a 5 años sin descargar PDFs pesados.
     - Calibración de perfil grounded: perfil semántico de la revista para análisis de brechas editoriales (*Editorial Gap Analysis*) y recomendación de evaluadores por afinidad a los manuscritos reales.
     - Conexión con **LA Referencia**: consulta en vivo a través de la API REST de OpenAIRE Graph (`api.openaire.eu`) para integrar literatura gris, tesis de posgrado y reportes técnicos de repositorios institucionales latinoamericanos en vivo.

5. **Bitácora Metodológica**:
   - Monografía académica en [`docs/BITACORA_METODOLOGICA_HALLAZGOS.md`](docs/BITACORA_METODOLOGICA_HALLAZGOS.md) documentando 11 percances empíricos, fórmulas, tablas comparativas y directrices epistemológicas. **Copia canónica única** (la de la raíz se archivó en `_ARCHIVE/docs_duplicados/`).

6. **Iniciativa Ecdysis-Bio (Biodiversidad del Quindío & Apropiación Social)**:
   - Documentación y roadmap consolidado en [`docs/PROYECTO_ECDYSIS_BIOCLIP_QUINDIO.md`](docs/PROYECTO_ECDYSIS_BIOCLIP_QUINDIO.md).
   - Experimento empírico con BioCLIP (`scratch/test_bioclip_paper.py`) validado sobre amblipígidos de cavernas colombianas del artículo de Delgado-Santa et al. (*Subterranean Biology*, 2025).
   - Arquitectura objetivo: PWA offline-first con ONNX Runtime Web / WebGPU, semáforo de peligrosidad, fichas agroecológicas para caficultura y ciencia ciudadana sincronizada con la Universidad del Quindío.
