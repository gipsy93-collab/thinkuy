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
