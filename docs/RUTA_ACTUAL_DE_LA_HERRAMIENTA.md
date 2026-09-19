# Cómo funciona HOY la ruta de Thinkuy

> Fecha: 18-09-2026 · Verificado contra el código, no contra la intención.
> Levanta en `http://localhost:8000/app/` (PWA) · `run_server.py` inicia el servidor y un refresco del catálogo cada 6 h.

## El dibujo

```
                    ┌─────────────────────────────────────────────┐
   TÚ ESCRIBES      │  RUTA 1 — DESCUBRIMIENTO  (EN VIVO)         │
   UN TEMA    ────► │  No necesita base local. Funciona hoy.      │
                    └─────────────────────────────────────────────┘
                          │
                          ▼
        Sonda federada en vivo:  OpenAlex  ↔  OpenAIRE  ↔  Dialnet
        (GET/POST /api/librarian/assist   ·   /review/protocol/{id}/harvest-search)
                          │
                          ▼
        Llegan METADATOS + RESUMEN  (no el cuerpo del artículo)
        Se indexan en sesión para no repetir la consulta
                          │
                          ▼
        Cribado PRISMA ──► Ranker de lectura ──► Diagrama de flujo
        (/screen, /screen-batch, /screening/rank, /flow-diagram)
                          │
                          ▼
        Matriz de extracción sobre el RESUMEN + export CSV/RIS/BibTeX
        (/chart, /charting, /export)

                    ┌─────────────────────────────────────────────┐
   PARA AUDITAR     │  RUTA 2 — CITAS Y POSTURA                   │
   LAS CITAS   ────►│  Necesita TEXTO COMPLETO.  ◄── LA PARED     │
                    └─────────────────────────────────────────────┘
                          │
              ¿de dónde sale el texto completo?
                          │
        ┌─────────────────┼──────────────────────────┬─────────────────┐
        ▼                 ▼                          ▼                 ▼
  PDF que subes     Texto pegado            Europe PMC (XML)    SciELO/Redalyc/OJS
  /fulltext/        /api/fulltext           fulltext_auto.py    ✗ NO EXISTE
  extract-pdf       (manual)                ✗ NO CONECTADO      ruta automática
        │                 │                          │                 │
        └─────────────────┴──────────┬───────────────┘                 │
                                     ▼                                 │
              Se extraen secciones + contextos de cita                 │
              (text_extractor.py · ingest_fulltext_and_contexts)       │
                                     │                                 │
                                     ▼                                 │
              Etiquetado epistémico: ejes A (postura) · B (certeza)    │
              · C (función)  →  propuestas «posible X» con evidencia   │
                                     │                                 │
                                     ▼                                 │
              El investigador valida  ◄─────────────────────────────────┘
              (eso es lo que hace que el resultado sea confiable)
```

## Ruta 1 — Descubrimiento (funciona hoy, sin base local)

| Paso | Qué pasa | Endpoint real |
| :--- | :--- | :--- |
| 1 | Escribes un tema en lenguaje natural | PWA o `POST /api/librarian/assist` |
| 2 | El motor "escucha" y reformula: *«Ah, lo que usted busca es…»* | respuesta `heard_as` |
| 3 | **Consulta en vivo** a OpenAlex, OpenAIRE y Dialnet | `probe_engine` = *Sonda Federada* |
| 4 | Devuelve metadatos y **resumen** de cada artículo | `data_source` = `live_probe` |
| 5 | Se indexan en sesión (SQLite) solo como caché | `db.upsert_article` |
| 6 | Cribas (incluir/excluir/dudoso) y el ranker reordena | `/screen`, `/screening/rank` |
| 7 | Se dibuja el diagrama PRISMA | `/flow-diagram` |
| 8 | Extracción a la matriz y export | `/chart`, `/export` |

**Comprobado hoy mismo:** *«secado de alimentos y calidad nutricional en America Latina»* → **49 resultados** (openalex 48 · dialnet 1), trabajos pertinentes. **Nada predeterminado.**

## Ruta 2 — Auditoría de citas (necesita texto completo)

Aquí está la frontera que usted detectó. Para analizar **cómo se cita** hace falta el **cuerpo del artículo y su bibliografía**, y eso no viaja en el resumen.

**Las cuatro puertas de entrada del texto completo, hoy:**

| Puerta | Estado | Qué es |
| :--- | :--- | :--- |
| `POST /api/fulltext/extract-pdf` | ✅ **la que se usa** | Usted sube el PDF; se convierte a secciones + contextos |
| `POST /api/fulltext` | ✅ | Usted pega el texto ya limpio |
| `harvester/fulltext_auto.py` (Europe PMC) | ⚠️ **existe pero NO está conectado** | Nadie lo llama: no hay endpoint ni tarea programada. Solo biomédico |
| SciELO / Redalyc / OJS | ❌ **no existe** | No hay ruta automática al cuerpo en el diamante iberoamericano |

Y un detalle revelador: **Unpaywall sí se ejecuta** en la cosecha (`pipeline.py`, paso 9): guarda en cada artículo el **estado de acceso abierto y la URL del mejor PDF abierto**… pero **nadie descarga ese PDF**. El propio módulo lo declara: *«nunca se descargan PDFs»*.

## La pared, en una frase

> **La descubribilidad está resuelta y es en vivo. La lectura profunda está resuelta solo si el texto completo llega a la base, y hoy llega por su mano (PDFs que usted sube).**

## Qué falta conectar (piezas que ya existen o son acotadas)

1. **Exponer `fulltext_auto`** — un endpoint o comando que rellene textos completos biomédicos. *Está escrito y funciona; solo no está enchufado.*
2. **Ruta iberoamericana** — obtener el cuerpo desde SciELO, Redalyc y OJS (XML/HTML del artículo; ArticleMeta solo da metadatos, ya verificado).
3. **Aprovechar la URL de Unpaywall** que ya se guarda, descargando solo PDFs con licencia abierta.

Con esas tres, la Ruta 2 funcionaría para **cualquier tema iberoamericano** sin que usted cargue un solo PDF. Sin ellas, la herramienta sirve completa para descubrir, cribar y mapear, y sirve a medias para auditar citas.

## Lo que hoy NO es un problema

- **No hay resultados predeterminados.** La sonda consulta en vivo y para cualquier tema.
- **No hay que "llenar una base" para usar la herramienta.** El catálogo local es caché, no requisito.
- **Las etiquetas de postura no se presentan como verdad**: son propuestas «posible X» con el marcador a la vista, y el investigador valida.
