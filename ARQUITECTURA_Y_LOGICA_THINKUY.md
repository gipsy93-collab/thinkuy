# Thinkuy — Arquitectura, Lógica de Funcionamiento y Diagnóstico Epistemológico

> **Tinkuy Lab — Radar de Comunicación Científica y Suite de Revisión Sistemática**  
> **Versión**: 5.25 (Septiembre 2026)  
> **Documento de Referencia Técnica y Metodológica para el Investigador**

---

## 1. Misión y Filosofía: Apoyo, Nunca Reemplazo

Thinkuy fue diseñado bajo un principio ético y epistemológico irrenunciable: **la inteligencia artificial es una prótesis analítica de apoyo al investigador, jamás su sustituto**.

En el campo de las revisiones sistemáticas de la literatura (RSL) y las revisiones de alcance (*scoping reviews* bajo marcos PRISMA-ScR y JBI), la delegación ciega en modelos generativos produce **alucinaciones académicas catastróficas**: artículos inventados, atribuciones espurias y falsas sensaciones de consenso. Thinkuy invierte esta lógica:

1. **Evidencia Primero (*Evidence-First*)**: La IA generativa solo opera sobre registros previamente recuperados, indexados y validados en una base de datos local verificable (SQLite).
2. **Humildad Epistemológica**: Las clasificaciones cualitativas nunca se presentan como verdades absolutas. El sistema formula hipótesis de trabajo bajo las etiquetas de **«posible consenso»**, **«posible disenso»**, **«posible adopción metodológica»** y **«posible mención contextual»**, otorgando siempre al investigador la soberanía y la última palabra de validación o corrección.
3. **Transparencia Trazable**: Cada afirmación sintetizada enlaza con el párrafo exacto, la oración literal y el DOI de origen dentro del PDF analizado.

---

## 2. El Gran Cuello de Botella: Proximidad Epistémica Real vs. Grafos Ciegos

### 2.1. El límite de las herramientas cuantitativas tradicionales
Plataformas consagradas como VOSviewer, Connected Papers, Scopus o Research Rabbit construyen **grafos de citación ciegos**:
- Registran que el **Artículo A cita al Artículo B**.
- Pero son incapaces de descifrar **¿CÓMO lo cita? ¿Para qué lo cita? ¿Qué afirma A sobre B?**
- Un artículo puede tener 500 citas porque su metodología fue demolida por la comunidad científica, y un grafo tradicional lo presentará falsamente como un "nodo de enorme autoridad y consenso".

### 2.2. El Grafo Dialógico de Evidencia de Thinkuy
Para resolver este cuello de botella, Thinkuy introduce la **Proximidad Epistémica Cualitativa**:
1. **Extracción Textual Profunda (`text_extractor.py`)**: Utiliza PyMuPDF para segmentar el artículo en sus secciones funcionales (`introduction`, `methods`, `results`, `discussion`, `conclusion`), aislando la lista final de referencias.
2. **Localización en el Cuerpo del Manuscrito**: Mediante un parseador especializado (`parse_reference_entry`), extrae el autor principal y el año de cada entrada bibliográfica, rastreando los párrafos del cuerpo donde efectivamente se inserta la cita (ej. *«Como sostiene Habermas (1989)...»*, *«García et al. (2021) demuestran...»*).
3. **Extracción de la Afirmación Literal (*Claim*)**: Extrae la oración exacta del texto donde se formula la proposición. Si hay un LLM local conectado, extrae el fragmento asertivo (máximo 40 palabras) y ejecuta una verificación estricta anti-alucinación (`_verbatim`: el claim debe coincidir letra por letra con el pasaje). Si el LLM está apagado, la heurística preserva la oración textual completa para que el investigador nunca pierda el contexto.
4. **Mapeo de Funciones Retóricas Tentativas**:
   - **Posible consenso** (`supporting_or_agreement`): El autor parece confirmar, respaldar o extender los hallazgos previos.
   - **Posible disenso** (`contrasting_or_refuting`): El autor contrasta, cuestiona, refuta o matiza la postura previa.
   - **Posible adopción metodológica** (`methodological_adoption`): El autor adopta un instrumento, escala, software o protocolo.
   - **Posible mención contextual** (`neutral_or_mention`): Mención de estado del arte o antecedentes sin postura explícita.
5. **Cola de Validación Humana (*Human-in-the-Loop*)**: En la interfaz PWA, el investigador puede validar (`✓ Validar`), reclasificar (`✎ Corregir`) o descartar (`✕ Rechazar`) cada contexto de citación, alimentando una base de conocimiento curada y reproducible.

---

## 3. Curación de Contenido y Eliminación de Doblajes (*Deduplicación Difusa*)

Un problema severo advertido por los expertos en revisiones sistemáticas es la **proliferación de doblajes**:
- El mismo estudio aparece primero como *preprint* (en arXiv, bioRxiv, SocArXiv o Research Square) y meses después como artículo formal en una revista indexada con diferente DOI.
- O bien, el título sufre ligeras alteraciones ortográficas, diferencias de mayúsculas, signos de puntuación o traducciones bilingües.

Thinkuy combate los doblajes mediante un **pipeline de deduplicación en tres niveles**:
1. **Normalización Canónica de DOIs**: Limpieza de prefijos (`https://doi.org/`, `http://dx.doi.org/`), conversión a minúsculas y eliminación de sufijos espurios.
2. **Deduplicación Difusa por Título (*Fuzzy String Matching*)**:
   - Normalización fonética y de caracteres (remoción de acentos, signos, doble espacios y palabras vacías).
   - Cálculo de similitud mediante **Distancia de Levenshtein** y **Coeficiente de Jaccard** sobre n-gramas de palabras con umbral $\ge 0.88$.
3. **Consolidación de Versiones**:
   - Si se detecta que un registro es un preprint y otro es la versión de registro (*Version of Record - VoR*), el sistema prioriza la versión evaluada por pares pero conserva los metadatos de acceso abierto del repositorio.

---

## 4. Comparativa Técnica Exhaustiva: Thinkuy vs. ASReview Lab

Tras la inspección forense en profundidad del contenedor Docker `asreview-lab` (puerto 5000), se desglosa con exactitud el alcance de ambas herramientas:

| Dimensión | ASReview Lab (Utrecht University) | Thinkuy (Tinkuy Lab) |
| :--- | :--- | :--- |
| **Objetivo Primario** | Reordenamiento inteligente de títulos/resúmenes para reducir el tiempo de lectura humana. | Suite integral de revisión de alcance, mapeo dialógico y síntesis epistémica de evidencia. |
| **Fase en la que actúa** | Exclusivamente en la **Fase de Cribado (Screening)** de títulos y resúmenes. | **Ciclo Completo**: Búsqueda abierta, Cribado, Data Charting JBI de PDFs completos y Síntesis. |
| **Modelo de Clasificación** | **TF-IDF + LinearSVC** (SVM lineal por defecto) con muestreo activo *Max* y balanceador de clases. | **Híbrido Heurístico-Semántico + LLM Local** (embeddings OpenAlex + clasificación retórica contextual). |
| **Búsqueda Bibliográfica** | **No tiene**: El usuario debe traer su archivo RIS/CSV exportado de Scopus/WoS. | **Integrada y Abierta**: Consulta directa a OpenAlex, Crossref y portales OJS con priorización del Sur Global. |
| **Análisis de Texto Completo (PDFs)** | **No tiene**: Solo lee título y abstract. Jamás examina el cuerpo del PDF. | **Nativo con PyMuPDF**: Segmentación de secciones, lectura de párrafos y extracción de oraciones. |
| **Grafo de Citaciones** | **No tiene**: Ignora si los artículos se citan entre sí. | **Grafo Dialógico de Evidencia**: Distingue posibles consensos, disensos y trayectorias principales (Main Path SPC). |
| **Data Charting JBI (PCC)** | **No tiene**: No extrae variables de población, concepto, contexto ni métodos. | **Automatizado con SQLite**: Tabla estructurada de variables verificadas artículo por artículo. |
| **Síntesis PRISMA** | **No tiene**: Termina cuando el usuario decide parar de leer resúmenes. | **Agente A.1 Metodólogo**: Redacción de síntesis PRISMA 2020 con tabla de evidencia y diagrama de flujo. |
| **Soberanía y Privacidad** | Servidor local Flask/Python (`asreview-lab`). | **Local-First PWA**: Encriptación en cliente (AES-GCM 256 bits) + backend local en SQLite. |

> **Conclusión del contraste**: ASReview es un excelente motor especializado de *Active Learning* para descartar resúmenes irrelevantes en medicina clínica masiva (ej. 10.000 títulos). Thinkuy es una **estación de trabajo epistémica completa** diseñada para la investigación cualitativa y mixta, donde lo crucial no es solo contar cuántos artículos hay, sino **comprender cómo debaten entre sí en el texto**.

---

## 5. El Pipeline Integral de Thinkuy en 4 Fases

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 PIPELINE THINKUY                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘

  [Paso 0: Clasificación Epistémica]
         │
         ▼ (OpenAlex multiescalar + SUR_GLOBAL_CODES + Works-First 2022-2026)
  [Paso 1: Cribado Asistido PRISMA] ──► Deduplicación Difusa (Levenshtein / Anti-Doblajes)
         │                          ──► Human-in-the-loop (Motivos explícitos de exclusión)
         ▼
  [Paso 2: Data Charting JBI (PDFs)] ──► PyMuPDF: Segmenta texto, aísla bibliografía
         │                           ──► parse_reference_entry: Autor/Año en cuerpo
         │                           ──► Afirmación literal (Claim verbatim)
         │                           ──► Matriz PCC persistida en SQLite
         ▼
  [Paso 3: Síntesis & Rigor Metodológico]
         │
         ▼ (Agente A.1 Metodólogo alimentado solo con charting_verificado)
  [Reporte PRISMA 2020 + Matriz Dialógica: Posible Consenso / Posible Disenso]
```

### 5.1. Paso 0: Clasificación Epistémica y Mapeo de Frontera
- **Muestreo Temático Abierto**: Conexión con la API de OpenAlex sin requerir suscripciones comerciales privativas (Scopus/WoS).
- **Fórmula de Velocidad Temática Relativa**:
  $$\text{Velocidad} = \frac{V_r / 2}{V_b / 3} \quad (\text{con } V_r \ge 5)$$
  Donde $V_r$ es el volumen de producción reciente (últimos 2 años) y $V_b$ el volumen base histórico (3 años previos). Permite categorizar temas en **Consolidados**, **Emergentes** y **Gaps** (brechas de investigación).
- **Protocolo Anti-Ruido Descendente *Works-First* (2022-2026)**: Para evitar que perfiles inactivos o médicos ajenos copen los resultados por citas acumuladas de por vida, el motor busca primero las obras recientes de alto impacto y de allí desciende a los autores activos.
- **Foco Iberoamericano y Sur Global (`SUR_GLOBAL_CODES`)**: Ponderación geopolítica (`AR|BO|BR|CL|CO|CR|CU|DO|EC|ES|GT|HN|MX|NI|PA|PE|PT|PY|SV|UY|VE|ZA|IN`), con fallback global para nichos hiper-específicos.
- **Roles Epistemológicos**: Clasificación funcional de cada obra en el ecosistema:
  - *Seminal*: Obra fundacional altamente citada que originó el debate.
  - *Síntesis / Review*: Estado del arte que compila la literatura previa.
  - *Teórico*: Modela conceptos y marcos analíticos.
  - *Metodológico*: Aporta diseños, instrumentos o escalas.
  - *Empírico*: Aplica observación, datos de campo o experimentos.

### 5.2. Paso 1: Cribado Asistido PRISMA
- Interfaz interactiva donde el investigador revisa títulos y resúmenes.
- Asignación de motivos estandarizados de exclusión PRISMA:
  - `E1`: No aborda la población/contexto diana.
  - `E2`: Diseño metodológico no pertinente (ej. ensayo de opinión vs estudio empírico).
  - `E3`: Variable de resultado (*outcome*) no medible o irrelevante.
  - `E4`: Doblaje o reporte redundante de la misma muestra.
- Generación automática de los conteos requeridos por el **Diagrama de Flujo PRISMA 2020** (Identificados, Cribados, Excluidos con motivos, Incluidos).

### 5.3. Paso 2: Extracción Textual y Data Charting JBI
- Ingesta de artículos a texto completo vía PDF o XML JATS legal de acceso abierto.
- Conversión a Markdown estructurado con detección de encabezados y preservación de jerarquías.
- **Rastreador de Citas en el Texto**:
  - `parse_reference_entry()`: Extrae de cada referencia bibliográfica el apellido del primer autor, el año y el DOI.
  - `ensure_cited_articles()`: Auto-ingesta en SQLite de la metadata oficial de las obras citadas antes de rastrear el texto.
  - Búsqueda en los párrafos del cuerpo del manuscrito (excluyendo la lista final de referencias) para aislar el momento exacto en que un autor dialoga con otro.
  - Extracción de la oración literal y asignación provisional de la función retórica (*Posible consenso*, *Posible disenso*, *Posible adopción metodológica*, *Posible mención contextual*).
- **Matriz de Variables JBI (PCC)**:
  - Extracción y persistencia en SQLite de: Población de estudio, Concepto central, Contexto geopolítico/disciplinar, Metodología empleada y Hallazgos clave verificados.

### 5.4. Paso 3: Síntesis Dialógica y Control de Alucinaciones
- **El Agente A.1 Metodólogo**: Módulo orquestador que redacta la revisión sistemática en 7 fases metodológicas estrictas.
- **Blindaje Anti-Alucinación (Lección del Percance 11)**:
  - El LLM **NUNCA** recibe el corpus bibliográfico crudo ni abstracts masivos que saturan el contexto de atención (*attention leak*).
  - El LLM es alimentado **exclusivamente con el `charting_verificado`**: una tabla estructurada de variables extraídas y acotadas (abstracts de máximo 280 caracteres, muestra representativa balanceada de 15 artículos).
  - Se elimina de raíz la cascada de repetición y los errores de desbordamiento de contexto HTTP 400.

---

## 6. Soberanía de Datos, Encriptación y Modelo Local-First

Para investigadores que trabajan con datos sensibles, borradores inéditos, patentes o proyectos confidenciales, subir sus archivos a servidores externos en la nube (OpenAI, Claude, servidores ajenos) representa un riesgo inaceptable de propiedad intelectual.

Thinkuy está arquitecturada como una aplicación **Local-First**:
1. **Ejecución Local**: El backend corre en la propia máquina del usuario (`127.0.0.1:8000`), interactuando con SQLite local (`data/thinkuy.db`) y LLMs locales (LM Studio u Ollama en `127.0.0.1:1234`).
2. **PWA Instalable**: La interfaz web se instala directamente en el sistema operativo (Windows, macOS, Linux) a través de los navegadores Chrome, Edge o Brave, con soporte offline gracias al Service Worker (`thinkuy-v48`).
3. **Encriptación en Cliente**:
   - Todo protocolo de revisión, matriz de charting o nota cualitativa puede encriptarse en reposo utilizando la **Web Crypto API** estándar del navegador con el algoritmo simétrico **AES-GCM de 256 bits**.
   - La clave criptográfica se deriva de la contraseña del investigador mediante **PBKDF2** (con 100.000 iteraciones y sal aleatoria única).
   - Ningún dato desencriptado viaja por la red; la soberanía de la investigación pertenece 100% al usuario.

---

## 7. Resumen de Fórmulas y Heurísticas Clave

### 7.1. Crecimiento Relativo de un Frente de Investigación
$$\text{Velocidad} = \frac{\text{Producción Reciente (2 años)} / 2}{\text{Producción Base (3 años previos)} / 3}$$
- $\text{Velocidad} > 1.5$: Tema Emergente / Frente de Onda.
- $0.7 \le \text{Velocidad} \le 1.5$: Tema Consolidado / Núcleo Teórico.
- $\text{Velocidad} < 0.7$: Tema en Enfriamiento o Brecha (*Gap*).

### 7.2. Main Path — Search Path Count (SPC)
En el grafo acíclico dirigido (DAG) de citas históricas:
$$\text{SPC}(e) = N_{\text{orígenes}}(u) \times N_{\text{destinos}}(v)$$
Donde el flujo de conocimiento atraviesa el arista $e = (u, v)$ ponderando la importancia del linaje conceptual que conecta los orígenes del debate con el frente de investigación actual.

---

*Thinkuy — Ciencia Abierta, Soberanía de Datos y Rigor Epistemológico al servicio de la comunidad científica.*
