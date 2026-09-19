
ESTE DOCUMENTO CONTIENE UNA LISTA DE AJUSTES QUE SE DEBEN A HACER A ALGUNOS ARCHIVOS PY

### El Secreto: Extracción de "Contexto de Citación" (Citation Context)

Para responder a **"¿Cómo se citan?"**, la IA no puede leer solo el resumen. Necesita leer **por qué** el Autor A citó al Autor B en el texto completo (o al menos en los párrafos donde aparece la cita).


1. Cuando ingiera un paper (vía `live_search` o `harvester`), si tiene acceso al texto completo (PDF parseado a XML/JSON), debe extraer los párrafos donde aparece el DOI citado.
2. Si no tiene el texto completo, debe usar la API de **Semantic Scholar** o **OpenAlex** para traer los _citation contexts_ (OpenAlex tiene un campo llamado `cited_by_api_url` o contextos en su API premium).

Si logra almacenar los **párrafos de contexto de citación** en su base de datos (ej. tabla `citation_contexts` con columnas `citing_doi`, `cited_doi`, `paragraph_text`), la IA podrá hacer esto:

> _"El Autor A (2022) cita al Autor B (2018) para **contradecir** su metodología, argumentando que el enfoque de B ignora la variable X. Por otro lado, el Autor C (2023) cita a B para **extendar** su teoría al contexto latinoamericano."_



**Falla actual de su motor:** OpenAlex y Crossref a veces proveen el texto completo o al menos los _referenced_works_, pero no el párrafo exacto. **Solución para el Motor:**

_________________________________________________________________________




Este módulo reemplaza la lógica de `proximity.py` para el análisis de contenido. Asumo que su base de datos (o la ingesta de OpenAlex/Crossref) guarda la lista de `referenced_works` (DOIs que cada paper cita).



"""
Motor de Mapeo Epistemológico para Revisiones Sistemáticas.
Enfoque: Estructural (Redes de Citación) vs. Semántico (Texto).
"""
import sqlite3
from collections import defaultdict, Counter
from . import db, network as net
from .normalize import norm

def build_epistemic_graph(conn: sqlite3.Connection, seed_dois: list[str] = None, topic: str = None):
    """
    Construye el grafo epistemológico.
    Nodos: Papers/Autores.
    Aristas: Citaciones (A cita a B).
    """
    # 1. Cargar corpus relevante
    # Para una revisión sistemática, necesitamos el corpus completo o una muestra grande
    rows = conn.execute("SELECT * FROM articles WHERE referenced_works IS NOT NULL").fetchall()
    corpus = [db._row_to_article(r) for r in rows]
    
    if not corpus:
        return {"error": "No hay datos de referencias bibliográficas. Ingesta incompleta."}

    # 2. Construir Matriz de Co-citación (CCC)
    # Si el Paper X cita a A y a B, entonces A y B tienen un vínculo de co-citación.
    # Esto revela "Escuelas de Pensamiento".
    cocitation_matrix = defaultdict(int)
    citation_context = defaultdict(list) # Para analizar "qué dice A de B"
    
    # Mapa de ID canónico para autores
    identity_map = net.author_identity_map(corpus)

    for paper in corpus:
        refs = paper.get("referenced_works") or []
        # Normalizar referencias a DOIs o IDs internos
        ref_ids = [r.get("doi") or r for r in refs if r]
        
        # Co-citación: Todos contra todos dentro de las referencias
        for i, ref_a in enumerate(ref_ids):
            for ref_b in ref_ids[i+1:]:
                pair = tuple(sorted([ref_a, ref_b]))
                cocitation_matrix[pair] += 1

    # 3. Análisis de "Conversación" (Citation Context)
    # ¿Quién cita a quién?
    citation_edges = []
    for paper in corpus:
        paper_id = paper.get("doi")
        authors = paper.get("authors", [])
        refs = paper.get("referenced_works") or []
        
        for ref in refs:
            ref_doi = ref.get("doi") if isinstance(ref, dict) else ref
            if ref_doi:
                citation_edges.append({
                    "source": paper_id,
                    "target": ref_doi,
                    "year": paper.get("year"),
                    "source_authors": [net.canonical_author_id(a, identity_map) for a in authors if isinstance(a, dict)]
                })

    return {
        "nodes_count": len(corpus),
        "edges_count": len(citation_edges),
        "cocitation_clusters": _detect_clusters(cocitation_matrix),
        "citation_edges": citation_edges,
        "main_path": _calculate_main_path(corpus, citation_edges)
    }

def _detect_clusters(matrix: dict, threshold: int = 3):
    """
    Identifica clústeres de co-citación fuerte.
    Si A y B son co-citados más de 'threshold' veces, son la misma escuela.
    """
    # Simplificación: usar componentes conectados sobre aristas fuertes
    strong_edges = [(a, b) for (a, b), w in matrix.items() if w >= threshold]
    
    # Algoritmo Union-Find para clústeres
    parent = {}
    def find(i):
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]

    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    # Inicializar
    all_nodes = set()
    for a, b in strong_edges:
        all_nodes.add(a)
        all_nodes.add(b)
        parent[a] = a
        parent[b] = b

    for a, b in strong_edges:
        union(a, b)

    clusters = defaultdict(list)
    for node in all_nodes:
        clusters[find(node)].append(node)
    
    return list(clusters.values())

def _calculate_main_path(corpus, edges):
    """
    Algoritmo simplificado de Main Path (Trayectoria Principal).
    Encuentra la cadena de citas más "densa" que conecta el pasado con el presente.
    Útil para ver la evolución histórica de la idea.
    """
    # Contar pesos de aristas (cuántas veces se cita ese vínculo en el corpus)
    edge_weights = Counter()
    for e in edges:
        edge_weights[(e["source"], e["target"])] += 1
    
    # Aquí iría el algoritmo completo de Search Path Count (SPC)
    # Por ahora, retornamos las aristas más fuertes como "autopista"
    top_links = edge_weights.most_common(20)
    return [{"from": k[0], "to": k[1], "weight": v} for k, v in top_links]

def curate_for_systematic_review(conn, seed_dois):
    """
    Herramienta de curación: Clasifica papers por su ROL en la conversación.
    """
    papers = [db.get_article(conn, doi) for doi in seed_dois]
    curated = []
    
    for p in papers:
        # Heurística de Rol
        title = (p.get("title") or "").lower()
        refs_count = len(p.get("referenced_works") or [])
        cited_by = p.get("cited_by") or 0
        
        role = "Empirical" # Default
        if any(k in title for k in ["review", "revisión", "systematic", "scoping", "meta-analysis"]):
            role = "Synthesis/Review"
        elif refs_count > 80:
            role = "Theoretical/Framework" # Pocos datos, mucha teoría
        elif cited_by > 50:
            role = "Seminal" # Clásico
            
        curated.append({
            "doi": p.get("doi"),
            "title": p.get("title"),
            "role": role,
            "centrality": _calculate_centrality(conn, p.get("doi"))
        })
        
    return curated

def _calculate_centrality(conn, doi):
    """Calcula PageRank académico (importancia estructural)."""
    # Implementación simplificada: Grado de entrada (cuántos lo citan)
    row = conn.execute("SELECT cited_by FROM articles WHERE doi = ?", (doi,)).fetchone()
    return row[0] if row else 0


__________________________________________________________________________________________

### Ajustes Necesarios en `main.py` (API)

Debe exponer estos nuevos conceptos al frontend para que el revisor sistemático los use.

**Nuevo Endpoint: `/api/radar/epistemic`** En lugar de solo "autores cercanos", este endpoint devuelve:

1. **Línea de Tiempo:** Evolución del tema.
2. **Clústeres:** "Grupo A (Positivista)" vs "Grupo B (Constructivista)".
3. **Papeles:** "Este paper es la base teórica", "Este es el estudio empírico clave".

# En main.py, agregar:
@app.get("/api/radar/expand")
def expand_seed(
    doi: str = Query(..., description="DOI del paper semilla"),
    direction: str = Query("both", pattern="^(backward|forward|both)$", description="Dirección del snowballing"),
    limit: int = Query(20, ge=5, le=50)
):
    """
    Expansión tipo Research Rabbit: Dados un paper semilla, encuentra 
    sus ancestros (referencias) y descendientes (quienes lo citan).
    """
    conn = db.connect()
    try:
        seed = db.get_article(conn, doi.strip().lower())
        if not seed:
            raise HTTPException(404, "DOI semilla no encontrado en el catálogo")
        
        expanded_dois = set([doi])
        
        # 1. Snowballing hacia atrás (Referencias / Ancestros)
        if direction in ("backward", "both"):
            refs_raw = seed.get("referenced_works") or "[]"
            try:
                refs = json.loads(refs_raw) if isinstance(refs_raw, str) else refs_raw
                for r in refs:
                    r_doi = r.get("doi") if isinstance(r, dict) else r
                    if r_doi:
                        expanded_dois.add(r_doi.lower())
            except:
                pass
        
        # 2. Snowballing hacia adelante (Citado por / Descendientes)
        # Nota: Esto requiere que la BD tenga actualizado quién cita a quién. 
        # OpenAlex provee esto en el campo 'cited_by_count' y a veces la lista.
        if direction in ("forward", "both"):
            # Buscamos artículos en nuestra BD que tengan este DOI en sus referenced_works
            # (Una consulta LIKE en JSON o una tabla normalizada de citaciones es más rápida)
            rows = conn.execute(
                "SELECT doi FROM articles WHERE referenced_works LIKE ?", 
                (f"%{doi}%",)
            ).fetchall()
            for r in rows:
                expanded_dois.add(r["doi"].lower())
        
        # 3. Obtener los metadatos de los DOIs expandidos
        placeholders = ','.join(['?'] * len(expanded_dois))
        articles = conn.execute(
            f"SELECT * FROM articles WHERE doi IN ({placeholders})", 
            list(expanded_dois)
        ).fetchall()
        
        arts_dict = [db._row_to_article(r) for r in articles]
        
        # 4. Enriquecer con el grafo epistemológico (Co-citación entre ellos)
        # Esto le da al frontend la información para dibujar las líneas entre estos papers
        graph = epistemic.build_epistemic_graph(conn, seed_dois=list(expanded_dois)[:50])
        
        return {
            "seed": {"doi": seed["doi"], "title": seed["title"], "year": seed["year"]},
            "expanded_count": len(arts_dict),
            "articles": arts_dict,
            "network": {
                "edges": graph["citation_edges"], # Para dibujar las flechas
                "clusters": graph["cocitation_clusters"] # Para colorear por escuelas
            }
        }
    finally:
        conn.close()__________________________________________________________________________________________

### 5. Requerimiento de Base de Datos (Crítico)

Para que esto funcione, su tabla `articles` **DEBE** tener la columna `referenced_works` (JSON o tabla relacionada).

- **OpenAlex** y **Crossref** proveen esto nativamente (`referenced_works`).
- **Falla actual:** Si su `harvester` no está guardando las referencias, el motor epistemológico es imposible.
- **Acción:** Asegurar que `db.py` ingeste la lista de DOIs citados por cada paper.

### Resumen del Cambio de Paradigma

|Característica|Motor Actual (Semántico)|Nuevo Motor (Epistemológico)|
|---|---|---|
|**Unión**|Palabras clave similares|Citaciones compartidas (Co-citación)|
|**Búsqueda**|`LIKE '%term%'`|Expansiones de Red (Snowballing)|
|**Resultado**|Lista de papers relevantes|Mapa de Escuelas y Linajes|
|**Utilidad**|Encontrar "qué hay"|Entender "cómo se debate"|

Este ajuste convierte a Thinkuy en una herramienta de **Inteligencia Científica** real, apta para metodologías PRISMA y análisis de dominio.

_______________________________________________________________________


### 1. Arquitectura del "Revisor IA" (Módulo `review_agent.py`)

Este módulo no usa `LIKE` en la base de datos. Usa el Grafo Epistemológico (que construimos en el paso anterior) y lo inyecta en un LLM con un _System Prompt_ estricto basado en guías JBI/PRISMA.

"""
review_agent.py
Motor de Inteligencia Artificial para Revisiones Sistemáticas y Scoping Reviews.
Enfoque: Protocolos PRISMA/JBI, Extracción PICO/SPIDER, y Síntesis Epistemológica.
"""
import json
import sqlite3
from typing import List, Dict
from . import db, epistemic # El módulo epistemológico que diseñamos antes

# ==========================================
# 1. EL "PROMPT" DEL REVISOR EXPERTO (JBI/PRISMA)
# ==========================================
SYSTEM_PROMPT_REVIEWER = """
Eres un Investigador Principal experto en Metodología de la Investigación, 
especializado en Revisiones Sistemáticas (PRISMA/Cochrane) y Scoping Reviews (JBI).
Tu objetivo no es resumir, sino MAPEAR EL CONOCIMIENTO, HACER CURADUARÍA y evaluar la EPISTEMOLOGÍA.

REGLAS INQUEBRANTABLES:
1. NO inventes citas. Si el texto no lo dice explícitamente, indícalo.
2. Debes explorar todo el texto.
3. Identifica el ROL del paper: ¿Es un paper Seminal (propone teoría), Empírico (testea), Metodológico, o Crítico?
4. Cuando se te pregunte "¿Qué dice A y B sobre C?", debes basarte EXCLUSIVAMENTE en el contexto de citación y el resumen.
5. Detecta SESGOS o LIMITACIONES metodológicas si el resumen lo permite.
6. Clasifica los hallazgos en: Consenso, Debate/Conflicto, o Vacío de Investigación. Cada categoría en un color. 
"""

# ==========================================
# 2. MOTOR DE CRIBADO (SCREENING) AUTOMÁTICO
# ==========================================
def screen_papers_for_protocol(
    llm_client, 
    papers: List[Dict], 
    inclusion_criteria: str, 
    exclusion_criteria: str,
    framework: str = "PICO" # PICO para RS, SPIDER para ScR cualitativas
) -> Dict:
    """
    Evalúa una lista de papers contra los criterios de inclusión/exclusión.
    Devuelve la clasificación PRISMA: Included, Excluded, Maybe (needs human review).
    """
    results = {"included": [], "excluded": [], "maybe": [], "reasoning": {}}
    
    for paper in papers:
        # Solo enviamos Título + Resumen + Keywords al LLM para ahorrar tokens y tiempo
        context = f"Título: {paper.get('title')}\nResumen: {paper.get('abstract')}\nKeywords: {paper.get('keywords')}"
        
        prompt = f"""
        Marco de referencia: {framework}
        Criterios de INCLUSIÓN: {inclusion_criteria}
        Criterios de EXCLUSIÓN: {exclusion_criteria}
        
        Paper a evaluar:
        {context}
        
        Responde EXCLUSIVAMENTE en formato JSON con esta estructura:
        {{
            "decision": "included" | "excluded" | "maybe",
            "reason": "Explicación breve y técnica de por qué (máx 2 frases).",
            "extracted_data": {{
                "population/sample": "...",
                "intervention/phenomenon": "...",
                "methodology": "..."
            }}
        }}
        """
        
        # Llamada al LLM (simulada, aquí iría su integración con OpenAI/Anthropic/Ollama)
        response = llm_client.chat(system=SYSTEM_PROMPT_REVIEWER, user=prompt)
        data = json.loads(response)
        
        results[data["decision"]].append(paper["doi"])
        results["reasoning"][paper["doi"]] = data["reason"]
        
    return results

# ==========================================
# 3. SÍNTESIS EPISTEMOLÓGICA (¿Qué dice A y B sobre C?)
# ==========================================
def synthesize_epistemic_debate(
    llm_client,
    conn: sqlite3.Connection,
    concept_c: str,
    author_a_doi: str,
    author_b_doi: str
) -> Dict:
    """
    Responde a la pregunta: ¿Cómo conversan/citan A y B, y qué dice cada uno sobre el concepto C?
    Utiliza el grafo epistemológico para encontrar el contexto real.
    """
    # 1. Obtener los papers de A y B
    paper_a = db.get_article(conn, author_a_doi)
    paper_b = db.get_article(conn, author_b_doi)
    
    # 2. Obtener el grafo de co-citación (¿Están en la misma escuela?)
    graph = epistemic.build_epistemic_graph(conn, seed_dois=[author_a_doi, author_b_doi])
    are_in_same_cluster = False
    for cluster in graph.get("cocitation_clusters", []):
        if author_a_doi in cluster and author_b_doi in cluster:
            are_in_same_cluster = True
            break
            
    # 3. Construir el prompt de síntesis
    prompt = f"""
    Tienes dos artículos científicos y un concepto central: "{concept_c}".
    
    ARTÍCULO A: {paper_a.get('title')}. Resumen: {paper_a.get('abstract')}
    ARTÍCULO B: {paper_b.get('title')}. Resumen: {paper_b.get('abstract')}
    
    CONTEXTO DE LA RED: ¿Ambos autores pertenecen al mismo clúster de co-citación (misma escuela de pensamiento)? {are_in_same_cluster}
    
    TAREA:
    1. Explica qué dice el Autor A sobre "{concept_c}".
    2. Explica qué dice el Autor B sobre "{concept_c}".
    3. ¿Cómo se relacionan epistemológicamente? (¿Se citan? ¿Se contradicen? ¿Usan la misma base teórica pero llegan a conclusiones opuestas? ¿Son paradigmas incomparables?).
    4. ¿Qué "hueco" (gap) deja esta conversación que justifique una nueva investigación?
    
    Responde en formato JSON estructurado.
    """
    
    response = llm_client.chat(system=SYSTEM_PROMPT_REVIEWER, user=prompt)
    return json.loads(response)

__________________________________________________________________


### Integración en la API (`main.py`)

Para que el frontend (o el investigador) use esta IA, debemos exponer endpoints específicos que sigan el flujo de trabajo de una revisión sistemática.


# En main.py, agregar al final:

from . import review_agent
from .llm_client import get_llm_client # Su wrapper para OpenAI/Anthropic/Ollama

@app.post("/api/review/protocol")
def create_review_protocol(payload: dict = Body(...)):
    """
    Inicia una Revisión Sistemática o Scoping Review.
    Define el protocolo (Pregunta, Criterios PICO/SPIDER).
    """
    conn = db.connect()
    try:
        protocol = {
            "title": payload.get("title"),
            "question": payload.get("question"),
            "framework": payload.get("framework", "PICO"), # PICO o SPIDER
            "inclusion": payload.get("inclusion_criteria"),
            "exclusion": payload.get("exclusion_criteria"),
            "status": "screening"
        }
        # Guardar en DB (requeriría una tabla `review_protocols`)
        # db.save_protocol(conn, protocol)
        return {"status": "ok", "protocol": protocol}
    finally:
        conn.close()

@app.post("/api/review/screen")
def run_ai_screening(payload: dict = Body(...)):
    """
    Pasa los artículos candidatos por el filtro de IA (Cribado PRISMA).
    """
    protocol_id = payload.get("protocol_id")
    conn = db.connect()
    try:
        # 1. Obtener artículos candidatos (del grafo epistemológico o búsqueda inicial)
        candidate_dois = payload.get("candidate_dois", [])
        papers = [db.get_article(conn, doi) for doi in candidate_dois if db.get_article(conn, doi)]
        
        # 2. Obtener criterios del protocolo
        # protocol = db.get_protocol(conn, protocol_id)
        inclusion = payload.get("inclusion_criteria")
        exclusion = payload.get("exclusion_criteria")
        framework = payload.get("framework", "PICO")
        
        # 3. Ejecutar IA de cribado
        llm = get_llm_client()
        screening_result = review_agent.screen_papers_for_protocol(
            llm, papers, inclusion, exclusion, framework
        )
        
        return {
            "status": "ok",
            "screening": screening_result,
            "prisma_flow": {
                "identified": len(papers),
                "included": len(screening_result["included"]),
                "excluded": len(screening_result["excluded"]),
                "needs_review": len(screening_result["maybe"])
            }
        }
    finally:
        conn.close()

@app.post("/api/review/synthesize")
def synthesize_debate(payload: dict = Body(...)):
    """
    La pregunta de oro: ¿Qué dice A y B sobre C?
    """
    concept = payload.get("concept")
    doi_a = payload.get("doi_a")
    doi_b = payload.get("doi_b")
    
    if not all([concept, doi_a, doi_b]):
        raise HTTPException(400, "concept, doi_a, y doi_b son obligatorios")
        
    conn = db.connect()
    try:
        llm = get_llm_client()
        synthesis = review_agent.synthesize_epistemic_debate(
            llm, conn, concept, doi_a, doi_b
        )
        return {"status": "ok", "synthesis": synthesis}
    finally:
        conn.close()

______________________________________________________________________



Necesitamos tres cosas en SQLite:

1. Una tabla para los **Protocolos de Revisión** (PRISMA/JBI).
2. Una tabla para los **Contextos de Citación** (los párrafos exactos donde el Autor A cita al Autor B).
3. Asegurar que la tabla `articles` pueda almacenar la lista de referencias (`referenced_works`).

Añada esto a su archivo `db.py` (idealmente dentro de su función `init_db(conn)` o como un script de migración):

# ==========================================
# ESQUEMA PARA MAPEO EPISTEMOLÓGICO Y PRISMA
# ==========================================

def init_epistemic_schema(conn):
    """Inicializa las tablas necesarias para Revisiones Sistemáticas y Mapeo Epistemológico."""
    
    # 1. Protocolos de Revisión Sistemática / Scoping Review (PRISMA/JBI)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_protocols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            research_question TEXT,
            framework TEXT DEFAULT 'PICO',  -- PICO, SPIDER, PICo, etc.
            inclusion_criteria TEXT,
            exclusion_criteria TEXT,
            seed_dois TEXT,                 -- JSON array de DOIs semilla
            status TEXT DEFAULT 'draft',    -- draft, screening, extracting, completed
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # 2. Contextos de Citación (La clave para saber "Qué dice A de B")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS citation_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            citing_doi TEXT NOT NULL,       -- DOI del paper que cita
            cited_doi TEXT NOT NULL,        -- DOI del paper citado
            paragraph_text TEXT NOT NULL,   -- El párrafo exacto donde ocurre la cita
            section TEXT,                   -- intro, methods, discussion, etc.
            sentiment TEXT,                 -- positive, negative, neutral, contrasting (opcional, para IA)
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(citing_doi) REFERENCES articles(doi),
            FOREIGN KEY(cited_doi) REFERENCES articles(doi)
        )
    """)
    
    # Índices para velocidad en grafos de citación
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cit_context_citing ON citation_contexts(citing_doi)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cit_context_cited ON citation_contexts(cited_doi)")

    # 3. Asegurar que la tabla 'articles' tenga la columna de referencias (OpenAlex/Crossref)
    # Usamos PRAGMA para verificar si la columna ya existe antes de intentar añadirla
    cursor = conn.execute("PRAGMA table_info(articles)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "referenced_works" not in columns:
        conn.execute("ALTER TABLE articles ADD COLUMN referenced_works TEXT")
        # referenced_works guardará un JSON array de DOIs: '["10.1234/a", "10.1234/b"]'
        
    conn.commit()

________________________________________________________________________


### PASO 2: El Módulo Epistemológico (`epistemic.py`)

Cree este nuevo archivo en su proyecto. Este módulo reemplaza la lógica de "proximidad por texto" por **análisis de redes de citación** (Co-citación y Acoplamiento Bibliográfico).


"""
epistemic.py
Motor de Mapeo Epistemológico para Revisiones Sistemáticas y Scoping Reviews.
Enfoque: Estructural (Redes de Citación) vs. Semántico (Texto).
Descubre escuelas de pensamiento, rutas principales (Main Path) y contextos de conversación.
"""
import sqlite3
import json
from collections import defaultdict, Counter
from typing import List, Dict, Tuple, Optional
from . import db

# ==========================================
# 1. CONSTRUCCIÓN DEL GRAFO EPISTEMOLÓGICO
# ==========================================

def build_epistemic_graph(conn: sqlite3.Connection, seed_dois: List[str] = None, max_corpus: int = 1000) -> Dict:
    """
    Construye el grafo epistemológico basado en citaciones.
    Si se proveen seed_dois, expande el corpus usando Snowballing (Bola de Nieve) 
    hacia atrás (referencias) y hacia adelante (citados por).
    """
    # 1. Obtener corpus base
    if seed_dois:
        # Aquí iría la lógica de Snowballing. Por ahora, cargamos los seeds y sus conexiones directas.
        placeholders = ','.join(['?'] * len(seed_dois))
        rows = conn.execute(f"SELECT * FROM articles WHERE doi IN ({placeholders})", seed_dois).fetchall()
        corpus = [db._row_to_article(r) for r in rows]
    else:
        rows = conn.execute("SELECT * FROM articles WHERE referenced_works IS NOT NULL LIMIT ?", (max_corpus,)).fetchall()
        corpus = [db._row_to_article(r) for r in rows]

    if not corpus:
        return {"error": "No hay datos de referencias bibliográficas. Ingesta incompleta."}

    # 2. Matrices de Análisis Estructural
    cocitation_matrix = defaultdict(int)      # A y B son citados juntos por X
    bibliographic_coupling = defaultdict(int) # A y B citan a los mismos X
    citation_edges = []                       # A cita a B
    
    # Mapa de referencias por paper
    paper_refs = {}
    for paper in corpus:
        doi = paper.get("doi")
        if not doi: continue
        
        refs_raw = paper.get("referenced_works") or "[]"
        if isinstance(refs_raw, str):
            try:
                refs = json.loads(refs_raw)
            except json.JSONDecodeError:
                refs = []
        else:
            refs = refs_raw
            
        # Normalizar a lista de DOIs
        ref_dois = []
        for r in refs:
            if isinstance(r, dict):
                ref_dois.append(r.get("doi", "").lower())
            elif isinstance(r, str):
                ref_dois.append(r.lower())
                
        ref_dois = [r for r in ref_dois if r]
        paper_refs[doi] = ref_dois
        
        # Aristas de citación directa
        for ref_doi in ref_dois:
            citation_edges.append({
                "source": doi,
                "target": ref_doi,
                "year": paper.get("year")
            })

    # 3. Calcular Co-citación (Escuelas de Pensamiento)
    # Si el Paper X cita a A y a B, entonces A y B tienen un vínculo de co-citación.
    for doi, refs in paper_refs.items():
        unique_refs = list(set(refs))
        for i in range(len(unique_refs)):
            for j in range(i + 1, len(unique_refs)):
                pair = tuple(sorted([unique_refs[i], unique_refs[j]]))
                cocitation_matrix[pair] += 1

    # 4. Calcular Acoplamiento Bibliográfico (Bases Teóricas Compartidas)
    # Si el Paper A y el Paper B citan ambos al Paper X, están acoplados.
    # (Inverso de co-citación, útil para ver quién está trabajando en la misma línea HOY)
    cited_by_who = defaultdict(set)
    for doi, refs in paper_refs.items():
        for ref in refs:
            cited_by_who[ref].add(doi)
            
    for ref_doi, citing_papers in cited_by_who.items():
        citing_list = list(citing_papers)
        for i in range(len(citing_list)):
            for j in range(i + 1, len(citing_list)):
                pair = tuple(sorted([citing_list[i], citing_list[j]]))
                bibliographic_coupling[pair] += 1

    return {
        "corpus_size": len(corpus),
        "citation_edges": citation_edges,
        "cocitation_clusters": _detect_clusters(cocitation_matrix, threshold=2),
        "coupling_clusters": _detect_clusters(bibliographic_coupling, threshold=3),
        "main_path": _calculate_main_path(citation_edges),
        "paper_refs": paper_refs
    }

# ==========================================
# 2. ALGORITMOS DE DETECCIÓN ESTRUCTURAL
# ==========================================

def _detect_clusters(matrix: dict, threshold: int = 2) -> List[List[str]]:
    """
    Identifica clústeres usando el algoritmo Union-Find (Componentes Conectados).
    Si A y B superan el umbral de fuerza, pertenecen al mismo clúster epistemológico.
    """
    strong_edges = [(a, b) for (a, b), w in matrix.items() if w >= threshold]
    
    parent = {}
    def find(i):
        if parent.get(i, i) == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]

    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    all_nodes = set()
    for a, b in strong_edges:
        all_nodes.add(a)
        all_nodes.add(b)
        parent[a] = a
        parent[b] = b

    for a, b in strong_edges:
        union(a, b)

    clusters = defaultdict(list)
    for node in all_nodes:
        clusters[find(node)].append(node)
    
    # Ordenar clústeres por tamaño (los más grandes son las escuelas dominantes)
    sorted_clusters = sorted(clusters.values(), key=len, reverse=True)
    return sorted_clusters[:10] # Top 10 escuelas

def _calculate_main_path(edges: List[Dict], top_n: int = 20) -> List[Dict]:
    """
    Algoritmo simplificado de Main Path (Trayectoria Principal).
    Encuentra la cadena de citas más "densa" que conecta el pasado con el presente.
    Útil para ver la evolución histórica de la idea (el "hilo conductor").
    """
    # Contar pesos de aristas (cuántas veces se repite esa citación en el corpus)
    edge_weights = Counter()
    for e in edges:
        edge_weights[(e["source"], e["target"])] += 1
    
    # Retornar las aristas más fuertes como la "autopista" del conocimiento
    top_links = edge_weights.most_common(top_n)
    return [{"from_doi": k[0], "to_doi": k[1], "weight": v} for k, v in top_links]


# ==========================================
# 3. CURACIÓN Y ROLES EPISTEMOLÓGICOS
# ==========================================

def curate_for_systematic_review(conn: sqlite3.Connection, dois: List[str]) -> List[Dict]:
    """
    Clasifica papers por su ROL en la conversación científica.
    Fundamental para una Scoping Review: saber qué es teoría, qué es empírica, qué es revisión.
    """
    papers = []
    for doi in dois:
        art = db.get_article(conn, doi)
        if art:
            papers.append(art)
            
    curated = []
    for p in papers:
        title = (p.get("title") or "").lower()
        abstract = (p.get("abstract") or "").lower()
        text_blob = title + " " + abstract
        
        refs_raw = p.get("referenced_works") or "[]"
        refs_count = len(json.loads(refs_raw)) if isinstance(refs_raw, str) else len(refs_raw)
        cited_by = p.get("cited_by") or 0
        
        # Heurística de Rol Epistemológico
        role = "Empirical" # Default
        if any(k in text_blob for k in ["systematic review", "revisión sistemática", "scoping review", "meta-analysis", "meta-análisis", "estado del arte"]):
            role = "Synthesis/Review"
        elif refs_count > 80 and cited_by < 20:
            role = "Theoretical/Framework" # Mucha teoría, poco impacto empírico aún
        elif cited_by > 50:
            role = "Seminal" # Clásico / Altamente influyente
        elif any(k in text_blob for k in ["methodology", "metodología", "instrument", "escala", "validación"]):
            role = "Methodological"
            
        curated.append({
            "doi": p.get("doi"),
            "title": p.get("title"),
            "year": p.get("year"),
            "role": role,
            "cited_by": cited_by,
            "refs_count": refs_count,
            "centrality_score": cited_by # Proxy simple de centralidad de grado de entrada
        })
        
    # Ordenar por importancia (Seminales primero, luego Síntesis)
    role_priority = {"Seminal": 1, "Synthesis/Review": 2, "Theoretical/Framework": 3, "Methodological": 4, "Empirical": 5}
    curated.sort(key=lambda x: (role_priority.get(x["role"], 9), -x["cited_by"]))
    return curated


# ==========================================
# 4. LA PREGUNTA DE ORO: ¿QUÉ DICE A DE B?
# ==========================================

def get_conversation_context(conn: sqlite3.Connection, citing_doi: str, cited_doi: str) -> List[Dict]:
    """
    Recupera los párrafos exactos donde el Autor A (citing) menciona al Autor B (cited).
    Esto es lo que permite a la IA responder "¿Cómo conversan?" sin alucinar.
    """
    rows = conn.execute("""
        SELECT paragraph_text, section, sentiment 
        FROM citation_contexts 
        WHERE citing_doi = ? AND cited_doi = ?
    """, (citing_doi.lower(), cited_doi.lower())).fetchall()
    
    return [
        {
            "text": r["paragraph_text"],
            "section": r["section"],
            "sentiment": r["sentiment"] or "neutral"
        }
        for r in rows
    ]

def find_epistemic_bridges(conn: sqlite3.Connection, cluster_1_dois: List[str], cluster_2_dois: List[str]) -> List[Dict]:
    """
    Encuentra los "Puentes" (Betweenness). Papers que citan a ambos clústeres 
    (escuelas de pensamiento que normalmente no se hablan).
    """
    if not cluster_1_dois or not cluster_2_dois:
        return []
        
    set1 = set(d.lower() for d in cluster_1_dois)
    set2 = set(d.lower() for d in cluster_2_dois)
    
    # Buscar papers que tengan en sus referencias DOIs de AMBOS clústeres
    bridges = []
    rows = conn.execute("SELECT doi, title, referenced_works FROM articles WHERE referenced_works IS NOT NULL").fetchall()
    
    for r in rows:
        doi = r["doi"]
        refs_raw = r["referenced_works"] or "[]"
        try:
            refs = json.loads(refs_raw)
        except:
            continue
            
        ref_dois = set()
        for ref in refs:
            if isinstance(ref, dict): ref_dois.add(ref.get("doi", "").lower())
            elif isinstance(ref, str): ref_dois.add(ref.lower())
            
        hits_1 = len(ref_dois & set1)
        hits_2 = len(ref_dois & set2)
        
        if hits_1 > 0 and hits_2 > 0:
            bridges.append({
                "doi": doi,
                "title": r["title"],
                "links_to_cluster_1": hits_1,
                "links_to_cluster_2": hits_2,
                "bridge_strength": hits_1 + hits_2
            })
            
    bridges.sort(key=lambda x: -x["bridge_strength"])
    return bridges[:10]
____________________________________________________________________________

### Qué acabamos de lograr con estos dos pasos?

1. **La Base de Datos ahora "piensa" en relaciones:** Ya no solo guarda texto, guarda _linajes intelectuales_ (`citation_contexts`) y _protocolos de investigación_ (`review_protocols`).
2. **El Motor Epistemológico (`epistemic.py`) es ciego a las palabras y sensible a la estructura:**
    - Si usted le da un tema, no busca "palabras clave". Busca **Clústeres de Co-citación** (Escuelas de pensamiento).
    - Si quiere saber la evolución del tema, usa el **Main Path** (El hilo conductor histórico).
    - Si quiere hacer una Revisión Sistemática, usa `curate_for_systematic_review` para separar automáticamente los papers _Seminales_ de los _Empíricos_ o las _Síntesis_.
    - **Lo más importante:** La función `get_conversation_context` es la que alimentará a la IA en el Paso 3. Cuando le pregunte "¿Qué dice el Autor A del Autor B?", la IA no inventará; leerá el párrafo exacto extraído de la tabla `citation_contexts`.
_________________________________________________________________________

### Spotify para Papers" (Similitud Estructural, no solo Semántica)

- **Lo que hace Research Rabbit:** Tiene una pestaña "Similar Works". No se basa en que los títulos tengan las mismas palabras, sino en **Acoplamiento Bibliográfico** (si el Paper A y el Paper B citan a las mismas 10 fuentes, son estructuralmente similares, aunque usen palabras distintas).
- **Cómo lo aplicamos en Thinkuy:** Ya calculamos `bibliographic_coupling` en `epistemic.py`. Debemos exponer un endpoint rápido:
- 
- @app.get("/api/radar/similar/{doi}")
def get_similar_works(doi: str, limit: int = 15):
    # 1. Obtener las referencias del DOI semilla.
    # 2. Buscar en la BD otros papers que compartan >30% de esas referencias.
    # 3. Rankear por ese solapamiento (Jaccard similarity).
_________________________________________________________________________

### Paso 3: El Motor de IA para Revisiones Sistemáticas (`review_agent.py`)

"""
review_agent.py
Motor de Inteligencia Artificial para Revisiones Sistemáticas y Scoping Reviews.
Enfoque: Auditoría Epistemológica, Cribado PRISMA (PICO/SPIDER) y Síntesis Estructural.
No resume textos: mapea la estructura del conocimiento y extrae datos metodológicos.
"""
import json
import sqlite3
import logging
from typing import List, Dict, Any
from . import db, epistemic

log = logging.getLogger("radar.review_agent")

# ==========================================
# 1. SYSTEM PROMPT: EL REVISOR PAR EXPERTO
# ==========================================
SYSTEM_PROMPT = """
Eres un Investigador Principal y Metodólogo experto en Revisiones Sistemáticas (PRISMA/Cochrane) 
y Scoping Reviews (JBI). Tu función NO es resumir textos de forma semántica, sino analizar 
la EPISTEMOLOGÍA y la ESTRUCTURA de la literatura científica.

REGLAS INQUEBRANTABLES:
1. CERO ALUCINACIÓN: Si la información no está explícita en el contexto proporcionado, debes marcarlo como "No reportado" o "Null".
2. ENFOQUE EPISTEMOLÓGICO: Cuando analices debates, no busques similitud de palabras. Busca linajes: 
   ¿Quién cita a quién? ¿Quién contradice la metodología de quién? ¿Qué escuela de pensamiento representan?
3. RIGOR METODOLÓGICO: Identifica el diseño exacto (ej. "Estudio transversal", "Etnografía", "Meta-análisis de red").
4. FORMATO: Responde SIEMPRE en JSON válido, sin markdown, sin texto fuera del objeto JSON.
"""

# ==========================================
# 2. MOTOR DE CRIBADO (SCREENING PRISMA/JBI)
# ==========================================
def screen_papers_for_protocol(
    llm_client, 
    papers: List[Dict], 
    inclusion_criteria: str, 
    exclusion_criteria: str,
    framework: str = "PICO"
) -> Dict[str, Any]:
    """
    Evalúa artículos contra criterios de inclusión/exclusión.
    Devuelve la clasificación PRISMA: Included, Excluded, Maybe.
    """
    results = {"included": [], "excluded": [], "maybe": [], "reasoning": {}}
    
    for paper in papers:
        context = f"""
        Título: {paper.get('title')}
        Resumen: {paper.get('abstract')}
        Palabras clave: {paper.get('keywords')}
        Metodología declarada: {paper.get('type') or 'Desconocida'}
        """
        
        prompt = f"""
        Marco de referencia: {framework}
        Criterios de INCLUSIÓN: {inclusion_criteria}
        Criterios de EXCLUSIÓN: {exclusion_criteria}
        
        Paper a evaluar:
        {context}
        
        TAREA: Evalúa si este paper entra, sale o requiere revisión humana.
        Responde EXCLUSIVAMENTE en este formato JSON:
        {{
            "decision": "included" | "excluded" | "maybe",
            "reason": "Justificación técnica en 1-2 frases basada estrictamente en los criterios.",
            "extracted_pico": {{
                "population": "...",
                "intervention_phenomenon": "...",
                "context": "...",
                "methodology": "..."
            }}
        }}
        """
        
        try:
            response = llm_client.chat(system=SYSTEM_PROMPT, user=prompt, response_format="json")
            data = json.loads(response)
            
            decision = data.get("decision", "maybe")
            results[decision].append({
                "doi": paper.get("doi"),
                "title": paper.get("title"),
                "pico": data.get("extracted_pico", {})
            })
            results["reasoning"][paper.get("doi")] = data.get("reason", "Sin justificación")
        except Exception as e:
            log.error(f"Error en cribado IA para {paper.get('doi')}: {e}")
            results["maybe"].append({"doi": paper.get("doi"), "title": paper.get("title"), "pico": {}})
            results["reasoning"][paper.get("doi")] = f"Error de parsing IA: {str(e)}"
            
    return results


# ==========================================
# 3. SÍNTESIS EPISTEMOLÓGICA (El "Hilo Conductor")
# ==========================================
def synthesize_epistemic_debate(
    llm_client,
    conn: sqlite3.Connection,
    concept: str,
    dois_to_analyze: List[str]
) -> Dict[str, Any]:
    """
    Responde: ¿Cómo conversan estos autores sobre el concepto X?
    Utiliza el grafo de co-citación para entender sus escuelas de pensamiento.
    """
    # 1. Obtener metadatos de los papers
    papers_data = []
    for doi in dois_to_analyze:
        art = db.get_article(conn, doi)
        if art:
            papers_data.append({
                "doi": art.get("doi"),
                "title": art.get("title"),
                "year": art.get("year"),
                "abstract": (art.get("abstract") or "")[:1000],
                "authors": [f"{a.get('family')}, {a.get('given')}" for a in (art.get("authors") or []) if isinstance(a, dict)]
            })
            
    if not papers_data:
        return {"error": "No se encontraron papers válidos para sintetizar."}

    # 2. Obtener el contexto estructural (¿Están en el mismo clúster epistemológico?)
    graph = epistemic.build_epistemic_graph(conn, seed_dois=dois_to_analyze)
    clusters = graph.get("cocitation_clusters", [])
    
    # Mapear qué clúster pertenece a cada DOI
    doi_cluster_map = {}
    for i, cluster in enumerate(clusters):
        for doi_in_cluster in cluster:
            doi_cluster_map[doi_in_cluster.lower()] = f"Escuela/Clúster {i+1}"

    context_papers = "\n\n".join([
        f"Paper {i+1} ({p['doi']}): {p['title']} ({p['year']}). "
        f"Autores: {', '.join(p['authors'][:3])}. "
        f"Resumen: {p['abstract']}. "
        f"Clúster Epistemológico: {doi_cluster_map.get(p['doi'].lower(), 'No agrupado / Puente')}"
        for i, p in enumerate(papers_data)
    ])

    prompt = f"""
    Concepto central a analizar: "{concept}"
    
    CONTEXTO DE LOS PAPERS Y SUS ESCUELAS DE PENSAMIENTO:
    {context_papers}
    
    TAREA DE SÍNTESIS EPISTEMOLÓGICA:
    1. Identifica las posturas fundamentales sobre "{concept}" presentes en estos papers.
    2. ¿Hay linajes de citación? (Ej. "El Autor A basa su trabajo en la teoría del Autor B, pero el Autor C la critica empíricamente").
    3. ¿Qué "hueco" (gap) epistemológico o metodológico queda tras leer esta conversación?
    
    Responde EXCLUSIVAMENTE en este formato JSON:
    {{
        "core_debates": [
            {{"stance": "Descripción de la postura", "representative_authors": ["Autor X"], "epistemic_role": "Teórico/Empírico/Crítico"}}
        ],
        "citation_lineage": "Descripción de cómo se citan o contradicen entre sí (máx 3 frases).",
        "identified_gap": "Descripción del vacío de investigación que justifica futuros estudios.",
        "methodological_trend": "Tendencia en los diseños metodológicos usados para estudiar este concepto."
    }}
    """
    
    try:
        response = llm_client.chat(system=SYSTEM_PROMPT, user=prompt, response_format="json")
        return json.loads(response)
    except Exception as e:
        log.error(f"Error en síntesis epistemológica: {e}")
        return {"error": str(e)}


# ==========================================
# 4. EXTRACCIÓN DE DISEÑO METODOLÓGICO (Scoping Review)
# ==========================================
def extract_methodology(
    llm_client,
    papers: List[Dict]
) -> List[Dict]:
    """
    Extrae el diseño metodológico, muestra y técnicas de análisis.
    Vital para la tabla de características de una Scoping Review.
    """
    extracted = []
    for paper in papers:
        context = f"Título: {paper.get('title')}\nResumen: {paper.get('abstract')}"
        prompt = f"""
        Analiza el siguiente artículo científico y extrae su arquitectura metodológica.
        {context}
        
        Responde en JSON:
        {{
            "doi": "{paper.get('doi')}",
            "design": "Ej. Transversal, Experimental, Etnografía, Revisión Sistemática",
            "sample_size": "Ej. N=350, o 'Cualitativo (15 entrevistas)'",
            "data_collection": "Ej. Encuestas, Análisis de contenido, Scrapy",
            "analysis_technique": "Ej. SEM, ANOVA, Teoría fundamentada",
            "geographical_context": "País o región del estudio"
        }}
        """
        try:
            response = llm_client.chat(system=SYSTEM_PROMPT, user=prompt, response_format="json")
            data = json.loads(response)
            data["doi"] = paper.get("doi") # Asegurar DOI
            extracted.append(data)
        except Exception as e:
            extracted.append({"doi": paper.get("doi"), "error": str(e)})
            
    return extracted

________________________________________________________________________

el objetivo central es tener una **IA especializada en Revisiones Sistemáticas (PRISMA) y Scoping Reviews (JBI)**, vamos a dar el salto al **Paso 3: La Integración del Agente IA (`review_agent.py`)**.

Para que esta IA no sea un simple "resumidor semántico" (que es lo que hacen las herramientas genéricas), la vamos a diseñar como un **Auditor Epistemológico**. La IA no leerá los papers para "sacar la idea principal", sino que los cruzará con el **Grafo Epistemológico** que construimos en el Paso 2 para responder a las preguntas estructurales de una revisión sistemática.

Aquí tiene el módulo `review_agent.py`. Está diseñado para conectarse a cualquier LLM (OpenAI, Anthropic, Ollama local) y devolver datos estructurados en JSON para que su frontend (PWA) los renderice en tablas PRISMA y mapas.

### Paso 3: El Motor de IA para Revisiones Sistemáticas (`review_agent.py`)

Cree este nuevo archivo en el proyecto.

"""
review_agent.py
Motor de Inteligencia Artificial para Revisiones Sistemáticas y Scoping Reviews.
Enfoque: Auditoría Epistemológica, Cribado PRISMA (PICO/SPIDER) y Síntesis Estructural.
No resume textos: mapea la estructura del conocimiento y extrae datos metodológicos.
"""
import json
import sqlite3
import logging
from typing import List, Dict, Any
from . import db, epistemic

log = logging.getLogger("radar.review_agent")

# ==========================================
# 1. SYSTEM PROMPT: EL REVISOR PAR EXPERTO
# ==========================================
SYSTEM_PROMPT = """
Eres un Investigador Principal y Metodólogo experto en Revisiones Sistemáticas (PRISMA/Cochrane) 
y Scoping Reviews (JBI). Tu función NO es resumir textos de forma semántica, sino analizar 
la EPISTEMOLOGÍA y la ESTRUCTURA de la literatura científica.

REGLAS INQUEBRANTABLES:
1. CERO ALUCINACIÓN: Si la información no está explícita en el contexto proporcionado, debes marcarlo como "No reportado" o "Null".
2. ENFOQUE EPISTEMOLÓGICO: Cuando analices debates, no busques similitud de palabras. Busca linajes: 
   ¿Quién cita a quién? ¿Quién contradice la metodología de quién? ¿Qué escuela de pensamiento representan?
3. RIGOR METODOLÓGICO: Identifica el diseño exacto (ej. "Estudio transversal", "Etnografía", "Meta-análisis de red").
4. FORMATO: Responde SIEMPRE en JSON válido, sin markdown, sin texto fuera del objeto JSON.
"""

# ==========================================
# 2. MOTOR DE CRIBADO (SCREENING PRISMA/JBI)
# ==========================================
def screen_papers_for_protocol(
    llm_client, 
    papers: List[Dict], 
    inclusion_criteria: str, 
    exclusion_criteria: str,
    framework: str = "PICO"
) -> Dict[str, Any]:
    """
    Evalúa artículos contra criterios de inclusión/exclusión.
    Devuelve la clasificación PRISMA: Included, Excluded, Maybe.
    """
    results = {"included": [], "excluded": [], "maybe": [], "reasoning": {}}
    
    for paper in papers:
        context = f"""
        Título: {paper.get('title')}
        Resumen: {paper.get('abstract')}
        Palabras clave: {paper.get('keywords')}
        Metodología declarada: {paper.get('type') or 'Desconocida'}
        """
        
        prompt = f"""
        Marco de referencia: {framework}
        Criterios de INCLUSIÓN: {inclusion_criteria}
        Criterios de EXCLUSIÓN: {exclusion_criteria}
        
        Paper a evaluar:
        {context}
        
        TAREA: Evalúa si este paper entra, sale o requiere revisión humana.
        Responde EXCLUSIVAMENTE en este formato JSON:
        {{
            "decision": "included" | "excluded" | "maybe",
            "reason": "Justificación técnica en 1-2 frases basada estrictamente en los criterios.",
            "extracted_pico": {{
                "population": "...",
                "intervention_phenomenon": "...",
                "context": "...",
                "methodology": "..."
            }}
        }}
        """
        
        try:
            response = llm_client.chat(system=SYSTEM_PROMPT, user=prompt, response_format="json")
            data = json.loads(response)
            
            decision = data.get("decision", "maybe")
            results[decision].append({
                "doi": paper.get("doi"),
                "title": paper.get("title"),
                "pico": data.get("extracted_pico", {})
            })
            results["reasoning"][paper.get("doi")] = data.get("reason", "Sin justificación")
        except Exception as e:
            log.error(f"Error en cribado IA para {paper.get('doi')}: {e}")
            results["maybe"].append({"doi": paper.get("doi"), "title": paper.get("title"), "pico": {}})
            results["reasoning"][paper.get("doi")] = f"Error de parsing IA: {str(e)}"
            
    return results


# ==========================================
# 3. SÍNTESIS EPISTEMOLÓGICA (El "Hilo Conductor")
# ==========================================
def synthesize_epistemic_debate(
    llm_client,
    conn: sqlite3.Connection,
    concept: str,
    dois_to_analyze: List[str]
) -> Dict[str, Any]:
    """
    Responde: ¿Cómo conversan estos autores sobre el concepto X?
    Utiliza el grafo de co-citación para entender sus escuelas de pensamiento.
    """
    # 1. Obtener metadatos de los papers
    papers_data = []
    for doi in dois_to_analyze:
        art = db.get_article(conn, doi)
        if art:
            papers_data.append({
                "doi": art.get("doi"),
                "title": art.get("title"),
                "year": art.get("year"),
                "abstract": (art.get("abstract") or "")[:1000],
                "authors": [f"{a.get('family')}, {a.get('given')}" for a in (art.get("authors") or []) if isinstance(a, dict)]
            })
            
    if not papers_data:
        return {"error": "No se encontraron papers válidos para sintetizar."}

    # 2. Obtener el contexto estructural (¿Están en el mismo clúster epistemológico?)
    graph = epistemic.build_epistemic_graph(conn, seed_dois=dois_to_analyze)
    clusters = graph.get("cocitation_clusters", [])
    
    # Mapear qué clúster pertenece a cada DOI
    doi_cluster_map = {}
    for i, cluster in enumerate(clusters):
        for doi_in_cluster in cluster:
            doi_cluster_map[doi_in_cluster.lower()] = f"Escuela/Clúster {i+1}"

    context_papers = "\n\n".join([
        f"Paper {i+1} ({p['doi']}): {p['title']} ({p['year']}). "
        f"Autores: {', '.join(p['authors'][:3])}. "
        f"Resumen: {p['abstract']}. "
        f"Clúster Epistemológico: {doi_cluster_map.get(p['doi'].lower(), 'No agrupado / Puente')}"
        for i, p in enumerate(papers_data)
    ])

    prompt = f"""
    Concepto central a analizar: "{concept}"
    
    CONTEXTO DE LOS PAPERS Y SUS ESCUELAS DE PENSAMIENTO:
    {context_papers}
    
    TAREA DE SÍNTESIS EPISTEMOLÓGICA:
    1. Identifica las posturas fundamentales sobre "{concept}" presentes en estos papers.
    2. ¿Hay linajes de citación? (Ej. "El Autor A basa su trabajo en la teoría del Autor B, pero el Autor C la critica empíricamente").
    3. ¿Qué "hueco" (gap) epistemológico o metodológico queda tras leer esta conversación?
    
    Responde EXCLUSIVAMENTE en este formato JSON:
    {{
        "core_debates": [
            {{"stance": "Descripción de la postura", "representative_authors": ["Autor X"], "epistemic_role": "Teórico/Empírico/Crítico"}}
        ],
        "citation_lineage": "Descripción de cómo se citan o contradicen entre sí (máx 3 frases).",
        "identified_gap": "Descripción del vacío de investigación que justifica futuros estudios.",
        "methodological_trend": "Tendencia en los diseños metodológicos usados para estudiar este concepto."
    }}
    """
    
    try:
        response = llm_client.chat(system=SYSTEM_PROMPT, user=prompt, response_format="json")
        return json.loads(response)
    except Exception as e:
        log.error(f"Error en síntesis epistemológica: {e}")
        return {"error": str(e)}


# ==========================================
# 4. EXTRACCIÓN DE DISEÑO METODOLÓGICO (Scoping Review)
# ==========================================
def extract_methodology(
    llm_client,
    papers: List[Dict]
) -> List[Dict]:
    """
    Extrae el diseño metodológico, muestra y técnicas de análisis.
    Vital para la tabla de características de una Scoping Review.
    """
    extracted = []
    for paper in papers:
        context = f"Título: {paper.get('title')}\nResumen: {paper.get('abstract')}"
        prompt = f"""
        Analiza el siguiente artículo científico y extrae su arquitectura metodológica.
        {context}
        
        Responde en JSON:
        {{
            "doi": "{paper.get('doi')}",
            "design": "Ej. Transversal, Experimental, Etnografía, Revisión Sistemática",
            "sample_size": "Ej. N=350, o 'Cualitativo (15 entrevistas)'",
            "data_collection": "Ej. Encuestas, Análisis de contenido, Scrapy",
            "analysis_technique": "Ej. SEM, ANOVA, Teoría fundamentada",
            "geographical_context": "País o región del estudio"
        }}
        """
        try:
            response = llm_client.chat(system=SYSTEM_PROMPT, user=prompt, response_format="json")
            data = json.loads(response)
            data["doi"] = paper.get("doi") # Asegurar DOI
            extracted.append(data)
        except Exception as e:
            extracted.append({"doi": paper.get("doi"), "error": str(e)})
            
    return extracted
______________________________________________________________

### Integración en la API (`main.py`)

Para que su PWA (Frontend) pueda usar este motor, necesitamos exponer endpoints que orquesten el flujo de trabajo de una revisión sistemática. Añada esto a su `main.py`:

# En main.py, importar el nuevo módulo y un cliente LLM (ej. OpenAI, Anthropic, o su wrapper local)
from . import review_agent
from .llm_client import get_llm_client # Asuma que tiene esta función que devuelve su cliente LLM configurado

# ==========================================
# ENDPOINTS PARA REVISIÓN SISTEMÁTICA (PRISMA/JBI)
# ==========================================

@app.post("/api/review/screen")
def run_ai_screening(payload: dict = Body(...)):
    """
    Cribado PRISMA: Pasa artículos por los criterios de inclusión/exclusión usando IA.
    """
    inclusion = str(payload.get("inclusion_criteria") or "").strip()
    exclusion = str(payload.get("exclusion_criteria") or "").strip()
    framework = str(payload.get("framework", "PICO")).upper()
    dois = payload.get("dois", [])
    
    if not (inclusion and exclusion and dois):
        raise HTTPException(400, "inclusion_criteria, exclusion_criteria y dois son obligatorios")
        
    conn = db.connect()
    try:
        papers = [db.get_article(conn, doi) for doi in dois]
        papers = [p for p in papers if p] # Filtrar nulos
        
        llm = get_llm_client()
        screening_result = review_agent.screen_papers_for_protocol(
            llm, papers, inclusion, exclusion, framework
        )
        
        return {
            "status": "ok",
            "prisma_flow": {
                "identified": len(papers),
                "included": len(screening_result["included"]),
                "excluded": len(screening_result["excluded"]),
                "needs_review": len(screening_result["maybe"])
            },
            "details": screening_result
        }
    finally:
        conn.close()

@app.post("/api/review/synthesize")
def synthesize_epistemology(payload: dict = Body(...)):
    """
    La pregunta de oro: ¿Cómo conversan estos autores sobre este concepto?
    """
    concept = str(payload.get("concept") or "").strip()
    dois = payload.get("dois", [])
    
    if not concept or len(dois) < 2:
        raise HTTPException(400, "concept y al menos 2 dois son obligatorios")
        
    conn = db.connect()
    try:
        llm = get_llm_client()
        synthesis = review_agent.synthesize_epistemic_debate(
            llm, conn, concept, dois
        )
        return {"status": "ok", "synthesis": synthesis}
    finally:
        conn.close()

@app.post("/api/review/extract-methodology")
def extract_methodology(payload: dict = Body(...)):
    """
    Extracción de datos para tablas de características (Scoping Review).
    """
    dois = payload.get("dois", [])
    conn = db.connect()
    try:
        papers = [db.get_article(conn, doi) for doi in dois if db.get_article(conn, doi)]
        llm = get_llm_client()
        extracted = review_agent.extract_methodology(llm, papers)
        return {"status": "ok", "count": len(extracted), "methodologies": extracted}
    finally:
        conn.close()
____________________________________________________________________

la máquina lea el texto completo (o al menos los fragmentos donde ocurren las citaciones) y responda basándose en **evidencia textual real**, no en resúmenes genéricos.

Vamos a implementar esto en tres capas:

---

## CAPA 1: Extracción de Texto Completo (PDF → Markdown)

Primero necesitamos un módulo que convierta los PDFs en texto estructurado. Esto le dará a la IA el "cuerpo" del paper para leer.

"""
text_extractor.py
Convierte PDFs científicos en texto estructurado (Markdown) para análisis por IA.
Usa PyMuPDF (fitz) para extracción de alta calidad, preservando secciones, 
encabezados y referencias.
"""
import re
import logging
from pathlib import Path
from typing import Optional, Dict, List

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

log = logging.getLogger("radar.text_extractor")

# ==========================================
# 1. CONVERSIÓN PDF → MARKDOWN ESTRUCTURADO
# ==========================================

def extract_paper_to_markdown(pdf_path: str | Path) -> Optional[Dict]:
    """
    Convierte un PDF científico en Markdown estructurado.
    Preserva: Título, Abstract, Secciones, Referencias.
    
    Devuelve:
    {
        "full_text": "Texto completo en Markdown",
        "sections": {"abstract": "...", "introduction": "...", ...},
        "references": ["1. Autor (2020). Título...", ...],
        "word_count": 5420,
        "page_count": 15
    }
    """
    if not HAS_FITZ:
        log.error("PyMuPDF (fitz) no está instalado. Ejecute: pip install PyMuPDF")
        return None
    
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        log.error(f"PDF no encontrado: {pdf_path}")
        return None
    
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        log.error(f"Error abriendo PDF {pdf_path}: {e}")
        return None
    
    full_text = []
    sections = {}
    current_section = "preamble"
    current_text = []
    references = []
    in_references = False
    
    # Patrones para detectar secciones comunes en papers científicos
    section_patterns = [
        (r"^(?:\d+\.?\s*)?(abstract|resumen|suma?rio|summary)\b", "abstract"),
        (r"^(?:\d+\.?\s*)?(introduction|introducción|introducao)\b", "introduction"),
        (r"^(?:\d+\.?\s*)?(methods?|metodología|metodologia|métodos|metodos)\b", "methods"),
        (r"^(?:\d+\.?\s*)?(results?|resultados|resultados)\b", "results"),
        (r"^(?:\d+\.?\s*)?(discussion|discusión|discussao)\b", "discussion"),
        (r"^(?:\d+\.?\s*)?(conclusion|conclusión|conclusao|conclusiones)\b", "conclusion"),
        (r"^(?:\d+\.?\s*)?(references|referencias|bibliografía|bibliografia)\b", "references"),
    ]
    
    for page_num, page in enumerate(doc):
        blocks = page.get_text("blocks")
        
        for block in blocks:
            text = block[4].strip()  # block[4] es el texto
            if not text:
                continue
            
            # Detectar si es un encabezado de sección
            is_heading = False
            for pattern, section_name in section_patterns:
                if re.match(pattern, text.lower(), re.IGNORECASE):
                    # Guardar sección anterior
                    if current_text:
                        sections[current_section] = "\n".join(current_text)
                    
                    current_section = section_name
                    current_text = []
                    is_heading = True
                    
                    if section_name == "references":
                        in_references = True
                    
                    full_text.append(f"\n## {text}\n")
                    break
            
            if not is_heading:
                current_text.append(text)
                full_text.append(text)
                
                # Si estamos en referencias, capturar cada línea como referencia
                if in_references and len(text) > 20:
                    references.append(text)
    
    # Guardar última sección
    if current_text:
        sections[current_section] = "\n".join(current_text)
    
    doc.close()
    
    result = {
        "full_text": "\n\n".join(full_text),
        "sections": sections,
        "references": references,
        "word_count": len("\n".join(full_text).split()),
        "page_count": len(doc) if HAS_FITZ else 0,
        "pdf_path": str(pdf_path)
    }
    
    return result


# ==========================================
# 2. EXTRACCIÓN DE CONTEXTOS DE CITACIÓN
# ==========================================

def extract_citation_contexts(full_text: str, cited_doi: str, cited_author: str = None) -> List[Dict]:
    """
    Busca en el texto completo dónde y cómo se cita a un paper específico.
    
    Estrategias de búsqueda:
    1. Búsqueda por DOI (si está en el texto)
    2. Búsqueda por apellido del autor + año (ej. "Torres Salinas (2020)")
    3. Búsqueda por número de referencia (ej. "[2]", "(2)")
    
    Devuelve lista de contextos:
    [
        {
            "paragraph": "El enfoque de Torres Salinas (2020) demuestra que...",
            "sentence": "Torres Salinas (2020) demuestra que...",
            "sentiment": "positive",  # positive, negative, neutral, contrasting
            "section": "discussion",
            "context_type": "author_year"
        },
        ...
    ]
    """
    if not full_text or not cited_doi:
        return []
    
    contexts = []
    
    # Dividir el texto en párrafos
    paragraphs = re.split(r'\n\s*\n', full_text)
    
    # 1. Búsqueda por DOI (raro en texto, pero posible)
    doi_clean = cited_doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "")
    for para in paragraphs:
        if doi_clean in para:
            contexts.append({
                "paragraph": para.strip(),
                "sentence": _extract_relevant_sentence(para, doi_clean),
                "sentiment": _classify_sentiment(para),
                "section": _detect_section(para, full_text),
                "context_type": "doi"
            })
    
    # 2. Búsqueda por apellido + año (más común)
    if cited_author:
        # Extraer apellidos (última palabra antes de paréntesis con año)
        author_patterns = [
            rf"\b{re.escape(cited_author)}\s*(?:et al\.?)?\s*\(?(\d{{4}})\)?",  # "Torres Salinas (2020)"
            rf"\b{re.escape(cited_author)}\s*(?:et al\.?)?\s*,\s*(\d{{4}})",    # "Torres Salinas, 2020"
        ]
        
        for pattern in author_patterns:
            for match in re.finditer(pattern, full_text, re.IGNORECASE):
                # Extraer párrafo que contiene esta mención
                start = max(0, match.start() - 200)
                end = min(len(full_text), match.end() + 200)
                context_window = full_text[start:end]
                
                # Buscar el párrafo completo
                para_match = re.search(r'([^.!?]*[.!?])', context_window)
                if para_match:
                    sentence = para_match.group(1).strip()
                else:
                    sentence = context_window.strip()
                
                contexts.append({
                    "paragraph": context_window.strip(),
                    "sentence": sentence,
                    "sentiment": _classify_sentiment(context_window),
                    "section": _detect_section(context_window, full_text),
                    "context_type": "author_year",
                    "year": match.group(1) if match.lastindex else None
                })
    
    # 3. Búsqueda por número de referencia (ej. "[2]", "(2)")
    # Esto requiere conocer el número de referencia en la bibliografía
    # (Se implementaría en una segunda pasada si se tiene la lista de referencias)
    
    # Eliminar duplicados
    seen = set()
    unique_contexts = []
    for ctx in contexts:
        key = ctx["sentence"][:100]
        if key not in seen:
            seen.add(key)
            unique_contexts.append(ctx)
    
    return unique_contexts


def _extract_relevant_sentence(paragraph: str, search_term: str) -> str:
    """Extrae la oración específica que contiene el término buscado."""
    sentences = re.split(r'(?<=[.!?])\s+', paragraph)
    for sent in sentences:
        if search_term.lower() in sent.lower():
            return sent.strip()
    return paragraph[:200] + "..." if len(paragraph) > 200 else paragraph


def _classify_sentiment(text: str) -> str:
    """
    Clasificación heurística simple del sentimiento de la citación.
    (Para producción, usar un LLM o modelo de NLP fino)
    """
    text_lower = text.lower()
    
    positive_words = ["demuestra", "confirma", "apoya", "valida", "evidencia", "muestra", 
                      "confirms", "supports", "validates", "shows", "demuestra"]
    negative_words = ["contradice", "refuta", "cuestiona", "critica", "limita", 
                      "contradicts", "refutes", "questions", "criticizes", "limits"]
    contrasting_words = ["sin embargo", "no obstante", "aunque", "pero", 
                         "however", "although", "but", "nevertheless"]
    
    pos_count = sum(1 for w in positive_words if w in text_lower)
    neg_count = sum(1 for w in negative_words if w in text_lower)
    cont_count = sum(1 for w in contrasting_words if w in text_lower)
    
    if cont_count > 0:
        return "contrasting"
    elif pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    else:
        return "neutral"


def _detect_section(context_window: str, full_text: str) -> str:
    """Detecta en qué sección del paper ocurre la citación."""
    # Buscar el encabezado de sección más cercano antes del contexto
    pos = full_text.find(context_window[:50])
    if pos == -1:
        return "unknown"
    
    preceding_text = full_text[max(0, pos-500):pos]
    
    section_patterns = [
        (r"abstract|resumen", "abstract"),
        (r"introduction|introducción", "introduction"),
        (r"methods?|metodología", "methods"),
        (r"results?|resultados", "results"),
        (r"discussion|discusión", "discussion"),
        (r"conclusion|conclusión", "conclusion"),
    ]
    
    for pattern, section in section_patterns:
        if re.search(pattern, preceding_text, re.IGNORECASE):
            return section
    
    return "body"

________________________________________________________________________

## CAPA 2: Ajustes en la Base de Datos (`db.py`)

Necesitamos almacenar el texto completo y los contextos de citación extraídos.

# En db.py, añadir a init_db():

def init_text_storage(conn):
    """Inicializa tablas para almacenamiento de texto completo y contextos de citación."""
    
    # Texto completo de papers (para análisis por IA)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS article_fulltext (
            doi TEXT PRIMARY KEY,
            markdown_text TEXT NOT NULL,
            sections_json TEXT,          -- JSON con secciones estructuradas
            word_count INTEGER,
            page_count INTEGER,
            pdf_path TEXT,
            extracted_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(doi) REFERENCES articles(doi)
        )
    """)
    
    # Contextos de citación (dónde y cómo se cita a otro paper)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS citation_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            citing_doi TEXT NOT NULL,
            cited_doi TEXT NOT NULL,
            paragraph TEXT NOT NULL,
            sentence TEXT NOT NULL,
            sentiment TEXT,              -- positive, negative, neutral, contrasting
            section TEXT,                -- abstract, intro, methods, discussion, etc.
            context_type TEXT,           -- doi, author_year, ref_number
            extracted_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(citing_doi) REFERENCES articles(doi),
            FOREIGN KEY(cited_doi) REFERENCES articles(doi)
        )
    """)
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cit_context_citing ON citation_contexts(citing_doi)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cit_context_cited ON citation_contexts(cited_doi)")
    conn.commit()


# Funciones para guardar/recuperar texto completo

def save_article_fulltext(conn, doi: str, markdown_text: str, sections: dict, 
                          word_count: int, page_count: int, pdf_path: str = None):
    """Guarda el texto completo extraído de un PDF."""
    import json
    conn.execute("""
        INSERT OR REPLACE INTO article_fulltext 
        (doi, markdown_text, sections_json, word_count, page_count, pdf_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (doi.lower(), markdown_text, json.dumps(sections, ensure_ascii=False), 
          word_count, page_count, pdf_path))
    conn.commit()


def get_article_fulltext(conn, doi: str) -> dict | None:
    """Recupera el texto completo de un paper."""
    import json
    row = conn.execute("""
        SELECT markdown_text, sections_json, word_count, page_count 
        FROM article_fulltext WHERE doi = ?
    """, (doi.lower(),)).fetchone()
    
    if not row:
        return None
    
    return {
        "markdown_text": row["markdown_text"],
        "sections": json.loads(row["sections_json"]) if row["sections_json"] else {},
        "word_count": row["word_count"],
        "page_count": row["page_count"]
    }


def save_citation_context(conn, citing_doi: str, cited_doi: str, context: dict):
    """Guarda un contexto de citación extraído."""
    conn.execute("""
        INSERT INTO citation_contexts 
        (citing_doi, cited_doi, paragraph, sentence, sentiment, section, context_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (citing_doi.lower(), cited_doi.lower(), 
          context.get("paragraph"), context.get("sentence"), 
          context.get("sentiment"), context.get("section"), context.get("context_type")))
    conn.commit()


def get_citation_contexts(conn, citing_doi: str, cited_doi: str) -> list[dict]:
    """Recupera todos los contextos donde un paper cita a otro."""
    rows = conn.execute("""
        SELECT paragraph, sentence, sentiment, section, context_type
        FROM citation_contexts
        WHERE citing_doi = ? AND cited_doi = ?
        ORDER BY section
    """, (citing_doi.lower(), cited_doi.lower())).fetchall()
    
    return [dict(r) for r in rows]

________________________________________________________________________

"""
review_agent.py (VERSIÓN 2.0 - Con lectura real de papers)
Motor de IA para Revisiones Sistemáticas que lee el TEXTO COMPLETO 
y los CONTEXTOS DE CITACIÓN reales para evitar alucinaciones.
"""
import json
import sqlite3
import logging
from typing import List, Dict, Any
from . import db, epistemic, text_extractor

log = logging.getLogger("radar.review_agent")

# ==========================================
# SYSTEM PROMPT: EL REVISOR QUE LEE EVIDENCIA REAL
# ==========================================
SYSTEM_PROMPT = """
Eres un Investigador Principal experto en Revisiones Sistemáticas (PRISMA/Cochrane) 
y Scoping Reviews (JBI). Tu función es analizar EVIDENCIA TEXTUAL REAL extraída 
de los papers científicos.

REGLAS INQUEBRANTABLES:
1. CERO ALUCINACIÓN: Solo puedes afirmar lo que está EXPLÍCITO en los fragmentos de texto 
   proporcionados. Si no está en el texto, marca como "No reportado en el texto disponible".
2. CITAS TEXTUALES: Cuando afirmes algo, cita el fragmento exacto entre comillas.
3. ENFOQUE EPISTEMOLÓGICO: Analiza CÓMO se citan los papers (¿apoyan? ¿contradicen? ¿extienden?).
4. FORMATO: Responde SIEMPRE en JSON válido.
"""


# ==========================================
# SÍNTESIS EPISTEMOLÓGICA CON EVIDENCIA REAL
# ==========================================

def synthesize_epistemic_debate_with_evidence(
    llm_client,
    conn: sqlite3.Connection,
    concept: str,
    dois_to_analyze: List[str]
) -> Dict[str, Any]:
    """
    SÍNTESIS EPISTEMOLÓGICA que usa TEXTO COMPLETO y CONTEXTOS DE CITACIÓN reales.
    La IA NO inventa: lee los fragmentos extraídos de los papers.
    """
    
    # 1. Recopilar evidencia textual real
    evidence_pack = []
    
    for doi in dois_to_analyze:
        art = db.get_article(conn, doi)
        if not art:
            continue
        
        # Obtener texto completo si está disponible
        fulltext_data = db.get_article_fulltext(conn, doi)
        
        paper_evidence = {
            "doi": doi,
            "title": art.get("title"),
            "year": art.get("year"),
            "authors": [f"{a.get('family')}, {a.get('given')}" 
                       for a in (art.get("authors") or []) if isinstance(a, dict)][:3],
            "abstract": (art.get("abstract") or "")[:800],
        }
        
        # Si tenemos texto completo, extraer secciones relevantes
        if fulltext_data:
            sections = fulltext_data.get("sections", {})
            paper_evidence["has_fulltext"] = True
            paper_evidence["word_count"] = fulltext_data.get("word_count", 0)
            
            # Extraer fragmentos donde se menciona el concepto
            concept_mentions = _extract_concept_mentions(
                fulltext_data.get("markdown_text", ""), 
                concept
            )
            paper_evidence["concept_mentions"] = concept_mentions[:5]  # Top 5 menciones
            
            # Extraer secciones clave (si existen)
            for section_name in ["discussion", "conclusion", "results"]:
                if section_name in sections:
                    paper_evidence[f"{section_name}_excerpt"] = sections[section_name][:600]
        else:
            paper_evidence["has_fulltext"] = False
            paper_evidence["note"] = "Solo se dispone del resumen. Para análisis profundo, extraer PDF completo."
        
        # 2. Buscar contextos de citación (¿cómo cita este paper a los otros?)
        citation_contexts = []
        for other_doi in dois_to_analyze:
            if other_doi == doi:
                continue
            
            contexts = db.get_citation_contexts(conn, doi, other_doi)
            if contexts:
                citation_contexts.append({
                    "cited_paper": other_doi,
                    "contexts": contexts[:3]  # Top 3 contextos
                })
        
        if citation_contexts:
            paper_evidence["how_it_cites_others"] = citation_contexts
        
        evidence_pack.append(paper_evidence)
    
    if not evidence_pack:
        return {"error": "No se encontró evidencia textual para los DOIs proporcionados."}
    
    # 3. Construir prompt con EVIDENCIA REAL
    evidence_text = _format_evidence_for_prompt(evidence_pack, concept)
    
    prompt = f"""
CONCEPTO A ANALIZAR: "{concept}"

EVIDENCIA TEXTUAL REAL EXTRAÍDA DE LOS PAPERS:
{evidence_text}

TAREA DE SÍNTESIS EPISTEMOLÓGICA:

1. POSTURAS FUNDAMENTALES: Identifica las posturas sobre "{concept}" presentes en los papers.
   Para cada postura, CITA el fragmento exacto del texto que la sustenta.

2. LINAJES DE CITACIÓN: ¿Cómo se citan entre sí estos papers?
   - ¿Quién apoya a quién? (cita el fragmento donde se evidencia el apoyo)
   - ¿Quién contradice o cuestiona a quién? (cita el fragmento de la crítica)
   - ¿Quién extiende o aplica la teoría de quién?

3. HUECO EPISTEMOLÓGICO: ¿Qué vacío queda tras leer esta evidencia?
   ¿Qué preguntas no responden estos papers?

4. TENDENCIA METODOLÓGICA: ¿Qué métodos usan para estudiar "{concept}"?
   (Basado en las secciones de metodología o resultados extraídas)

Responde EXCLUSIVAMENTE en este formato JSON:
{{
    "core_debates": [
        {{
            "stance": "Descripción de la postura",
            "evidence_quote": "Fragmento textual exacto que sustenta esta postura",
            "representative_authors": ["Autor X"],
            "epistemic_role": "Teórico/Empírico/Crítico/Metodológico"
        }}
    ],
    "citation_lineage": {{
        "supports": [
            {{"citing": "Paper A", "cited": "Paper B", "evidence": "Fragmento donde A apoya a B"}}
        ],
        "contradicts": [
            {{"citing": "Paper A", "cited": "Paper B", "evidence": "Fragmento donde A critica a B"}}
        ],
        "extends": [
            {{"citing": "Paper A", "cited": "Paper B", "evidence": "Fragmento donde A extiende a B"}}
        ]
    }},
    "identified_gap": "Descripción del vacío de investigación con evidencia textual",
    "methodological_trend": "Tendencia en diseños metodológicos con evidencia de las secciones extraídas"
}}
"""
    
    try:
        response = llm_client.chat(system=SYSTEM_PROMPT, user=prompt, response_format="json")
        return json.loads(response)
    except Exception as e:
        log.error(f"Error en síntesis epistemológica con evidencia: {e}")
        return {"error": str(e), "evidence_pack_size": len(evidence_pack)}


def _extract_concept_mentions(full_text: str, concept: str, max_mentions: int = 10) -> List[str]:
    """
    Extrae los párrafos donde se menciona el concepto.
    Usa ventanas de contexto de 300 caracteres alrededor de cada mención.
    """
    if not full_text or not concept:
        return []
    
    mentions = []
    concept_lower = concept.lower()
    
    # Buscar todas las ocurrencias del concepto
    for match in re.finditer(re.escape(concept_lower), full_text.lower()):
        start = max(0, match.start() - 150)
        end = min(len(full_text), match.end() + 150)
        context = full_text[start:end].strip()
        
        # Limpiar saltos de línea excesivos
        context = re.sub(r'\s+', ' ', context)
        
        if context not in mentions:
            mentions.append(context)
        
        if len(mentions) >= max_mentions:
            break
    
    return mentions


def _format_evidence_for_prompt(evidence_pack: List[Dict], concept: str) -> str:
    """Formatea la evidencia para inyectarla en el prompt de la IA."""
    formatted = []
    
    for i, paper in enumerate(evidence_pack, 1):
        section = [f"\n{'='*60}\nPAPER {i}: {paper['title']} ({paper['year']})"]
        section.append(f"Autores: {', '.join(paper['authors'])}")
        section.append(f"DOI: {paper['doi']}")
        
        if paper.get("has_fulltext"):
            section.append(f"[TEXTO COMPLETO DISPONIBLE - {paper.get('word_count', 0)} palabras]")
            
            # Menciones del concepto
            if paper.get("concept_mentions"):
                section.append(f"\n--- FRAGMENTOS DONDE SE MENCIONA '{concept}' ---")
                for j, mention in enumerate(paper["concept_mentions"], 1):
                    section.append(f"[Mención {j}]: \"{mention}\"")
            
            # Excerpts de secciones clave
            for section_name in ["discussion", "conclusion", "results"]:
                excerpt_key = f"{section_name}_excerpt"
                if paper.get(excerpt_key):
                    section.append(f"\n--- SECCIÓN: {section_name.upper()} ---")
                    section.append(paper[excerpt_key])
        else:
            section.append("[SOLO RESUMEN DISPONIBLE]")
            section.append(f"\nResumen: {paper['abstract']}")
        
        # Contextos de citación
        if paper.get("how_it_cites_others"):
            section.append(f"\n--- CÓMO CITA ESTE PAPER A LOS OTROS ---")
            for cit in paper["how_it_cites_others"]:
                section.append(f"\nCita a: {cit['cited_paper']}")
                for ctx in cit["contexts"]:
                    sentiment_emoji = {"positive": "✓", "negative": "✗", "contrasting": "↔", "neutral": "·"}.get(ctx.get("sentiment"), "·")
                    section.append(f"  {sentiment_emoji} [{ctx.get('section', 'unknown')}]: \"{ctx.get('sentence', '')}\"")
        
        formatted.append("\n".join(section))
    
    return "\n".join(formatted)
__________________________________________________________________________


## CAPA 3: La IA que REALMENTE lee los papers (`review_agent.py` mejorado)

Ahora sí, vamos a modificar el agente IA para que use el texto completo y los contextos de citación reales.

"""
review_agent.py (VERSIÓN 2.0 - Con lectura real de papers)
Motor de IA para Revisiones Sistemáticas que lee el TEXTO COMPLETO 
y los CONTEXTOS DE CITACIÓN reales para evitar alucinaciones.
"""
import json
import sqlite3
import logging
from typing import List, Dict, Any
from . import db, epistemic, text_extractor

log = logging.getLogger("radar.review_agent")

# ==========================================
# SYSTEM PROMPT: EL REVISOR QUE LEE EVIDENCIA REAL
# ==========================================
SYSTEM_PROMPT = """
Eres un Investigador Principal experto en Revisiones Sistemáticas (PRISMA/Cochrane) 
y Scoping Reviews (JBI). Tu función es analizar EVIDENCIA TEXTUAL REAL extraída 
de los papers científicos.

REGLAS INQUEBRANTABLES:
1. CERO ALUCINACIÓN: Solo puedes afirmar lo que está EXPLÍCITO en los fragmentos de texto 
   proporcionados. Si no está en el texto, marca como "No reportado en el texto disponible".
2. CITAS TEXTUALES: Cuando afirmes algo, cita el fragmento exacto entre comillas.
3. ENFOQUE EPISTEMOLÓGICO: Analiza CÓMO se citan los papers (¿apoyan? ¿contradicen? ¿extienden?).
4. FORMATO: Responde SIEMPRE en JSON válido.
"""


# ==========================================
# SÍNTESIS EPISTEMOLÓGICA CON EVIDENCIA REAL
# ==========================================

def synthesize_epistemic_debate_with_evidence(
    llm_client,
    conn: sqlite3.Connection,
    concept: str,
    dois_to_analyze: List[str]
) -> Dict[str, Any]:
    """
    SÍNTESIS EPISTEMOLÓGICA que usa TEXTO COMPLETO y CONTEXTOS DE CITACIÓN reales.
    La IA NO inventa: lee los fragmentos extraídos de los papers.
    """
    
    # 1. Recopilar evidencia textual real
    evidence_pack = []
    
    for doi in dois_to_analyze:
        art = db.get_article(conn, doi)
        if not art:
            continue
        
        # Obtener texto completo si está disponible
        fulltext_data = db.get_article_fulltext(conn, doi)
        
        paper_evidence = {
            "doi": doi,
            "title": art.get("title"),
            "year": art.get("year"),
            "authors": [f"{a.get('family')}, {a.get('given')}" 
                       for a in (art.get("authors") or []) if isinstance(a, dict)][:3],
            "abstract": (art.get("abstract") or "")[:800],
        }
        
        # Si tenemos texto completo, extraer secciones relevantes
        if fulltext_data:
            sections = fulltext_data.get("sections", {})
            paper_evidence["has_fulltext"] = True
            paper_evidence["word_count"] = fulltext_data.get("word_count", 0)
            
            # Extraer fragmentos donde se menciona el concepto
            concept_mentions = _extract_concept_mentions(
                fulltext_data.get("markdown_text", ""), 
                concept
            )
            paper_evidence["concept_mentions"] = concept_mentions[:5]  # Top 5 menciones
            
            # Extraer secciones clave (si existen)
            for section_name in ["discussion", "conclusion", "results"]:
                if section_name in sections:
                    paper_evidence[f"{section_name}_excerpt"] = sections[section_name][:600]
        else:
            paper_evidence["has_fulltext"] = False
            paper_evidence["note"] = "Solo se dispone del resumen. Para análisis profundo, extraer PDF completo."
        
        # 2. Buscar contextos de citación (¿cómo cita este paper a los otros?)
        citation_contexts = []
        for other_doi in dois_to_analyze:
            if other_doi == doi:
                continue
            
            contexts = db.get_citation_contexts(conn, doi, other_doi)
            if contexts:
                citation_contexts.append({
                    "cited_paper": other_doi,
                    "contexts": contexts[:3]  # Top 3 contextos
                })
        
        if citation_contexts:
            paper_evidence["how_it_cites_others"] = citation_contexts
        
        evidence_pack.append(paper_evidence)
    
    if not evidence_pack:
        return {"error": "No se encontró evidencia textual para los DOIs proporcionados."}
    
    # 3. Construir prompt con EVIDENCIA REAL
    evidence_text = _format_evidence_for_prompt(evidence_pack, concept)
    
    prompt = f"""
CONCEPTO A ANALIZAR: "{concept}"

EVIDENCIA TEXTUAL REAL EXTRAÍDA DE LOS PAPERS:
{evidence_text}

TAREA DE SÍNTESIS EPISTEMOLÓGICA:

1. POSTURAS FUNDAMENTALES: Identifica las posturas sobre "{concept}" presentes en los papers.
   Para cada postura, CITA el fragmento exacto del texto que la sustenta.

2. LINAJES DE CITACIÓN: ¿Cómo se citan entre sí estos papers?
   - ¿Quién apoya a quién? (cita el fragmento donde se evidencia el apoyo)
   - ¿Quién contradice o cuestiona a quién? (cita el fragmento de la crítica)
   - ¿Quién extiende o aplica la teoría de quién?

3. HUECO EPISTEMOLÓGICO: ¿Qué vacío queda tras leer esta evidencia?
   ¿Qué preguntas no responden estos papers?

4. TENDENCIA METODOLÓGICA: ¿Qué métodos usan para estudiar "{concept}"?
   (Basado en las secciones de metodología o resultados extraídas)

Responde EXCLUSIVAMENTE en este formato JSON:
{{
    "core_debates": [
        {{
            "stance": "Descripción de la postura",
            "evidence_quote": "Fragmento textual exacto que sustenta esta postura",
            "representative_authors": ["Autor X"],
            "epistemic_role": "Teórico/Empírico/Crítico/Metodológico"
        }}
    ],
    "citation_lineage": {{
        "supports": [
            {{"citing": "Paper A", "cited": "Paper B", "evidence": "Fragmento donde A apoya a B"}}
        ],
        "contradicts": [
            {{"citing": "Paper A", "cited": "Paper B", "evidence": "Fragmento donde A critica a B"}}
        ],
        "extends": [
            {{"citing": "Paper A", "cited": "Paper B", "evidence": "Fragmento donde A extiende a B"}}
        ]
    }},
    "identified_gap": "Descripción del vacío de investigación con evidencia textual",
    "methodological_trend": "Tendencia en diseños metodológicos con evidencia de las secciones extraídas"
}}
"""
    
    try:
        response = llm_client.chat(system=SYSTEM_PROMPT, user=prompt, response_format="json")
        return json.loads(response)
    except Exception as e:
        log.error(f"Error en síntesis epistemológica con evidencia: {e}")
        return {"error": str(e), "evidence_pack_size": len(evidence_pack)}


def _extract_concept_mentions(full_text: str, concept: str, max_mentions: int = 10) -> List[str]:
    """
    Extrae los párrafos donde se menciona el concepto.
    Usa ventanas de contexto de 300 caracteres alrededor de cada mención.
    """
    if not full_text or not concept:
        return []
    
    mentions = []
    concept_lower = concept.lower()
    
    # Buscar todas las ocurrencias del concepto
    for match in re.finditer(re.escape(concept_lower), full_text.lower()):
        start = max(0, match.start() - 150)
        end = min(len(full_text), match.end() + 150)
        context = full_text[start:end].strip()
        
        # Limpiar saltos de línea excesivos
        context = re.sub(r'\s+', ' ', context)
        
        if context not in mentions:
            mentions.append(context)
        
        if len(mentions) >= max_mentions:
            break
    
    return mentions


def _format_evidence_for_prompt(evidence_pack: List[Dict], concept: str) -> str:
    """Formatea la evidencia para inyectarla en el prompt de la IA."""
    formatted = []
    
    for i, paper in enumerate(evidence_pack, 1):
        section = [f"\n{'='*60}\nPAPER {i}: {paper['title']} ({paper['year']})"]
        section.append(f"Autores: {', '.join(paper['authors'])}")
        section.append(f"DOI: {paper['doi']}")
        
        if paper.get("has_fulltext"):
            section.append(f"[TEXTO COMPLETO DISPONIBLE - {paper.get('word_count', 0)} palabras]")
            
            # Menciones del concepto
            if paper.get("concept_mentions"):
                section.append(f"\n--- FRAGMENTOS DONDE SE MENCIONA '{concept}' ---")
                for j, mention in enumerate(paper["concept_mentions"], 1):
                    section.append(f"[Mención {j}]: \"{mention}\"")
            
            # Excerpts de secciones clave
            for section_name in ["discussion", "conclusion", "results"]:
                excerpt_key = f"{section_name}_excerpt"
                if paper.get(excerpt_key):
                    section.append(f"\n--- SECCIÓN: {section_name.upper()} ---")
                    section.append(paper[excerpt_key])
        else:
            section.append("[SOLO RESUMEN DISPONIBLE]")
            section.append(f"\nResumen: {paper['abstract']}")
        
        # Contextos de citación
        if paper.get("how_it_cites_others"):
            section.append(f"\n--- CÓMO CITA ESTE PAPER A LOS OTROS ---")
            for cit in paper["how_it_cites_others"]:
                section.append(f"\nCita a: {cit['cited_paper']}")
                for ctx in cit["contexts"]:
                    sentiment_emoji = {"positive": "✓", "negative": "✗", "contrasting": "↔", "neutral": "·"}.get(ctx.get("sentiment"), "·")
                    section.append(f"  {sentiment_emoji} [{ctx.get('section', 'unknown')}]: \"{ctx.get('sentence', '')}\"")
        
        formatted.append("\n".join(section))
    
    return "\n".join(formatted)
______________________________________________________

## CAPA 4: Flujo de Trabajo Completo (End-to-End)

Ahora necesitamos un endpoint que orqueste todo: extraer PDF → guardar texto → analizar con IA.

# En main.py, añadir:

import tempfile
import shutil
from pathlib import Path
from . import text_extractor, review_agent

@app.post("/api/review/extract-and-analyze")
async def extract_and_analyze(
    dois: List[str] = Body(..., description="Lista de DOIs a analizar"),
    concept: str = Body(..., description="Concepto central a analizar"),
    pdf_files: List[UploadFile] = File(None, description="PDFs opcionales (si no están en el sistema)")
):
    """
    Flujo completo:
    1. Si se suben PDFs, extraer texto completo y guardar en BD
    2. Buscar contextos de citación entre los papers
    3. Ejecutar síntesis epistemológica con evidencia real
    """
    conn = db.connect()
    try:
        # 1. Procesar PDFs subidos (si existen)
        if pdf_files:
            for pdf_file in pdf_files:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    shutil.copyfileobj(pdf_file.file, tmp)
                    tmp_path = tmp.name
                
                try:
                    # Extraer texto
                    extracted = text_extractor.extract_paper_to_markdown(tmp_path)
                    if extracted:
                        # Buscar el DOI asociado (asumimos que el nombre del archivo contiene el DOI)
                        # En producción, esto debería venir de un mapeo DOI → PDF
                        doi = pdf_file.filename.replace(".pdf", "").lower()
                        
                        # Guardar en BD
                        db.save_article_fulltext(
                            conn, doi, 
                            extracted["full_text"], 
                            extracted["sections"],
                            extracted["word_count"],
                            extracted["page_count"],
                            tmp_path
                        )
                        
                        # Extraer contextos de citación
                        for other_doi in dois:
                            if other_doi != doi:
                                other_art = db.get_article(conn, other_doi)
                                if other_art:
                                    other_authors = [f"{a.get('family')}" for a in (other_art.get("authors") or []) if isinstance(a, dict)]
                                    if other_authors:
                                        contexts = text_extractor.extract_citation_contexts(
                                            extracted["full_text"],
                                            other_doi,
                                            cited_author=other_authors[0]
                                        )
                                        for ctx in contexts:
                                            db.save_citation_context(conn, doi, other_doi, ctx)
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
        
        # 2. Ejecutar síntesis epistemológica con evidencia real
        llm = get_llm_client()
        synthesis = review_agent.synthesize_epistemic_debate_with_evidence(
            llm, conn, concept, dois
        )
        
        return {
            "status": "ok",
            "concept": concept,
            "papers_analyzed": len(dois),
            "synthesis": synthesis
        }
    finally:
        conn.close()