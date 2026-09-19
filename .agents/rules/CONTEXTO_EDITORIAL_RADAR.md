# Regla de Contexto: Thinkuy SCIVIS & Editorial Radar

> **Conversación de origen**: `ea51cf8e-da53-4f97-89ed-4af8d4a2355a`  
> **Última actualización**: 2026-09-07  
> **Propósito**: Preservar el contexto integral, decisiones de arquitectura, heurísticas matemáticas y correcciones metodológicas implementadas en el sistema.

---

## 1. Módulos y Arquitectura Implementada

### 1.1. `backend/radar/editorial_radar.py`
* **Mapeo temático dinámico (OpenAlex Topics)**:
  - Clasificación en: **Consolidados** (núcleo duro de la revista), **Fronteras Emergentes** (alta velocidad reciente en la literatura global), y **Vacíos de Investigación (Gaps)** (alta demanda global, escasa presencia en la revista).
  - Cálculo de Velocidad de Crecimiento Relativo:
    $$\text{Velocidad} = \frac{V_r / 2}{V_b / 3}$$
    ($V_r$: ventana reciente de 2 años; $V_b$: ventana base de 3 años).
  - **Umbral de significancia estadística**: Exige $V_r \ge 5$ artículos para considerar un tema como emergente, evitando que micro-nichos con 1 paper histórico disparen falsos positivos matemáticos.
  - **Recomendación no alucinatoria de árbitros (ORCID verificado)**:
    - Recupera autores con `has_orcid: true` desde OpenAlex Authors.
    - **Filtro de Coherencia Disciplinar Estricta a nivel de `Field`**: Exige que el `Field` primario del autor pertenezca a los campos de la revista (`allowed_fields`).
    - Neutraliza los falsos positivos por homonimia masiva de OpenAlex:
      * Descartado **Dr. Santiago Fajardo Ruiz** (`0000-0003-2466-4031`, corrosión de materiales en CSIC confundido con el historiador de arte Santiago Rueda Fajardo).
      * Descartado **Dr. Alberto Peña** (`0000-0001-8667-6287`, cirujano pediátrico colado en historia del periodismo por homonimia con Alberto Peña Rodríguez).
      * Descartado **Dr. Ramón Cantero** (cirugía oncológica) y **Dr. Diego Rivera** (hidrología).
    - Autores reales verificados devueltos para *Revista Panamericana de Comunicación*: Javier Márquez (LSU), Andreu Casero-Ripollés (UJI), Rosa Berganza (URJC), Josep Domènech (UAB), Óscar Parra (Siena), M. Elizabeth Boone (Alberta).
    - **Fallback de filiación**: Si `last_known_institution` es nulo, extrae la institución más reciente del array `affiliations`.
    - **Mapeo de métricas**: Devuelve tanto `citations` como `cited_by_count` para evitar renderizar "0 citas".

### 1.2. `backend/radar/scivis.py`
* **Auditoría cibermétrica y editorial**:
  - `_probe_url_for_journal_meta`: Sonda HTTP ligera que inspecciona el HTML de URLs complejas de OJS (`https://.../index.php/...`) para extraer `<meta name="citation_issn">` o `<meta name="DC.Source.ISSN">`. Resuelve el ISSN de forma canónica contra OpenAlex y Latindex.
  - Detección de portales compartidos (`shared_host: true`): Advierte cuando el dominio pertenece a un consorcio universitario (`revistas.csic.es`, `revistas.ucm.es`, `revistas.up.edu.mx`).
  - Persistencia y caché con TTL en `data/scivis_store.db` (tabla `audits`, parámetro `?refresh=1` para forzar medición nueva).

### 1.3. `pwa/index.html` & `pwa/js/app.js` (Caché: `thinkuy-v21`, `v=4.8`)
* **Modal de Invitación Formal a Revisor / Comité Editorial (`#scivis-invite-modal`)**:
  - Desacoplado 100% del modal del método socrático (`#socratic-modal`).
  - Permite alternar entre **Revisor Par (Peer Reviewer)** y **Comité Científico / Consejo Asesor**.
  - Muestra ficha con nombre, afiliación, especialidad y enlace al ORCID verificado.
  - Carta editable con saludo formal, estándares COPE y datos de la revista.
  - Botón de **Copiar Carta** al portapapeles con confirmación visual interactiva.
  - Enlace **Abrir en Correo (`mailto:`)** con asunto y cuerpo pre-rellenados.

### 1.4. Herramienta CLI
* `tools/mapeobiblio.py`: Permite a los editores ejecutar auditorías bibliométricas directamente por línea de comandos.

---

## 2. Documentos de Referencia en el Repositorio
* [`BITACORA_METODOLOGICA_HALLAZGOS.md`](file:///c:/Users/gipsy/Documents/Obsidian%20Vault/03%20Proyectos/radar-obcc/BITACORA_METODOLOGICA_HALLAZGOS.md) (y su réplica en `docs/`): Monografía académica de 13 secciones detallando todos los percances, fórmulas, tablas comparativas y decisiones epistemológicas para ser citada en artículos científicos.
