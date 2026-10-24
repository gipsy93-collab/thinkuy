# Pertinencia de la herramienta en el plan doctoral

> Fecha: 22-09-2026 · Verificado contra `plan de investigación.pdf` (15 pp.), `Defensa del plan de investigación.md` y el código de `backend/radar/`.
> Objeto: determinar en qué medida la capa "Modo Investigador" (Ruta 1: sonda en vivo + cribado PRISMA-ScR + charting) es pertinente dentro de la tesis *Marcos normativos para la ciencia participativa entre la Unión Europea y Latinoamérica y su impacto en la democratización de la ciencia*.

## 1. Lo que dice el plan (relevante para la herramienta)

- **Diseño:** secuencial exploratorio de métodos mixtos, tres fases (cualitativa–cualitativa–cuantitativa).
- **Fase 1 — Scoping Review 2005–2025.** Directrices **PRISMA-ScR**; búsqueda sistemática en **Scopus, Web of Science, Dialnet y La Referencia**; universo inicial ≈ **700 estudios**; cribado título/resumen y texto completo; depuración de duplicados; **codificación en ATLAS.ti**; análisis longitudinal del concepto.
- **Fase 2 — Análisis discursivo.** Análisis crítico del discurso sobre un subconjunto + entrevistas semiestructuradas.
- **Fase 3 — Implementación.** Estudio en profundidad de 2–3 casos (≈ 25–30 entrevistas).
- **Cronograma, Año 4 (Oct–Nov 2028):** "preparación de entregables (**dataset, repositorio reproducible, plataforma web**) y plan de difusión".

**Dato central:** la herramienta **ya tiene un lugar formal en el plan**. El entregable "plataforma web" del Año 4 es esta herramienta; solo no está nombrada. Declararla no desvía la tesis, la precisa.

## 2. Correspondencia herramienta ↔ plan

| Componente del plan | Capacidad de la herramienta | Estado | Veredicto |
| :--- | :--- | :--- | :--- |
| Fase 1 · búsqueda en **Dialnet** y **La Referencia** | Sonda federada en vivo: Dialnet, OpenAIRE Graph (LA Referencia), SciELO, Redalyc, OpenAlex | Funciona hoy, sin base local | **Cobertura directa** |
| Fase 1 · búsqueda en **Scopus / WoS** | No las cubre (cerradas, de pago) | — | **No sustituye** |
| Fase 1 · cribado título/resumen y texto completo | `/screen`, `/screen-batch`, ranker de lectura, diagrama PRISMA trazable | Funciona | **Cobertura directa** |
| Fase 1 · codificación/extracción (ATLAS.ti) | Matriz de charting JBI PCC + export CSV/RIS/BibTeX | Funciona, pero es otra lógica | **Complementa; no reemplaza ATLAS.ti** |
| Fase 1 · análisis longitudinal | Metadatos con año y fuente por registro | Funciona | **Apto** |
| Fase 2 · análisis crítico del discurso y postura | Ruta 2 (auditoría de citas: ejes A/B/C) | **Parcial**: exige texto completo, hoy solo por PDF que sube el investigador | **Asiste; no cubre la fase** |
| Año 4 · entregable "plataforma web" | Es la herramienta | En construcción | **Ya previsto en el plan** |

## 3. Veredicto de pertinencia

1. **La herramienta es instrumento directo de la Fase 1.** Su Ruta 1 es, funcionalmente, un protocolo PRISMA-ScR operativo: búsqueda en vivo, cribado, diagrama de flujo y charting exportable.
2. **Es el entregable ya previsto en el Año 4.** La tesis cierra con "plataforma web"; la herramienta es su realización.
3. **No compite con Scopus/WoS: las complementa.** Su aporte específico es cubrir el **diamante iberoamericano (SciELO, Redalyc, Dialnet, LA Referencia)** que esas bases subindexan — lo que coincide con el recorte geográfico de la tesis y con la política de lenguas ES/PT.
4. **La Fase 2 solo queda parcialmente asistida.** La auditoría de citas necesita texto completo y hoy depende de carga manual; no debe presentarse como capacidad cerrada.

## 4. Riesgos a declarar

- **Doble fuente de verdad en la codificación.** El plan prevé ATLAS.ti; la herramienta ofrece charting. Debe declararse cuál gobierna la trazabilidad (recomendado: ATLAS.ti como fuente de verdad cualitativa; charting como capa de exportación estructurada).
- **Endogamia.** La tesis responde P1–P3; la herramienta no puede desplazarlas. Su estatus es *contribución instrumental*, no núcleo argumental.
- **Multiusuario.** Si el entregable del Año 4 se ofrece a terceros, el aislamiento por `owner_id` y la exigencia de Bearer son condición previa (ver `AGENTS.md` y `docs/DESPLIEGUE_MULTIUSUARIO.md`).

## 5. Conclusión operativa

La herramienta **es pertinente y no desviante**: cae sobre la Fase 1 (scoping review) y sobre un entregable que el plan ya exige. Su declaración formal en la tesis es un capítulo de **contribución metodológica/instrumental** (ver `docs/ARTEFACTO_METODOLOGICO_TESIS_AUDITORIA_EPISTEMICA.md`), con dos límites explícitos: no cubre Scopus/WoS y no resuelve por sí sola la Fase 2. Lo que resta para que sea "dejable" (aislamiento multiusuario, manual, licencia, DOI) se aborda por separado, después de que la herramienta esté lista y funcional.
