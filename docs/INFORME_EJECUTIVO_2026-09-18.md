# INFORME EJECUTIVO — Proyecto Thinkuy / radar-obcc

> **Fecha:** 18 de septiembre de 2026 · **Ámbito:** capa de datos y modelo de lenguaje (SLM)
> **Insumo humano:** 48 respuestas de anotación del IP (36 de postura + 12 de protocolo)
> **Documentación completa:** [`BITACORA_METODOLOGICA_HALLAZGOS.md`](BITACORA_METODOLOGICA_HALLAZGOS.md), hitos 23 a 31

---

## 1. Resumen en una página

| Pregunta | Respuesta |
| :--- | :--- |
| **¿En qué estado está?** | El corpus y los instrumentos de etiquetado están construidos, medidos y auditados. **El Gate 2 se cerró: 1 de 6 ejes supera el umbral humano.** |
| **¿Se puede entrenar?** | Sí, pero **solo lo verificable**: formato, fidelidad literal, R1 (guía de reporte) y T2 (matriz PCC). |
| **¿Se puede entrenar la postura?** | **No.** κ = 0,100. Entrenarla sería copiar dentro del modelo los errores de la regla. |
| **¿Cuál es el activo principal?** | El **corpus de 196 artículos únicos** con idiomas balanceados, más el **procedimiento auditable** y el **patrón humano permanente**. |
| **¿Cuál es el hallazgo publicable?** | Una taxonomía de postura epistémica que parece obvia **no es reproducible por reglas a escala** en un corpus iberoamericano (κ 0,10-0,37). |
| **¿Qué costó?** | Tres rondas de anotación del IP (~6 h) y varias iteraciones de instrumento. Evitó, a cambio, incorporar etiquetas no validadas a los pesos. |

---

## 2. Qué se hizo el 18-09-2026 (seis fases, de la 0 a la 3)

| Fase | Objetivo | Resultado |
| :--- | :--- | :--- |
| **0 — Orden y congelamiento** | Deshacer el caos de artefactos | `data/_LEGACY/` con manifiesto; **18 rutas rotas corregidas en 23 archivos** (respaldo en `_BACKUP_FASE0/`); manifiesto de linaje `data/DATASETS.md` con SHA-256; alcance ES/PT registrado en `AGENTS.md` y `docs/ALCANCE_IBEROAMERICANO.md` |
| **1 — Auditoría forense (Gate 1)** | ¿Servía el dataset anterior? | **NO SUPERADO**: 8,9 % de targets con JSON inválido, 10 % con `None`, T1 con 18/22 en una sola clase, T2 con 35 % de insumos no fiables y grounding de PCC de 0,08-0,25, T3 sin ninguna clase `Disenso`, **0 % de portugués** |
| **2 — Motor de extracción y corpus** | Que las secciones fueran reales | Motor reescrito (detección de encabezados por tamaño de fuente, sinónimos ES/PT/EN, corte de bibliografía, exclusión de tablas, rescate de abstracts). Corpus: **220 PDFs → 196 artículos únicos** (24 duplicados descartados) |
| **3 — Etiquetado determinista** | Producir el target sin LLM | Tres etiquetadores: **T1 reformulado** (protocolo R1/R2/R3), **T2 PCC verbatim** con guardián de grounding, **T3 stance** en ejes A/B/C |
| **3b/3c — Cobertura** | Recuperar lo que faltaba | **Citas numéricas `[n]`**: los artículos sin contextos pasaron de **68 a 7**. PCC: `población` 75 % · `contexto` 58 % · `diseño` 42 % · `concepto` 40 % (se descubrió que el *Concepto* de JBI vive en el abstract, no en la metodología) |
| **Gate 2 — Validación humana** | ¿La regla coincide con un humano? | Ver §4. **1 de 6 ejes pasa** |

---

## 3. Evidencia cuantitativa

### Corpus (196 artículos únicos)

| Idioma | n | % | Objetivo | Estado |
| :--- | ---: | ---: | ---: | :--- |
| Español | 94 | 48,0 % | ≥ 40 % | ✅ |
| Inglés | 58 | 29,6 % | ≤ 30 % | ✅ |
| Portugués | 43 | 21,9 % | ≥ 30 % | ❌ faltan ~23 artículos |
| Indeterminado | 1 | 0,5 % | — | — |

**Usabilidad por tarea:** T1 149 · T2 132 · T3 186 artículos.
**Duplicados detectados y descartados: 24** (incluidas 5 copias del mismo documento bajo nombres distintos). Sin esa deduplicación, el mismo artículo podía caer en entrenamiento y prueba.

### Etiquetado de postura (T3)

| Concepto | n |
| :--- | ---: |
| Contextos etiquetados | 4.009 |
| Con marcador (señal) | 415 |
| Reporte neutro | 3.500 |
| Derivados a arbitraje (`AMBIGUO`) | 94 (2,3 %) |
| Rechazados por el filtro de calidad | 820 |

---

## 4. Gate 2 — el resultado central

Medición contra las 48 respuestas humanas del IP, con κ de Cohen por eje y umbral pre-registrado de 0,60:

| Eje | n | κ | Acuerdo observado | Decisión |
| :--- | ---: | ---: | ---: | :--- |
| **R1 — guía de reporte** | 9 | **0,654** | 77,8 % | ✅ **SE CONSERVA** |
| R3 — tipo de síntesis | 10 | 0,167 | 60,0 % | ❌ sale del target |
| R2 — marco de conducción | 10 | 0,333 | 70,0 % | ❌ sale del target |
| C — función retórica | 35 | 0,371 | 74,3 % | ❌ sale del target |
| A — postura | 34 | 0,100 | 73,5 % | ❌ sale del target |
| B — certeza | 33 | −0,043 | 57,6 % | ❌ sale del target |

**Hallazgo más instructivo:** tras corregir la regla, el **acierto observado subió mucho** (A: 44 % → 73,5 %; C: 63 % → 74,3 %) pero el **κ no**, porque la regla quedó tan conservadora que responde `NEUTRAL` en 33 de 36 casos. El κ descuenta lo que se acertaría repitiendo la respuesta mayoritaria: **acertar por repetir lo común no es saber**. La corrección cambió el modo de falla (de inventar postura a no encontrarla), no lo eliminó.

---

## 5. Decisiones tomadas y registradas

1. **Alcance:** Sur Global iberoamericano; ES y PT de primera clase; EN como lengua de ingesta (tope 30 %).
2. **Eje "tradición epistémica":** activo solo bajo perfil LATAM/CCSH; fuera de él, `No aplica`.
3. **Etiquetas como códigos ASCII canónigos**, localizadas en la interfaz.
4. **T1 reformulado:** de «rol epistemológico» (no operacionalizable: 62,4 % una clase, dos clases vacías) a **tipo de protocolo de síntesis** en tres ejes ortogonales verificables contra estándares publicados.
5. **El etiquetado no lo fija un LLM:** reglas deterministas + arbitraje humano. El SLM solo extrae y redacta.
6. **Criterio de frontera:** κ ≥ 0,60 por eje decide qué se entrena. **No se negocia a posteriori.**
7. **Decisión de producto:** entrenar solo lo verificable (formato, verbatim, R1, T2). No entrenar postura, certeza ni función retórica: quedan como capa determinista de **baja confianza**, con evidencia visible y etiqueta «posible».
8. **Métrica de la capa de sugerencias:** tasa de aceptación por el investigador, no κ contra un patrón.

---

## 6. Riesgos abiertos

| Riesgo | Estado |
| :--- | :--- |
| **T2 sin Gate 2 humano** | Pendiente: 12 casos. Su grounding es verbatim por construcción, pero la *selección* del fragmento no está validada |
| **Portugués al 21,9 %** | Faltan ~23 artículos para cumplir el objetivo de nicho |
| **Dependencia de OpenAlex** | Cambio de términos (API key y créditos) ya identificado; mitigación: snapshot S3 + API solo para casos puntuales |
| **Frontera conceptual de la postura** | Es un problema de definición («¿cuándo una mención es postura?»), no de listas más largas. Una tercera iteración no se recomienda |
| **Regenerar artefactos anotados** | Trampa detectada y ya protegida con verificadores (`verificar_control_protocolo.py`) y scripts de re-medición sobre muestra congelada |

---

## 7. Recomendación y próximos pasos

**Corto plazo (recomendado):**

1. **Fase 4 — dataset reducido:** construir el target con lo verificado (formato + verbatim + R1) y el **split por documento con hash**, para que la evaluación sea válida.
2. **Fase 2b (opcional):** cosechar ~23 revisiones en portugués para cerrar el balance de idiomas.
3. **T2 — Gate 2 propio:** 12 casos, mismos formularios con casillas, ~20 min.

**Mediano plazo:**

4. **Entrenamiento acotado** (Gemma 4 E2B con el protocolo de aborto de VRAM; fallback Qwen 1.5B). **Gate 3:** el LoRA debe superar al modelo base zero-shot en el test congelado; si no, no se adopta.
5. **Capa de producto:** el motor determinista propone con evidencia visible; el investigador valida; se mide la tasa de aceptación.

**No recomendado:** una tercera iteración de las listas de marcadores de postura. La evidencia indica que el límite es conceptual, y cada iteración cuesta ~2 h de anotación humana.

---

## 8. Inventario de artefactos producidos

| Ubicación | Contenido |
| :--- | :--- |
| `data/corpus_v2/` | `inventario_unicos.json` (196 artículos con hash, banderas y usabilidad), `extraccion_v2.json`, `extraccion_es_pt.json`, `COBERTURA_V2.md` |
| `data/dataset_v4/` | 36 archivos: muestras de control (36 + 12), formularios de anotación, `gate2_resultado.json`, diagnósticos de stance, T1 y T2, `protocolo_revision.jsonl`, `t2_pcc.jsonl`, `dataset_balanceado.jsonl` |
| `data/auditorias_y_benchmarks/` | `INFORME_FORENSE_DATASET_V3.md`, `dataset_forense_v3.csv` |
| `data/_LEGACY/` | Artefactos descartados con manifiesto y hash |
| `tools/` | 60 scripts; 19 nuevos hoy: auditor forense, reindexado, inventario, tres etiquetadores, generadores y verificadores de formularios, calculador de κ, re-medición sobre muestra congelada |
| `docs/` | `ALCANCE_IBEROAMERICANO.md`, `QUE_SE_LOGRARIA_AL_ENTRENAR.md`, bitácora sincronizada |
| `BITACORA_METODOLOGICA_HALLAZGOS.md` | **Hitos 23 a 31** (9 hitos nuevos) + **18 percances** registrados, incluidos los defectos propios del instrumento |

---

## 9. Valor generado, en una frase por línea

- **Se evitó** publicar o entrenar sobre un dataset con 8,9 % de salidas inválidas, 10 % de `None` y cero portugués.
- **Se corrigió** el motor de extracción, que metía listas de bibliografía dentro de la sección de métodos.
- **Se descubrieron** 24 artículos duplicados que habrían inflado las métricas de evaluación.
- **Se resolvió** el balance de idiomas del nicho (ES 48 %, EN 29,6 %), antes imposible.
- **Se midió** con criterio humano qué se puede automatizar y qué no, con la evidencia en la mano.
- **Se acotó** el entrenamiento a lo verificable, con tres gates pre-registrados.
- **Queda** un patrón humano de 48 casos que sirve para validar cualquier regla futura sin volver a anotar.
