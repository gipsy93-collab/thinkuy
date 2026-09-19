# MANIFIESTO DEL ARCHIVO — nada se borra

> Regla del proyecto: **lo superado no se elimina, se archiva aquí** con el motivo y su
> reemplazo. El contenido pesado de `_ARCHIVE/` queda fuera de git; este manifiesto sí
> se versiona para dejar constancia de qué había y por qué se retiró.

## Categorías

| Carpeta | Qué guarda |
| :--- | :--- |
| `residuos/` | Archivos sueltos retirados del árbol de trabajo (backups del split, bases residuales). |
| `caches/` | Bytecode y bases generadas por ejecuciones antiguas (regenerables). |
| `fase0_backup/` | Copias de código previas a la Fase 0 (pendiente de organizar). |
| `tools_superados/`, `scripts_superados/` | Scripts duplicados o huérfanos (pendiente de organizar). |
| `docs_duplicados/` | Copias de documentos que ya tienen versión canónica en `docs/`. |
| `raiz_suelta/` | Archivos sueltos de la raíz que se mueven al archivo (pendiente). |

## Registro

### 2026-09-19 — Limpieza Fase 1 (Hito 61+)

| Elemento archivado | Origen | Motivo | Reemplazo |
| :--- | :--- | :--- | :--- |
| `residuos/scivis.py.bak` (141 KB) | `backend/radar/scivis.py.bak` | El monolito se partió en `radar/scivis/` (5 módulos); verificado fiel con `ast` (33/33 funciones). | `backend/radar/scivis/` |
| `residuos/db.py.bak` (64 KB) | `backend/radar/db.py.bak` | El monolito se partió en `radar/db/` (7 módulos). | `backend/radar/db/` |
| `residuos/radar.db` (0 B) | `backend/radar.db` | Base residual vacía; `config.DATA_DIR` apunta a `<raíz>/data`. | `data/radar.db` |
| `residuos/backend_data/{radar.db,doi_tracker.db}` | `backend/data/` | Bases creadas por scripts ejecutados desde `backend/` (ruta relativa al CWD). | `data/` (con `THINKUY_DATA_DIR`) |
| `caches/pycache_311/*` | `backend/__pycache__/*-311*` | Bytecode de un intérprete 3.11 anterior; el entorno actual es 3.13. | Regenerable |

> Los `.bak` se conservan hasta cerrar por completo la migración de los paquetes `scivis/` y `db/`.

### 2026-09-19 — Reorganización Fase 2 (entorno de trabajo)

| Elemento archivado | Origen | Motivo | Reemplazo |
| :--- | :--- | :--- | :--- |
| `fase0_backup/_BACKUP_FASE0/` (24 archivos) | `_BACKUP_FASE0/` | Snapshot previo a la Fase 0 (re-ruteo `data/`); histórico. | Código vigente en `tools/`, `scripts/` (→ `entrenamiento/scripts/`) |
| `docs_duplicados/ARQUITECTURA_Y_LOGICA_THINKUY.md` | raíz | Copia idéntica de la de `docs/`. | `docs/ARQUITECTURA_Y_LOGICA_THINKUY.md` |
| `docs_duplicados/ARTEFACTO_METODOLOGICO_TESIS_AUDITORIA_EPISTEMICA.md` | raíz | Copia idéntica de la de `docs/`. | `docs/ARTEFACTO_METODOLOGICO_TESIS_AUDITORIA_EPISTEMICA.md` |
| `docs_duplicados/BITACORA_METODOLOGICA_HALLAZGOS.md` | raíz | La bitácora pasa a tener **una sola copia canónica** en `docs/`. | `docs/BITACORA_METODOLOGICA_HALLAZGOS.md` |
| `caches/unsloth_compiled_cache/` | raíz | Caché de compilación de Unsloth (regenerable). | Regenerable al entrenar |
| `caches/_unsloth_sentencepiece_temp/` | raíz | Temporales de Unsloth (regenerable). | Regenerable al entrenar |

> `AJUSTES PY.md` **no** se archivó: se movió a `docs/AJUSTES_PY.md` (documento vivo).

### 2026-09-19 — Reorganización Fase 2B (pipeline de entrenamiento)

| Movimiento | De | A | Motivo |
| :--- | :--- | :--- | :--- |
| Pipeline ML | `scripts/` (25 archivos, numerados `02_`…`10_` + utilidades + `_LEGACY/`) | `entrenamiento/scripts/` | Agrupar todo lo relativo a dataset/entrenamiento fuera de la raíz. |
| Lanzadores de entrenamiento | `entrenar_qwen_1_5b.bat`, `entrenar_qwen_v2_cot.bat`, `exportar_a_gguf.bat`, `iniciar_unsloth_studio.bat`, `probar_modelo_entrenado.bat` (raíz) | `entrenamiento/` | Dejar la raíz solo con `inicio.bat` (servidor). Los `.bat` añaden `cd /d "%~dp0.."`. |

> `scripts/dev_check.ps1` **no** se movió: es de desarrollo/operación y permanece en `scripts/`.

### 2026-09-19 — Reorganización Fase 2C (herramientas superadas)

19 scripts de `tools/` movidos a `_ARCHIVE/tools_superados/`. Criterio: **sin referencia externa**
(ni `.bat`, ni docs, ni código) **y** superados por un sucesor. Los vigentes siguen en `tools/`
(ver `tools/README.md`).

| Archivado | Superado por / motivo |
| :--- | :--- |
| `build_epistemic_dataset_v2_cot.py` | `build_epistemic_dataset_v3_hard_negatives.py` (v3) |
| `benchmark_full_333_tripartite.py`, `benchmark_three_models_live.py`, `compare_qwen_base.py`, `compare_qwen_vs_mistral.py`, `compare_three_models.py` | `benchmark_three_models_rigorous.py` + `robust_tripartite_eval.py` |
| `replicate_full_wos_thinkuy.py`, `replicate_duque_review.py`, `blind_benchmark_duque.py`, `process_wos_native.py` | `replicate_full_scopus_and_merge_thinkuy.py` |
| `run_training_with_monitor.py` | `entrenamiento/entrenar_qwen_v2_cot.bat` + `train_monitor_dashboard.py` |
| `eval_rsu_duque_fine_tuned.py`, `audit_raw_thinkuy_v2.py`, `audit_real_paper.py`, `hunt_10_refutations.py`, `demo_live_probe_epistemic.py`, `test_gemma4_prompt.py` | Diagnósticos de una sola vez / linaje de modelo antiguo |
| `corregir_mojibake_docs.py`, `gen_seed.py` | Utilidades puntuales ya aplicadas |

### 2026-09-19 — Consolidación Fase 3 (módulos sin uso)

| Archivado | Origen | Motivo |
| :--- | :--- | :--- |
| `modulos_sin_uso/models.py` + `modulos_sin_uso/test_models.py` | `backend/radar/models.py`, `backend/test_models.py` | Modelos Pydantic que **solo se importaban entre sí**; la API devuelve dicts y no los usa. Recuperables si se decide tipar los contratos de la API. |

> Se **conservan** (no se archivan) `radar/taxonomy.py`, `radar/thesaurus.py` y
> `radar/harvester/snapshot.py`: son asistencia de campo y capacidades planificadas
> (Hitos 48-50 y mitigación de OpenAlex), aunque hoy no estén cableadas al runtime.
