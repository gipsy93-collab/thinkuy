2\. El Prompt de Anotación "Gold Standard" (Para los primeros 10-20 textos)

Una vez que el script genere el dataset\_bruto\_extraido.json, usted (o un LLM grande como Claude 3.5 Sonnet / GPT-4o asistido por usted) debe anotar estos bloques.

Este prompt está diseñado para generar exactamente el formato que su modelo pequeño (Gemma 4 2B o Qwen) necesita aprender mediante QLoRA.

A. Prompt para Paso 0 y 1 (Usando el resumen extraído):

&nbsp;

&nbsp;

Eres el Módulo Epistémico Thinkuy. Analiza el siguiente resumen de una revisión sistemática o scoping review iberoamericana.

&nbsp;

RESUMEN:

{insertar\_aquí\_el\_resumen\_extraído}

&nbsp;

TAREA:

1\. Clasifica el ROL METODOLÓGICO principal del estudio.

2\. Identifica la TRADICIÓN EPISTÉMICA desde la que opera (ej: Hegemónica/Positivista, Medicina Social/Salud Colectiva, Pensamiento Decolonial, Ecología de Saberes, Apropiación Social del Conocimiento, Crítica Latinoamericana).

3\. Determina si cumple criterios básicos de inclusión para una revisión PRISMA/JBI (justificación breve).

&nbsp;

FORMATO DE SALIDA OBLIGATORIO:

\<pensamiento\>

1\. Método declarado: \[Describir brevemente el diseño y protocolo, ej: Scoping review JBI\].

2\. Epistemología: \[Identificar tradición y justificar con 1-2 palabras clave del texto\].

3\. Descarte: \[¿Por qué NO es otra categoría? ej: No es empírico primario porque es una síntesis\].

\</pensamiento\>

\<salida\_json\>

{

&nbsp;&nbsp;"rol\_metodologico": "\[Seminal | Síntesis\_Review | Teórico\_Framework | Metodológico | Empírico\]",

&nbsp;&nbsp;"tradicion\_epistemica": "\[Hegemónica | Medicina Social | Decolonial | Ecología de Saberes | Apropiación Social | Crítica Latinoamericana | No especificada\]",

&nbsp;&nbsp;"aptitud\_prisma": "\[Apto | Excluir | Dudoso\]",

&nbsp;&nbsp;"motivo": "\[Máximo 15 palabras\]"

}

\</salida\_json\>

&nbsp;

\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

&nbsp;

&nbsp;

&nbsp;

&nbsp;

&nbsp;

&nbsp;

&nbsp;

B. Prompt para Paso 2 (Usando la metodologia extraída):

&nbsp;

Eres el Módulo de Extracción JBI (Paso 2). Analiza la siguiente sección de metodología de una revisión.

&nbsp;

METODOLOGÍA:

{insertar\_aquí\_la\_seccion\_metodologia}

&nbsp;

TAREA:

Extrae la matriz PCC (Población, Concepto, Contexto) y los detalles metodológicos clave de forma literal y estructurada.

&nbsp;

FORMATO DE SALIDA OBLIGATORIO:

\<pensamiento\>

Analizo la sección para identificar: 1\) Quiénes son los sujetos/unidades (P), 2\) Qué fenómeno se estudia (C), 3\) Dónde/cuándo (C), 4\) Cómo se hizo (Diseño, bases de datos, criterios).

\</pensamiento\>

\<salida\_json\>

{

&nbsp;&nbsp;"poblacion": "\[Descripción literal o 'No especificado'\]",

&nbsp;&nbsp;"concepto": "\[Fenómeno central\]",

&nbsp;&nbsp;"contexto": "\[Geográfico, temporal o institucional\]",

&nbsp;&nbsp;"diseno": "\[ej: Scoping review, Revisión sistemática, Mixto\]",

&nbsp;&nbsp;"criterios\_inclusion": "\[Resumen en 10 palabras\]"

}

\</salida\_json\>

&nbsp;

&nbsp;

\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

&nbsp;

C. Prompt para Paso 3 (Usando los bloques\_citacion extraídos):

&nbsp;

Eres el Módulo de Auditoría de Citas (Paso 3). Analiza el siguiente párrafo extraído del cuerpo de un artículo.

&nbsp;

PÁRRAFO:

{insertar\_aquí\_el\_bloque\_de\_citacion}

&nbsp;

TAREA:

Identifica la relación epistémica que el autor estable con las obras citadas.

&nbsp;

FORMATO DE SALIDA OBLIGATORIO:

\<pensamiento\>

1\. Autores citados: \[Listar\].

2\. Relación: ¿El autor usa la cita para apoyar (consenso), criticar (disenso), tomar un método (adopción) o solo mencionar (contexto)?

3\. Evidencia en el texto: \[Citar fragmento clave que demuestre la relación\].

\</pensamiento\>

\<salida\_json\>

{

&nbsp;&nbsp;"autores\_citados": \["Autor1, Año", "Autor2, Año"\],

&nbsp;&nbsp;"tipo\_relacion": "\[Consenso | Disenso | Adopcion\_Metodologica | Mencion\_Contextual\]",

&nbsp;&nbsp;"claim\_extraido": "\[La afirmación literal que el autor hace sobre la cita, máx 20 palabras\]"

}

\</salida\_json\>

&nbsp;