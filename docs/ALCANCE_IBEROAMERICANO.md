# ALCANCE DEL PRODUCTO — Sur Global Iberoamericano

> Decisión registrada el 2026-09-18 (Fase 0). Esta nota es vinculante para el diseño del dataset, del modelo y de la interfaz.

## 1. Definición del nicho

**Thinkuy es una herramienta para el Sur Global iberoamericano.**

- **Lenguas de primera clase: español y portugués.** Toda capacidad del modelo (T1 rol epistemológico, T2 PCC/JBI, T3 auditoría de citas) debe estar validada en ambas.
- **El inglés es lengua de INGESTA, no de nicho.** Debe estar presente porque parte de la literatura iberoamericana se publica o indexa en inglés, pero no define el producto.
- **Bases de referencia:** SciELO (incluye Brasil y Portugal), Redalyc, Dialnet, LA Referencia / OpenAIRE Graph, Latindex 2.0. Coherente con el motor federado de la plataforma.

## 2. Eje "tradición epistémica" (decisión A)

La taxonomía `Hegemónica / Medicina Social / Decolonial / Ecología de Saberes / Apropiación Social / Crítica Latinoamericana` es **iberoamericana y de ciencias sociales**. Por tanto:

- Se activa **solo** cuando el perfil del usuario es LATAM/CCSH.
- Fuera de ese perfil, el modelo debe responder **`No aplica`** y la interfaz no debe mostrar el campo.
- El mecanismo ya existe a medias en la plataforma (`profiles/ciencia_politica.json`, `salud_publica.json`, `comunicacion.json`, endpoint de cambio de campo en runtime). El eje debe quedar **declarado por perfil**, nunca global.

**Ampliación obligatoria para portugués:** se añaden `Saúde Coletiva` (par brasileño de Medicina Social) y `Epistemologias do Sul` / `Educação Popular` (Freire, Boaventura de Sousa Santos). Sin estas categorías, un artículo brasileño no tiene etiqueta válida.

## 3. Política de idiomas del corpus

| Lengua | Objetivo | Estado verificado 18-09 |
|---|---|---|
| Español | ≥ 40 % | 31/69 (45 %) ✔ |
| Portugués | ≥ 30 % | **0/69 (0 %) ✘ — bloqueante** |
| Inglés | ≤ 30 % | 38/69 (55 %) ✘ |

**Remedio en curso:** bloque `CORPUS ENTRENAMIENTO\PDFS\PRISMA_JBI\` (SciELO Brasil, revisiones con PRISMA/JBI explícito, 2022-2026): 31 PDFs, 18 markdown extraídos, 13 pendientes de extracción. Su `INDICE.md` declara 16 artículos y está desactualizado; se regenera en Fase 2.

## 4. Etiquetas: códigos ASCII estables

Las etiquetas de salida del modelo se escriben como **códigos ASCII canónigos**, y la interfaz las localiza a ES/PT/EN:

| Código | ES | PT |
|---|---|---|
| `SEMINAL` | Seminal | Seminal |
| `SYNTHESIS_REVIEW` | Síntesis / Review | Síntese / Revisão |
| `THEORETICAL_FRAMEWORK` | Teórico / Framework | Teórico / Referencial |
| `METHODOLOGICAL` | Metodológico | Metodológico |
| `EMPIRICAL` | Empírico | Empírico |

Tres razones verificables: (1) el modelo no aprende la taxonomía en tres idiomas; (2) se eliminan los errores por acentos en comparaciones de cadena; (3) se elimina el fallo documentado en el Hito 22, donde el modelo emitió variantes libres (`"REVIEW_SYSTEMATIC"`) en lugar del término canónico.

## 5. Taxonomía de stance (T3): tres ejes, no seis clases

Corrección aceptada el 18-09. Las seis fórmulas de la propuesta original (`ESTRUCTURA ORACIONES`) se reformulan como **tres ejes ortogonales** porque las categorías originales se solapaban (p. ej. "matizar" figuraba simultáneamente como divergencia suave y como matización), lo que hizo inanotable la taxonomía y produjo el colapso `Concesión_Matización 35/51`.

| Eje | Valores | Fuente léxica |
|---|---|---|
| **A — Postura** | `SUPPORT` / `CONFLICT` / `NEUTRAL` | listas ES+PT+EN de marcadores de consenso y disenso |
| **B — Certeza** | `STRONG` / `MODERATE` / `WEAK` | hedges y boosters (Hyland) |
| **C — Función retórica** | `REPORT` / `METHOD_ADOPTION` / `GAP` / `CONCESSION_REDEFINITION` / `OWN_CLAIM` | verbos de reporte (Thompson & Ye 1991) y concesión |

Referentes: Hyland (stance, hedges/boosters), Swales (movimientos, citación), Thompson & Ye (1991) para verbos de reporte, Martin & White (2005) para concesión/apreciación corporizada.

## 6. Regla de construcción del dataset

El etiquetado **no lo fija un modelo de lenguaje**. Etiqueta un **motor de reglas determinista** (lista cerrada de marcadores + detección de agente propio/tercero) y **arbitra el investigador**. El SLM solo extrae fragmentos y redacta el `<pensamiento>` a partir de spans verbatim.

Motivo: el mismo principio que rige la herramienta en producción — el LLM no introduce conocimiento ni hechos que el motor puede determinar. La violación de ese principio en la capa de datos produjo las etiquetas descartadas de 17-09.

## 7. Validación de generalización

Los casos de control humano para el κ de Cohen son **36, estratificados por lengua y macro-área: 12 ES / 12 PT / 12 EN**, con un mínimo absoluto de 8 en portugués. Sin representación portuguesa suficiente, el alcance declarado queda sin verificar.

Umbral: **κ ≥ 0,60 por eje**. El eje que no lo alcance sale del target de entrenamiento y se conserva como metadato.
