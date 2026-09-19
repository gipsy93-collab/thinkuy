# Qué lograríamos y qué no al entrenar el modelo (nota de decisión)

> Fecha: 18-09-2026 · Basada en el resultado del Gate 2 (Hito 30 de la bitácora).
> Pregunta del IP: *"¿Tiene sentido entrenarlo? ¿Sería un aporte interesante como herramienta metodológica?"*

## 1. Qué SÍ y qué NO se puede entrenar hoy

| Tarea | ¿Etiquetas verificadas? | Qué ganaríamos | Qué NO ganaríamos |
| :--- | :--- | :--- | :--- |
| **Formato de salida y taxonomía fija** (JSON estable, códigos canónicos) | ✅ Sí: la conformidad es comprobable | Un modelo pequeño que deja de inventar variantes (`"REVIEW_SYSTEMATIC"`) y emite siempre la estructura esperada | Ninguna capacidad de juicio. Solo disciplina de formato |
| **Extracción literal del claim** (verbatim) | ✅ Sí: se verifica que el fragmento sea subcadena del texto | Que no parafrasee ni «cosa» palabras ajenas (el fallo que tuvo Ministral 3B) | No decide si esa cita importa |
| **T2 — Matriz PCC (selección de fragmentos)** | ⚠️ Parcial: el grounding es verbatim por construcción, falta su Gate 2 humano | Cobertura de redacciones que la regla no contempla | No garantiza que el fragmento sea el correcto |
| **R1 — guía de reporte declarada** | ✅ Sí: κ = 0,654 | Cierto poder de generalización ante formulaciones no listadas | No mejora el techo de la regla |
| **A/B/C — postura, certeza, función retórica** | ❌ **No**: κ 0,100 / −0,043 / 0,371 | **Nada.** El modelo aprendería la distribución de etiquetas de una regla que un humano no reproduce | Todo |
| **R2 / R3 — marco de conducción y tipo de síntesis** | ❌ No: κ 0,333 / 0,167 | Nada por ahora | Todo |
| **Mapeo epistemológico y vecindarios de autores** | — | **No es tarea del modelo.** Es grafo determinista: co-citación, Union-Find, Main Path (SPC). Ya funciona y no necesita entrenamiento | — |

## 2. La distinción que decide todo

El IP plantea, con razón, que el modelo **no es determinista ni tiene la verdad**: es una ayuda, y el investigador valida. De ahí las etiquetas *"posible consenso"*, *"posible disenso"*.

Esa observación es correcta, pero aplica a **dos momentos distintos**, y solo a uno le baja el listón:

| Momento | Criterio | Por qué |
| :--- | :--- | :--- |
| **Uso** (inferencia) | «Posible X» con la evidencia a la vista | Protege al investigador y a la herramienta. El listón es bajo y está bien que lo sea |
| **Entrenamiento** | La etiqueta debe ser correcta | El modelo **aprende la distribución** de las etiquetas. Si son malas, produce «posibles X» malos **con seguridad** |

Evidencia propia: un LoRA entrenado sobre etiquetas sin verificar rindió **28,23 % frente al 46,55 % del modelo base**. El fine-tuning con etiquetas ruidosas **empeora** el modelo; no es neutro.

## 3. El riesgo práctico que hay que evitar

Si el modelo se usa para **aumentar cobertura** con baja precisión, el trabajo del investigador **aumenta** en vez de disminuir: tendría que revisar sugerencias malas. Es el modo de falla típico de las herramientas de «IA para investigar».

De ahí una consecuencia de diseño: la métrica correcta para esta capa **no es κ contra un patrón dorado**, sino la **tasa de aceptación de sugerencias** por parte del investigador, siempre con la evidencia visible. Eso se puede medir y es lo que importa en el producto.

## 4. ¿Tiene sentido entrenarlo? Sí, pero por otra razón

La motivación original era «clasificar la postura epistémica». La evidencia dice que eso no es entrenable hoy. Lo que **sí** justifica un fine-tuning pequeño y local:

1. **Disciplina de formato y taxonomía** (salida parseable al 100 %, sin variantes libres).
2. **Fidelidad literal** (extracción verbatim, sin paráfrasis).
3. **R1** (guía de reporte), el único eje de juicio que superó el umbral.

Y todo ello en un modelo **local y soberano**, que es coherente con la tesis del proyecto (no depender de infraestructura rentada).

## 5. ¿Es un aporte metodológico interesante? Sí, y no es el modelo

El aporte está en tres cosas que ya existen y no dependen del entrenamiento:

1. **El procedimiento auditable de etiquetado**: reglas deterministas con listas cerradas ES/PT/EN, cola explícita de ambigüedad, y un **gate humano con κ por eje** que decide qué entra al target y qué no. Esto es escaso en herramientas de investigación: la mayoría son cajas negras.
2. **El resultado negativo, que es publicable**: una taxonomía de postura epistémica que parece obvia **no es reproducible por reglas a escala** en un corpus iberoamericano de revisiones (κ 0,10-0,37), y el intento de corregirla oscila entre sobre-atribuir y no detectar. Es un hallazgo sobre la dificultad real de automatizar el análisis de postura, no sobre la incompetencia de un equipo.
3. **El corpus y el patrón humano**: 196 artículos únicos, deduplicados, segmentados, con idiomas balanceados (ES 48 % / EN 29,6 % / PT 21,9 %) y **48 respuestas humanas** que sirven como patrón permanente para medir cualquier regla futura.

Y un cuarto, de mercado: **casi no existen herramientas para el diamante iberoamericano** (Redalyc/SciELO/OJS). El diferenciador no es el modelo; es que **cada sugerencia sea trazable a un marcador literal del texto y esté validada por un humano**. Eso es exactamente lo que el mercado de «IA para investigación» no ofrece.

## 6. Recomendación

**Entrenar un modelo reducido** —solo formato, verbatim, R1 y T2— porque es barato, es coherente con la filosofía y no arrastra etiquetas no verificadas. **No entrenar** postura, certeza ni función retórica: se quedan como capa determinista de **baja confianza**, con la evidencia visible y la etiqueta «posible», que es lo que el diseño del IP ya preveía.

**Y declararlo así en el producto y en la tesis**: el motor determinista decide lo que se puede decidir; el modelo propone lo que se puede proponer; el investigador valida. La frontera entre ambos no se elige por gusto: **se mide con κ**.
