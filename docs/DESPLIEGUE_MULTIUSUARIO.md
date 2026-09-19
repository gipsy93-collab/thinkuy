# Despliegue abierto y multiusuario: qué asume hoy una máquina local

> **Origen:** advertencia del IP (18-09-2026): «esta herramienta no quedará en local, se alojará
> de cierta forma en que cualquier persona pueda usarla. Hay que tener cuidado con lo que se está
> haciendo con la base de mi PC».
> **Estado:** auditoría hecha. Los puntos marcados **CRÍTICO** deben resolverse **antes** de
> exponer la herramienta a terceros. Nada de esto se ha cambiado sin decisión: es el inventario.

---

## 1. Lo que ya juega a favor

* **La búsqueda no depende del catálogo local.** Por la regla de oro, la home y
  `/api/librarian/assist` consultan **en vivo** OpenAlex / OpenAIRE / Dialnet. El catálogo es
  un accidente, no la fuente. Eso hace que un despliegue abierto **funcione sin base previa**.
* **Sin secretos en el repositorio**: `THINKUY_OPENALEX_API_KEY`, `CORE_API_KEY` y
  `REDALYC_TOKEN` se leen de variables de entorno (`radar/config.py`).
* **Rutas de datos configurables**: `THINKUY_DATA_DIR` y `THINKUY_DB_PATH` existen y son
  variables de entorno.

## 2. Riesgos encontrados, con evidencia

### CRÍTICO — `db.set_db()` muta una variable **global del proceso**

`backend/radar/db.py:206-224`

```python
_DB_OVERRIDE: Path | None = None
def set_db(field_id):
    global _DB_OVERRIDE
    _DB_OVERRIDE = config.DATA_DIR / f"radar_{field_id}.db"
```

`POST /api/field/set` llama a `db.set_db(field_id)`. En una máquina local eso cambia *tu* base.
**En un servidor compartido, si un usuario cambia de campo, cambia la base de TODOS los que
estén usando la herramienta en ese momento.** La sesión de un investigador alteraría el corpus
de los demás. Es el riesgo más grave del inventario.

### CRÍTICO — la base es un **estado global compartido** y se escribe en cada consulta

`db.upsert_article` aparece en **17 puntos**, diez de ellos en `harvester/pipeline.py`, tres en
`api/main.py` y uno en `harvester/live_search.py`. En concreto, **cada búsqueda en vivo indexa
sus resultados en la misma base** (`librarian_assist`):

* los resultados de la búsqueda de un usuario se mezclan con los de todos;
* el catálogo crece con la actividad de cualquiera (hoy: 12.039 artículos sin criterio de quién
  los trajo);
* los **datos privados** de una revisión —protocolos, cribados, charting, manuscritos— viven en
  las mismas tablas, **sin columna de usuario ni de tenant**: cualquiera vería la revisión de
  cualquiera.

### ALTO — escrituras a disco por petición, dentro del árbol de código

* `data/html_render/` (caché del navegador sin cabeza, `render_js.py`): una carpeta que crece
  con el uso y que en un servidor debe ser efímera y con tope de tamaño.
* `data/cache_taxonomia.json` (caché de Wikidata), `data/demo/*` (artefactos de verificación).
* `backend/scratch/servidor_*.log` (registro del servidor, escrito por el lanzador).
* `DATA_DIR` apunta por defecto a `PROJECT_ROOT/data`, **dentro del despliegue**: en un servidor
  conviene que esté fuera (volumen montado) y que el código sea de solo lectura.

### ALTO — SQLite con múltiples escritores

Un archivo SQLite tolera lecturas concurrentes (WAL) pero **serializa las escrituras**. Con
varios usuarios escribiendo en cada búsqueda aparecerán bloqueos. Además, hoy el lanzador levanta
**dos procesos** (IPv4 e IPv6), lo que multiplica los escritores sobre el mismo archivo.

### MEDIO — CORS abierto a cualquiera

`backend/radar/api/main.py:66`: `allow_origins=["*"]`. Aceptable en local, **inaceptable en un
servicio público**: cualquier sitio puede llamar a la API desde el navegador de un tercero.

### MEDIO — rutas absolutas de la máquina del IP

`radar/config.py:55-60`: los seis datasets de Common Crawl (SCIVIS) apuntan a `D:\...`. Son
sobrescribibles por entorno (bien), pero **el valor por defecto no existe en otro servidor** y
las funciones que los usan deben **degradar declarando**, no reventar.

### BAJO — migraciones al arrancar

`db.init_db()` corre `_migrate_screening_links` en el arranque. Con una sola instancia está bien;
con varias, cada una migra el mismo archivo. Se resuelve fijando **una instancia escritora**.

## 3. Plan propuesto, por orden

| # | Acción | Por qué primero |
| :-- | :--- | :--- |
| 1 | **Quitar la mutación global**: que el campo activo sea **por petición/usuario**, no una variable de proceso | Es el fallo que rompe a los demás usuarios |
| 2 | **Separar datos privados de catálogo**: tablas con `owner_id` (o una base por usuario) para protocolos, cribados y charting | Sin esto no hay privacidad posible |
| 3 | **Hacer opcional la indexación en el catálogo** durante la búsqueda en vivo (bandera de entorno, por defecto apagada en servidor) | Deja de crecer un estado compartido con la actividad de terceros |
| 4 | **Configurar el despliegue por entorno**: `THINKUY_DATA_DIR` fuera del código, `THINKUY_CORS_ORIGINS`, una sola instancia escritora, caché de render efímera y con tope | Es el mínimo de seguridad y operación |
| 5 | **Migrar de SQLite a un motor con concurrencia** (PostgreSQL) cuando haya usuarios reales | No antes: hoy la carga es de un investigador |
| 6 | **Autenticación** (aunque sea por enlace firmado o clave de institución) | Sin identidad no hay separación de datos |

## 4. Regla inmediata adoptada (sin esperar al despliegue)

**Ningún script de desarrollo escribe en la base de producción.** Las pruebas y las sondas
trabajan sobre copias o bases temporales. Motivo: durante la sesión del 18-09 se insertaron y
borraron filas de prueba (`10.1000/prueba.*`) en el protocolo 15 del IP desde un script de
verificación. Se limpiaron, pero **el principio es inaceptable**: una herramienta de verificación
no debe poder alterar los datos reales del investigador.

---

## 5. Nota de alcance

Este documento es un **inventario**, no una migración hecha. Lo que se cambió hoy en el código
por esta advertencia está en el Hito 51 de la bitácora. El resto requiere decisión de producto
(quién es el usuario, dónde vive el dato, cómo se autentica) antes de tocar la arquitectura.
