# Opciones para lograr un modelo que clasifique postura

> Fecha: 18-09-2026 · Pregunta del IP: *«¿cómo logramos un modelo que clasifique postura? Deme todas las posibles opciones. No quiero que sea determinista e infalible, pero sí que sea de ayuda, con sus "posibles", y que el investigador determine.»*

## 0. El dato que reorienta todo

Se midió la pregunta **binaria** («¿el autor toma postura?», sí/no) reutilizando tus 34 anotaciones, sin pedirte nada nuevo:

| Métrica | Valor |
| :--- | ---: |
| Acuerdo observado | 73,5 % |
| κ | 0,061 |
| Casos donde el humano ve postura | **8** |
| Casos donde la regla ve postura | **3** |
| **Posturas humanas que la regla NO detecta** | **7 de 8 (87,5 %)** |
| Falsos positivos de la regla | 2 |

**Conclusión:** el cuello de botella **no es la taxonomía ni la dirección** del juicio. Es la **detección**: la regla no ve la postura. Y no es un problema de etiquetas — es que reconocer que una oración expresa una postura **requiere entender la oración**.

Eso, precisamente, es una tarea de modelo. Las opciones se ordenan según cómo atacan la detección.

---

## A. Sin entrenar (reorganizar lo que ya hay)

| # | Opción | Cómo funciona | Coste | Techo |
| :--- | :--- | :--- | :--- | :--- |
| **A1** | **Lexicón de postura derivado del corpus** | Extraer automáticamente todos los verbos que aparecen junto a una cita (`VERBO + Autor (año)`), y pedirte que marques sí/no «¿este verbo expresa apoyo / crítica?». Es una tarea de **dos segundos por verbo**, no de anotar oraciones | ~1 h tuya | Medio: la lista crece, pero sigue siendo lista |
| **A2** | **LLM grande solo para SELECCIONAR** | El motor determinista entrega candidatos (garantizados como literales); un LLM grande elige **cuál fragmento expresa la postura** y devuelve el span. La **etiqueta** la sigue poniendo la tabla cerrada | Bajo (una pasada API) | Alto: el LLM hace lo que sabe hacer, y la etiqueta queda auditable |
| **A3** | **Panel con desacuerdos visibles** | Regla + LLM local + evidencia, mostrados **por separado**. Cuando no coinciden, el desacuerdo se muestra al investigador | Medio | Alto para confianza: el desacuerdo es informativo |
| **A4** | **Reencuadrar la salida como ranking** | No clasificar: **ordenar** las citas por probabilidad de contener postura y que el investigador revise las N primeras. Es el mismo principio que el ranker de PRISMA que ya existe | Bajo | Alto: la métrica pasa a ser precisión@N, que es lo que importa |

---

## B. Entrenar, con etiquetas verificables

| # | Opción | Cómo funciona | Coste | Techo |
| :--- | :--- | :--- | :--- | :--- |
| **B1** | **Entrenar la EXTRACCIÓN del span de postura** | El target deja de ser «clase SUPPORT/CONFLICT» y pasa a ser «devuelve el fragmento mínimo que expresa la postura, o `NINGUNO`». Etiqueta **verificable**: el fragmento está o no está en el texto. La clase la pone después la tabla cerrada | Anotar ~100-150 spans (2-3 h tuyas) | **Alto**: es extractivo, y el v2 ya demostró 96,9 % de fidelidad verbatim en modelos pequeños |
| **B2** | **Destilación filtrada por aceptación** | Un LLM grande propone postura + evidencia en todo el corpus → **tú aceptas o rechazas** en una revisión rápida → **las aceptadas son el dataset** del SLM local. Las etiquetas quedan human-verificadas por construcción | Revisión rápida (tu tiempo, escalable) | **Alto**: es la vía más limpia para tener etiquetas buenas sin anotar desde cero |
| **B3** | **Dataset público de intención de cita** | Existen corpus anotados por equipos con acuerdo publicado: **ACL-ARC** y **SciCite** (intención de cita: background, uses, motivation, extends, compare/contrast). Si tus ejes se **mapean** a esas categorías, hay miles de ejemplos para entrenar sin anotar nada | Medio (mapeo de taxonomías) | Medio-alto: riesgo de cambio de dominio (son papers en inglés de CS) |
| **B4** | **Entrenar la pregunta binaria** | «¿hay postura? sí/no». Reutiliza tus anotaciones recodificadas | **Cero** | Bajo hoy: κ 0,061 por falta de detección, no por la pregunta |

---

## C. Cambiar el constructo (donde está la ambigüedad real)

| # | Opción | Cómo funciona | Coste | Techo |
| :--- | :--- | :--- | :--- | :--- |
| **C1** | **Objetivo solo los eventos nítidos** | Perseguir únicamente **apoyo explícito** y **disenso explícito** (los casos donde el autor realmente se posiciona), y tratar todo lo demás como «sin postura». Tolerar baja cobertura: una sugerencia perdida es invisible, una sugerencia falsa cuesta dos segundos | Cero (remedir con lo que hay) | Alto en precisión, bajo en cobertura |
| **C2** | **Medir con aceptación, no con κ** | La métrica deja de ser κ contra un patrón y pasa a ser **tasa de aceptación del investigador** y **precisión@N**. Es la métrica correcta para una capa de sugerencias | Cero | — |

---

## Recomendación: A2 + B1 + C2

**Combinación coherente, en este orden:**

1. **A2 — primero, ya.** Un LLM grande (una pasada) selecciona fragmentos candidatos. No entrena nada y ataca directamente el fallo medido (detección 1/8). Con el span a la vista, tú validas en segundos.
2. **B1 — después.** Esos fragmentos validados se convierten en el dataset de **extracción de spans** para el SLM local: tarea extractiva, etiquetas verificables, y es lo que los modelos pequeños sí hacen bien (fidelidad verbatim 96,9 % en el v2).
3. **C2 — siempre.** La métrica es tu tasa de aceptación, no κ. La frontera del entrenamiento sigue siendo el Gate 3 (superar al base), pero el éxito del *producto* se mide por si te ahorra trabajo, no por un coeficiente.

**Por qué no la vía anterior:** entrenar directamente la clase (SUPPORT/CONFLICT/NEUTRAL) exige etiquetas de clase que un humano no reproduce de forma estable (κ 0,10). Entrenar la **extracción** del fragmento elude ese problema: el fragmento es un hecho, no una interpretación.

**Lo que esto pide de ti, en total:** una revisión rápida de propuestas (A2/B2) y, si vamos a B1, marcar ~100-150 fragmentos — una tarea mucho más ligera y más objetiva que etiquetar oraciones.

**Decisión pendiente:** si el LLM de la opción A2 va por API (rápido, coste bajo por una sola pasada) o local (soberanía total, más lento). Ambas son compatibles con el resto.
