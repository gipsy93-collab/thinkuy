# Patrón dorado de Thinkuy: qué se mide, cómo se anota y con qué umbrales

> **Para qué existe:** hoy sabemos que la herramienta *funciona*; no podemos demostrar
> *cuánto*. Sin un patrón dorado, cualquier afirmación de rigor académico es una opinión.
> **Fecha de creación:** 18-09-2026 · **Herramienta:** `tools/patron_dorado.py`

---

## 1. Tres capas, tres objetos distintos

Mezclarlas sería inmanejable: se mide cada una por separado y con su propia métrica.

| Capa | Qué mide | Material | Estado |
| :--- | :--- | :--- | :--- |
| **A — Recuperación** | ¿Encuentra lo que existe y declara lo que no? | **40 consultas** en 5 niveles | Material listo, **pendiente de anotar** |
| **B — Extracción de metadatos** | ¿Extrae el dato correcto y literal? | **15 fichas reales** en 4 niveles | Material listo, **pendiente de anotar** |
| **C — Juicio discursivo** | ¿Es reproducible el criterio? | `control_36` + `control_protocolo_12` con κ | **Ya existe y ya se midió** (Gate 2) |

---

## 2. Capa A — Recuperación

### Los cinco niveles de complejidad

| Nivel | Qué es | N | Qué mide |
| :--- | :--- | --: | :--- |
| **N1** | Monoconcepto explícito (`altmetría`) | 8 | Precisión básica |
| **N2** | Multiconcepto con sinónimos (`altmetría en revistas iberoamericanas`) | 8 | Expansión léxica y vocabulario controlado |
| **N3** | Pregunta larga en lenguaje natural (≥15 palabras) | 8 | Que **no** devuelva cero y que **declare** la consulta usada |
| **N4** | Translengua o interdisciplinar (`ciência aberta` / `open science`) | 8 | Cobertura ES/PT y tope de inglés |
| **N5** | **Fuera de alcance (control de relevancia)** | 8 | Que **declare** que no cubre la consulta, no que presente resultados irrelevantes como vinculados |

Mitad en español, mitad en portugués (el nicho), con presencia de inglés solo en N4.

### Cómo se anota (`data/gold_standard/A_consultas.tsv`)

Por cada consulta, **antes de mirar la salida de la herramienta**:

1. `linea_base_total`: cuántos resultados devuelve tu búsqueda propia en Scopus/WoS/Scholar.
2. `linea_base_dois_relevantes`: los DOI que **tú** consideras pertinentes (hasta 20, separados por `;`).
3. Después, ejecuta la consulta en la herramienta y anota:
   - `consulta_usada_por_la_herramienta`: lo que declara haber buscado.
   - `resulto_cero`: `SI`/`NO`.
   - `se_relajo`: `SI`/`NO`.
4. `notas`: cualquier cosa que debas recordar (p. ej. «la herramienta entendió X»).

### Métricas y umbrales **pre-registrados**

| Métrica | Cómo se calcula | Umbral |
| :--- | :--- | :--- |
| **precisión@10** | De los 10 primeros, cuántos están en tu lista de relevantes | ≥ 0,50 en N1–N2 |
| **recall@k** | Cuántos de tus relevantes aparecen en los k devueltos | ≥ 0,40 en N1–N2 |
| **tasa de cero resultados** | Consultas sin resultados (N1–N4) | ≤ 0,05 |
| **relajación declarada** | Casos donde la consulta se amplió **y se declaró** | 1,00 (siempre declarado) |
| **N5 — precisión@10** | Relevancia de los 10 primeros en consultas fuera de alcance | **≤ 0,10** |
| **N5 — honestidad** | ¿La herramienta declara que no cubre la consulta? | **obligatorio**; si presenta los resultados como «vinculados a X», **FALLA** |

> **Hallazgo medido antes de congelar (18-09-2026):** las 8 consultas de N5 **no** devuelven
> vacío —el motor encuentra coincidencias laxas por relevancia (3 a 273 obras)—. Por eso el
> control **no mide el vacío**, mide la **honestidad**: si la herramienta presenta como
> «vinculados a tu consulta» resultados que no lo están, falla. Este hallazgo se registró
> *antes* de la anotación, para no ajustar el criterio después de ver los resultados.

---

## 3. Capa B — Extracción de metadatos

### Los cuatro niveles (clasificados por lo medido, no por lo supuesto)

| Nivel | Qué es | N |
| :--- | :--- | --: |
| **B1** | Metaetiquetas completas (`citation_abstract` — SciELO) | 2 |
| **B2** | Dublin Core (`DC.Description` — OJS) | 6 |
| **B3** | Sin resumen en la ficha (solo PDF declarado o página con JavaScript) | 6 |
| **B4** | Página caída o muro (control) | 1 (+1 de control adicional) |

### Cómo se anota (`data/gold_standard/B_fichas.tsv`)

Abriendo cada URL y leyendo la ficha o el PDF original, escribe la **verdad**:
título, autores, año, revista, DOI, y el **resumen tal cual aparece** (verbatim).
Y en `tiene_resumen_real`: `SI`/`NO` — **hay fichas de revistas antiguas que no tienen resumen**
(medido: los 7 artículos de *Alteridad* 2008-2011 no lo tienen, y un modelo llegó a inventarlo).

### Métricas y umbrales

| Métrica | Cómo se calcula | Umbral |
| :--- | :--- | :--- |
| **exactitud por campo** | Campos correctos / campos con verdad | ≥ 0,95 |
| **fidelidad verbatim** | Fracción del resumen devuelto que aparece literal (`tools/auditar_fidelidad.py`) | ≥ 0,95 |
| **tasa de invención** | Campos con contenido que **no** está en la fuente | **0,00** (tolerancia cero) |
| **declaración de vacío** | En B4, ¿declaró que no hay resumen? | obligatorio |

---

## 4. Reglas del protocolo (no negociables)

1. **Anotación a ciegas.** La verdad se escribe **antes** de consultar la salida de la herramienta.
2. **Sin fallbacks complacientes.** Una salida vacía, rota o fuera de taxonomía cuenta como
   **fallo estricto** (0 puntos). No existe el «se interpreta como».
3. **Umbrales pre-registrados.** No se ajustan después de ver los resultados.
4. **Congelación.** `protocolo.json` guarda las huellas SHA-256 del material. Si el material
   cambia, la huella cambia y hay que declararlo.
5. **Si el patrón no se anota, no se reporta ninguna métrica.** El evaluador lo dice
   explícitamente en lugar de estimar.

---

## 5. Coste estimado para ti

| Tarea | Volumen | Tiempo aproximado |
| :--- | :--- | :--- |
| Capa A: búsqueda propia + juicio | 40 consultas × ~20 resultados | 4–6 h |
| Capa B: leer ficha/PDF y escribir la verdad | 15 fichas | 1,5–2 h |
| Capa C: ya está hecha | — | 0 |

---

## 6. Cómo se ejecuta

```bash
# El material ya está generado y congelado
python tools/patron_dorado.py --generar     # vuelve a generarlo (cambia la huella: declararlo)

# Cuando hayas anotado A_consultas.tsv:
python tools/patron_dorado.py --evaluar
```

La evaluación **no inventa**: si las columnas de verdad están vacías, lo dice.
