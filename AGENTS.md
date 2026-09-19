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

---

### 🪜 ESCALERA DE INGESTA (DECISIÓN VINCULANTE — 18-09-2026):
* La ingesta **baja por escalones y solo pasa al siguiente cuando el anterior no entregó el dato**. Orden de coste, legalidad y fiabilidad; no es preferencia estética.
* **1) OAI-PMH** (`oai_dc`): una petición entrega una **revista completa**. Cliente compartido `backend/radar/harvester/oai_dc.py`; destinos `redalyc.py` y `ojs_oai.py` (con detección automática del endpoint). Medido: `dspace.palermo.edu/ojs/index.php/cdc` → 24 artículos en 4,1 s (0,17 s/artículo), 100 % con resumen.
* **2) Metaetiquetas de la ficha + PDF declarado**: cadena determinista del resumen `abstract_chain.py` (`citation_abstract` → `DC.Description` → `citation_pdf_url` → `description` → vacío), expuesta en `POST /api/metadata/abstract`. Medido: 14/14 fichas correctas con **cero llamadas a modelo**.
* **3) APIs de agregadores** (ya en `pipeline.py`): Crossref, OpenAlex, SciELO ArticleMeta, OpenAIRE Graph, CORE, Europe PMC, Unpaywall, Semantic Scholar.
* **4) PDF de acceso abierto** (Unpaywall confirma `is_oa`) + PyMuPDF.
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
     - **Paso 2 (Data Charting JBI PCC)**: Matriz estructurada de extracción (Población, Concepto, Contexto, Metodología, Hallazgos clave) por artículo incluido, exportable a CSV, RIS y BibTeX.
     - **Paso 3 (Síntesis & Rigor)**:
       - *Auditoría de Citas*: Lectura de PDFs con PyMuPDF (`text_extractor.py`), extracción de contextos en el cuerpo del manuscrito (omitiendo listas de referencias finales) y etiquetas asistidas: *"Posible consenso"*, *"Posible disenso"*, *"Posible adopción metodológica"* y *"Posible mención contextual"* con extracción de claim literal.
       - *Agente A.1 Metodólogo*: Redacción del informe sistemático en 7 fases alimentado exclusivamente por `charting_verificado` para erradicar alucinaciones y atención leaks.

2. **Editorial Radar & SCIVIS (`backend/radar/scivis.py` y `editorial_radar.py`)**:
   - Mapeo temático dinámico de OpenAlex (Consolidados, Emergentes con velocidad $>1.4x$, Gaps).
   - **Protocolo Anti-Ruido Descendente Works-First (2022-2026)**: Captación de evaluadores desde obras recientes de impacto en OpenAlex (`/works`) con foco en Sur Global (`SUR_GLOBAL_CODES`).
   - Sonda cibermétrica SCIVIS con Harmonic Centrality y PageRank del Web Graph oficial de Common Crawl, soporte a portales multirrevista (`shared_host`) y validación segura de ISSNs con dígito 'X'.

3. **Arquitectura PWA e Interfaz (`pwa/`)**:
   - Selector Dual de Persona en Home: **Modo Investigador** (manuscrito, vacíos, citas y DOI) vs. **Modo Revista / Editorial** (benchmarking y SCIVIS).
   - Telemetría de cabecera conectada a: `Sonda Federada: OpenAlex · OpenAIRE · Dialnet` | `Acceso Abierto Global • Políticas UE • Iberoamérica`.
   - Inicialización limpia con `initEpistemicTabs()` asegurando arranque íntegro del Service Worker.
   - Versión actual de assets y Service Worker: **`thinkuy-v69` (`v=5.45`)**. Se mantiene con `python tools/bump_pwa_version.py` (fuente única; `--check` falla si `index.html` y `sw.js` se desincronizan).
   - Suite de pruebas de backend: **253/253 tests en verde** (`pytest`; config en `pyproject.toml`, aislamiento de datos en `backend/conftest.py`). Verificación completa: `powershell -File scripts/dev_check.ps1` (ruff + pytest + versión).
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
