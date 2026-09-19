# PLAN EJECUTIVO — Entrenamiento Thinkuy V5 (Qwen3-4B-2507 + LoRA)

> Fecha: 2026-09-19 · Estado: BORRADOR PARA INVESTIGACIÓN
> Base propuesta: `Qwen3-4B-Instruct-2507` (Apache 2.0, GGUF disponible, no-thinking, contexto 256K)
> Hardware: RTX 5060 Laptop GPU 8GB · Unsloth 2026.9.4 · PyTorch 2.11.0+cu128
> Objetivo: **asistente de mapeo epistemológico y vecindario de autores**, NO motor de scoping/metaanálisis completo.

---

## 0. Decisión de diseño que rige todo el plan (no negociable)

El modelo **propone**, el investigador **valida uno a uno**, y solo validando pasa al siguiente paso.
Esta compuerta de lectura tiene una consecuencia arquitectónica mayor:

> **La interfaz de validación ES la anotadora.** Cada corrección del investigador sobre la
> propuesta del modelo se registra y se convierte en fila del dataset de entrenamiento (gold humano).

Consecuencia: el dataset no se construye en lote previo; **se construye operando la herramienta**
en modo supervisado. El motor determinista propone pre-relleno, el SLM propone texto, el humano
arbitra, y el delta (propuesta → corrección) es el dato de entrenamiento.

---

## 1. Estado real verificado (2026-09-19)

| Activo | Estado | Evidencia |
|---|---|---|
| Reconstrucción Fase 3 (determinista) | **COMPLETA** | `data/dataset_v4/INFORME_FASE3.md` |
| T3 contextos etiquetados | 4.829 (1.073 con señal, 194 ambiguos, tasa 4,0%) | ibíd. |
| T3 dataset balanceado | 1.654 filas (ES 679 · EN 612 · PT 357) | `dataset_balanceado.jsonl` |
| T2 PCC con guardián de grounding | Cobertura P 75% · Ctx 58% · D 42% · Co 40% | INFORME_FASE3 §3bis |
| T1 reformulado R1/R2/R3 | R1 45,6% · R2 53,0% · R3 49,7% (ninguna clase vacía) | INFORME_FASE3 §4 |
| Gate 2 (κ humano) | **A 0,10 · B −0,04 · C 0,37 · R1 0,65 · R2 0,33 · R3 0,17** | `gate2_resultado.json` |
| Corpus fuente | 196 únicos (`inventario_unicos.json`) + PRISMA_JBI markdown PT | `data/corpus_v2/` + `CORPUS ENTRENAMIENTO/PDFS` |
| SciCite (warm-start EN) | train/test/dev JSONL | `scratch/scicite_raw/scicite/` |
| Base actual entrenada | Qwen 2.5 1.5B LoRA (mode collapse previo) | `models/thinkuy_v3_qwen1.5b_lora` |
| Dataset v3 (90 filas) | **GATE 1 NO SUPERADO**, descartado | `INFORME_FORENSE_DATASET_V3.md` |

### Diagnóstico que obliga a actuar

El Gate 2 mide acuerdo **motor determinista ↔ humano**, no humano↔humano.
Con κ 0,10 en postura y −0,04 en certeza, **el motor NO es fuente de verdad para T3**.
Si se entrena con etiquetas del motor, el modelo aprenderá el juicio del motor (que el humano no comparte).

**Decisión derivada (alineada con el punto B):** conservar los 3 ejes ortogonales, pero la **fuente de verdad pasa al humano arbitrado vía la compuerta de validación**. El motor y el SLM son proponentes; el investigador es la etiqueta. Esto convierte el fracaso del Gate 2 en la justificación del diseño de validación uno-a-uno, no en un bloqueo.

---

## 2. Tareas de entrenamiento (3, acotadas)

### T2 — PCC + hallazgos principales (cribado)
- **Entrada:** abstract + sección de métodos (nunca solo abstract).
- **Salida:** `poblacion`, `concepto`, `contexto`, `diseno`, `hallazgos_clave`.
- **Regla dura:** extracción **verbatim** (subcadena literal de la fuente). Si el dato no consta → `No especificado en la metodología`. Prohibido rellenar.
- **Origen del target:** pre-relleno del motor (T2 ya lo hace) + corrección humana.
- **Target ya disponible:** `data/dataset_v4/t2_pcc.jsonl` (132 artículos, fuentes METODOS/ABSTRACTO declaradas).

### T3 — Postura de cita para vecindario (Paso 3 / auditoría)
- **Entrada:** oración que contiene la cita + ventana de contexto (±300 caracteres, como el motor actual).
- **Salida (3 ejes ortogonales, inalterados):**
  - A postura: `SUPPORT` | `CONFLICT` | `NEUTRAL`
  - B certeza: `STRONG` | `MODERATE` | `WEAK` | `NO_DECLARADA`
  - C función: `REPORT` | `METHOD_ADOPTION` | `GAP` | `CONCESSION_REDEFINITION` | `OWN_CLAIM`
- **Fuente de verdad:** humano arbitrado (Gate 2 falló al motor). Pre-relleno del motor como propuesta, corrección humana como etiqueta.
- **Material de partida:** `dataset_balanceado.jsonl` (1.654 filas) para pre-lleno y curva de arranque; la etiqueta final la pone el investigador en la interfaz.
- **Warm-start EN:** SciCite (migración de esquema a 3 ejes NO automática; usar solo para pre-entrenamiento auxiliar o calibrar lectura, no como canónico).

### T1 — Tipo de protocolo de síntesis (mapeo del vecindario)
- **Entrada:** abstract + métodos (+ cuerpo para detección en dos niveles).
- **Salida:** R1 guía (`PRISMA_2020|PRISMA_ScR|ENTREQ|MOOSE|STROBE|NONE_DECLARED`) · R2 marco (`JBI|COCHRANE|ARKSEY_OMALLEY|EPPI|NONE_DECLARED`) · R3 síntesis (`META_ANALYSIS|META_SYNTHESIS|THEMATIC_SYNTHESIS|DESCRIPTIVE_MAPPING|NARRATIVE|NONE`).
- **Nota:** R1 es el único que superó Gate 2 (κ 0,65). R2/R3 **salen del target** hasta que se recalibren (regla pre-registrada). Para mapeo, R1+R3 son los operacionalmente útiles; R2 puede quedar como metadato.

---

## 3. Corpus y datos — qué investigar/reunir

### Necesario (crítico)
| Ítem | Estado | Acción |
|---|---|---|
| Bloques PT reales | PRISMA_JBI: 18 markdown, 13 pendientes | Completar conversión PDF→MD; meta **≥30% PT** del dataset |
| Corpus de 6 áreas | 69 artículos (~55% EN) | Balancear; el techo EN ≤30% del conjunto de entrenamiento |
| Hallazgos clave (T2) | No existe campo anotado | Diseñar extracción verbatim de 1–3 hallazgos por artículo con fuente declarada |
| Registro de validación humana | No existe en la app | **Implementar captura de deltas** (propuesta→corrección→etiqueta) en la UI |

### Recomendado
| Ítem | Uso |
|---|---|
| SciCite (EN) | Pre-entrenamiento auxiliar de lectura de citas; jamás como canónico |
| `control_36` / `control_protocolo_12` | Test congelado de Gate 2 (ya estratificado ES/PT/EN) |
| Data de `candidatos_stance.jsonl`, `respuestas_modelo.jsonl` | Curva de arranque para que el humano corrija, no redacte desde cero |

### A investigar (preguntas abiertas del plan)
1. ¿Qwen3-4B-Instruct-2507 en 4-bit con LoRA r=16 cabe con seq 2048 en 8GB (ya cabe 1.5B con 1536)? Medir con `--dry-run` antes de comprometer horas.
2. ¿El tokenizador de Qwen3 maneja bien ES/PT diacríticos y el formato `<pensamiento>/<salida_json>`? Prueba de 10 prompts antes del entrenamiento.
3. ¿Conviene `train_on_responses_only` (como en Qwen 2.5) o template ChatML nativa de Qwen3? Comparar en dry-run.
4. ¿Cuántas filas humanas se necesitan por eje para κ estable? (Cálculo: con 1.654 pre-lleno, muestrear corrección por estratos de dificultad).
5. `OWN_CLAIM` (n=1) y `METHOD_ADOPTION` (n=13): excluir del target (decisión ya tomada en Fase 3) — verificar que la UI no las exija al modelo.
6. ¿El corpus de 6 áreas es representativo del vecindario epistemológico que se quiere mapear (comunicación + medicina social + ecología de saberes)? Si no, ampliar corpus por campo antes de entrenar.

---

## 4. Arquitectura de entrenamiento

| Parámetro | Valor | Justificación |
|---|---|---|
| Base | `Qwen3-4B-Instruct-2507` (no-thinking) | Mejor ES/PT/capacidad en el rango 4B de pesos abiertos; cabe en 8GB 4-bit |
| Método | QLoRA (bnb 4-bit), r=16, alpha=16 | Mismo patrón validado en 1.5B; subir r solo si dry-run lo permite |
| Seq len | 1536–2048 | Contextos de cita ±300 ×3 + plantilla; sin necesidad de 256K en entrenamiento |
| Épocas | 3 (con pesos de clase) | Contra overfit en clases raras |
| Pérdida | `train_on_responses_only` o nativa Qwen3 | Decidir por dry-run (§3 investigación) |
| Pesos de clase | Ya calculados en Fase 3 (inverso a frecuencia, tope 10) | A: NEUTRAL 0,38 · SUPPORT 4,75 · CONFLICT 6,64; C: GAP 2,11 · METHOD_ADOPTION 10 |
| Grad accum | 4–8 (batch efectivo ≥8) | Estabilidad en 8GB |

**Formato de salida (inalterado):** `<pensamiento>` (traza, spans verbatim) + `<salida_json>` (solo etiquetas canónicas ASCII). Prohibido emitir variantes libres.

---

## 5. Gates (inalterados, con fecha de aplicación)

| Gate | Criterio | Instrumento |
|---|---|---|
| **G1** Auditoría forense | Dataset entrenable, sin colapso de clase, sin inválidos | `tools/auditor_forense_dataset.py` (re-aplicar al dataset humano) |
| **G2** κ humano | κ ≥ 0,60 por eje sobre 36 casos ES/PT/EN | `control_36` + `control_protocolo_12`; ejes que fallen **salen del target** |
| **G3** LoRA vs base | LoRA debe superar al base zero-shot en el test congelado | Test congelado estratificado (Duque 333 + control_36) |

**Cambio respecto a V3:** G2 ya no valida al motor contra el humano (fracasó, es el diagnóstico); **valida que el humano sea consistente consigo mismo** (test-retest sobre la misma muestra) y que la interfaz capture esa decisión. El motor queda como proponente, no como juez.

---

## 6. Secuencia de ejecución (hitos)

| # | Hito | Entrega | Depende de |
|---|---|---|---|
| M1 | Dry-run Qwen3-4B + seq 2048 en 8GB | VRAM/gradientes OK o ajuste de base | — |
| M2 | Prueba ES/PT/EN del tokenizador y formato | 10 prompts correctos | M1 |
| M3 | Completar bloque PT (13 PDFs) | Markdown + inventario actualizado | — |
| M4 | Diseñar captura de deltas en la UI (modo supervisado) | Cada propuesta→corrección→etiqueta persistida | — |
| M5 | Primera pasada humana sobre pre-lleno T2+T3 | Gold humano inicial (target ≥50 filas/eje) | M3, M4 |
| M6 | Test-retest G2 (consistencia humana) | κ ≥ 0,60 por eje o eje fuera de target | M5 |
| M7 | Conjunto de entrenamiento ChatML V5 | `thinkuy_v5_*.jsonl` + hash en `DATASETS.md` | M5, M6 |
| M8 | Entrenamiento QLoRA V5 | Adaptadores `models/thinkuy_v5_qwen3_lora` | M7, G1 |
| M9 | Gate 3 (LoRA vs base, test congelado) | Tabla de contingencia por eje + INVALID_OUTPUT | M8 |
| M10 | Integración al pipeline (cribado/PCC, vecindario/T3) | Modelo sirviendo propuestas en la UI | M9, G3 |

---

## 7. Riesgos y mitigación

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| G2 (motor) no reproducible en T3 | Confirmado (κ 0,10) | Alto | Fuente de verdad = humano arbitrado vía UI (§1) |
| Volumen de corrección humana insuficiente | Media | Alto | Pre-lleno con motor+SLM para que el humano corrija, no redacte |
| 4B no cabe en 8GB con seq 2048 | Baja | Medio | Reducir seq a 1536 o r a 8; medir en M1 |
| PT < 30% | Media | Medio | Bloque PRISMA_JBI + corpus de áreas ibéricas/brasileñas |
| `OWN_CLAIM`/`METHOD_ADOPTION` con n mínimo | Alta | Bajo | Fuera del target; metadato (§3 #5) |
| Modelo aprende formato `<pensamiento>` pero etiqueta mal | Media | Medio | G3 exige superar base zero-shot; si no, no se integra |

---

## 8. Qué NO se entrena (perímetro explícito)

- **NO** redacción del informe sistemático de 7 fases (Agente A.1 se alimenta de `charting_verificado`, no de generación libre).
- **NO** completar resúmenes (escalera de ingesta, prohibido).
- **NO** etiquetado T3 autónomo sin validación (la etiqueta final es humana).
- **NO** R2/R3 como target hasta recalibrar (κ < 0,6).
- **NO** taxonomía de disciplinas desde Wikidata (guardada para metadato).

---

## 9. Próximos pasos inmediatos (para investigación)

1. Descargar `Qwen3-4B-Instruct-2507` GGUF y correr M1 (dry-run seq 2048).
2. Revisar `t2_pcc.jsonl` y `dataset_balanceado.jsonl` para confirmar pre-lleno utilizable por la UI.
3. Completar los 13 PDFs PT pendientes de PRISMA_JBI.
4. Inventariar cuántas correcciones humanas por eje son viables por sesión (calibrar tamaño de target).
5. Decidir e implementar la captura de deltas en la interfaz (es el cuello de botella del plan).