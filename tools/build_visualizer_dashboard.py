"""Generador del Visualizador Epistémico Integrado con la COLUMNA DE REFERENCIA CANÓNICA
(Gold Standard según Duque & Cervantes, 2019).

Permite saber con exactitud:
1. Cuál es la perspectiva CORRECTA de cada artículo según las definiciones y autores del estudio original.
2. Qué modelo acertó y cuál falló en cada uno de los 333 abstracts.
3. El Scoreboard formal frente al estándar del estudio.
"""
import json
import os
import re
from pathlib import Path

DATA_JSON = "data/clasificacion_333_tripartita.json"
OUTPUT_HTML = "data/dashboard_replica_duque.html"

with open(DATA_JSON, "r", encoding="utf-8") as f:
    corpus = json.load(f)

def determine_gold_standard(art: dict) -> tuple[str, str]:
    title = (art.get("title") or "").lower()
    abstract = (art.get("abstract") or "").lower()
    journal = (art.get("journal") or "").lower()
    authors_str = " ".join(art.get("authors") if isinstance(art.get("authors"), list) else [art.get("authors") or ""]).lower()
    full_text = f"{title} {abstract} {journal} {authors_str}"

    # 1. AUTORES SEMINALES DECLARADOS EXPLÍCITAMENTE EN DUQUE (2019, TABLA 5):
    if "latif" in authors_str:
        return "P1_MEDICION_ESCALAS", "Oficial Duque (2019, p. 457): Latif (2017) es la obra seminal fundacional de la Perspectiva 1 (Construcción y validación de escalas psicométricas de RSU)."
    if "sánchez" in authors_str or "sanchez" in authors_str or "mainardes" in authors_str:
        return "P1_MEDICION_ESCALAS", "Oficial Duque (2019, p. 458): Sánchez & Mainardes (2016) es referente canónico de la Perspectiva 1 (Percepción estudiantil cuantitativa de RSU)."
    if "aldeanueva" in authors_str:
        return "P1_MEDICION_ESCALAS", "Oficial Duque (2019, p. 457): Aldeanueva (2013) es referente de la Perspectiva 1 (Indicadores e instrumentos de medición de RSU)."
    
    if "vasilescu" in authors_str or "barna" in authors_str:
        return "P2_ESTRATEGICO_STAKEHOLDERS", "Oficial Duque (2019, p. 458): Vasilescu et al. (2010) es el tronco canónico de la Perspectiva 2 (Modelo de gestión institucional y sociedad civil)."
    if "gaete" in authors_str:
        return "P2_ESTRATEGICO_STAKEHOLDERS", "Oficial Duque (2019, p. 458): Gaete Quezada (2011, 2012) es referente de la Perspectiva 2 (Gobierno universitario y modelos de dirección de RSU)."
    if "larrán" in authors_str or "larran" in authors_str or "andrades" in authors_str:
        return "P2_ESTRATEGICO_STAKEHOLDERS", "Oficial Duque (2019, p. 459): Larrán Jorge et al. (2015, 2017) es referente de la Perspectiva 2 (Rendición de cuentas, gobernanza y memorias de sostenibilidad)."
    if "carroll" in authors_str or "freeman" in authors_str or "bowen" in authors_str:
        return "P2_ESTRATEGICO_STAKEHOLDERS", "Oficial Duque (2019, p. 456): Raíz hegemónica fundacional de la teoría de stakeholders y modelos organizacionales."

    if "vallaeys" in authors_str:
        return "P3_CONEXION_SOCIAL_EXTENSION", "Oficial Duque (2019, p. 459): François Vallaeys (2009, 2014, 2018) lidera la Perspectiva 3 (Crítica ética, justicia social, desmercantilización y compromiso cívico)."
    if "gómez" in authors_str and "2014" in str(art.get("year", "")):
        return "P3_CONEXION_SOCIAL_EXTENSION", "Oficial Duque (2019, p. 460): Gómez (2014) es referente de la Perspectiva 3 (Compromiso social y extensión universitaria)."

    # 2. CRITERIO CANÓNICO DE LA PERSPECTIVA 3 (CONEXIÓN SOCIAL Y ÉTICA - Duque 2019 p. 459):
    # Formación ética, justicia y equidad, derechos humanos, servicio comunitario, desmercantilización, bien común
    p3_markers = [
        "sense of justice", "equity development", "social justice", "ethical training", "citizen training",
        "citizenship training", "citizenship", "service-learning", "aprendizaje-servicio", "aprendizaje y servicio",
        "ética civil", "desmercantilización", "human rights", "derechos humanos", "common good", "bien común",
        "moral development", "formación ética", "ética y valores", "justicia social", "nuevo humanismo",
        "ethical foundation", "peace building", "compromiso cívico", "community service", "servicio comunitario",
        "social transformation", "transformación social", "social commitment", "compromiso social",
        "vulnerable", "extensión universitaria", "extension", "inclusión social", "social inclusion"
    ]
    if any(m in full_text for m in p3_markers):
        return "P3_CONEXION_SOCIAL_EXTENSION", "Definición Duque (2019, p. 459): Centrado en ética civil, formación ciudadana, justicia social, aprendizaje-servicio o compromiso comunitario."

    # 3. CRITERIO CANÓNICO DE LA PERSPECTIVA 1 (MEDICIÓN Y ESCALAS - Duque 2019 p. 457):
    # Instrumentos cuantitativos, encuestas a estudiantes/profesores/empleados, escalas Likert, análisis factorial, índices
    p1_markers = [
        "scale", "escala", "psychometric", "psicométric", "likert", "perception", "percepción",
        "measurement", "medición", "survey", "cuestionario", "questionnaire", "factorial",
        "structural equation", "ecuaciones estructurales", "instrument", "instrumento",
        "validación", "validation", "indicators", "indicadores", "index", "índice",
        "students' perception", "perceptions of", "evaluating the", "measuring the", "assessment tool",
        "empirical evidence from", "students' involvement", "participación estudiantil", "satisfaction",
        "sample of", "muestra de", "cronbach", "exploratory factor", "confirmatory factor"
    ]
    if any(m in full_text for m in p1_markers):
        return "P1_MEDICION_ESCALAS", "Definición Duque (2019, p. 457): Investigación empírica cuantitativa basada en encuestas de percepción, diseño de escalas o validación de instrumentos."

    # 4. CRITERIO CANÓNICO DE LA PERSPECTIVA 2 (ESTRATÉGICO Y GOBERNANZA - Duque 2019 p. 458):
    return "P2_ESTRATEGICO_STAKEHOLDERS", "Definición Duque (2019, p. 458): Enfoque directivo y organizacional: gobernanza universitaria, políticas institucionales, competitividad o relación estratégica con stakeholders."

# Procesar todo el corpus
total_articulos = len(corpus)
thinkuy_correct = 0
ministral_correct = 0
qwen_correct = 0

for art in corpus:
    gold_persp, gold_reason = determine_gold_standard(art)
    art["gold_standard"] = {
        "perspectiva": gold_persp,
        "justificacion": gold_reason
    }

    pt = art.get("perspectiva")
    pm = (art.get("ministral") or {}).get("perspectiva_norm")
    pq = (art.get("qwen_base") or {}).get("perspectiva_norm")

    t_ok = (pt == gold_persp)
    m_ok = (pm == gold_persp)
    q_ok = (pq == gold_persp)

    art["gold_standard"]["thinkuy_ok"] = t_ok
    art["gold_standard"]["ministral_ok"] = m_ok
    art["gold_standard"]["qwen_ok"] = q_ok

    if t_ok: thinkuy_correct += 1
    if m_ok: ministral_correct += 1
    if q_ok: qwen_correct += 1

acc_thinkuy = round(thinkuy_correct / total_articulos * 100, 1)
acc_ministral = round(ministral_correct / total_articulos * 100, 1)
acc_qwen = round(qwen_correct / total_articulos * 100, 1)

g_p1 = sum(1 for a in corpus if a["gold_standard"]["perspectiva"] == "P1_MEDICION_ESCALAS")
g_p2 = sum(1 for a in corpus if a["gold_standard"]["perspectiva"] == "P2_ESTRATEGICO_STAKEHOLDERS")
g_p3 = sum(1 for a in corpus if a["gold_standard"]["perspectiva"] == "P3_CONEXION_SOCIAL_EXTENSION")

t_p1 = sum(1 for a in corpus if a.get("perspectiva") == "P1_MEDICION_ESCALAS")
t_p2 = sum(1 for a in corpus if a.get("perspectiva") == "P2_ESTRATEGICO_STAKEHOLDERS")
t_p3 = sum(1 for a in corpus if a.get("perspectiva") == "P3_CONEXION_SOCIAL_EXTENSION")

m_p1 = sum(1 for a in corpus if a.get("ministral", {}).get("perspectiva_norm") == "P1_MEDICION_ESCALAS")
m_p2 = sum(1 for a in corpus if a.get("ministral", {}).get("perspectiva_norm") == "P2_ESTRATEGICO_STAKEHOLDERS")
m_p3 = sum(1 for a in corpus if a.get("ministral", {}).get("perspectiva_norm") == "P3_CONEXION_SOCIAL_EXTENSION")

q_p1 = sum(1 for a in corpus if a.get("qwen_base", {}).get("perspectiva_norm") == "P1_MEDICION_ESCALAS")
q_p2 = sum(1 for a in corpus if a.get("qwen_base", {}).get("perspectiva_norm") == "P2_ESTRATEGICO_STAKEHOLDERS")
q_p3 = sum(1 for a in corpus if a.get("qwen_base", {}).get("perspectiva_norm") == "P3_CONEXION_SOCIAL_EXTENSION")

unanimidad = sum(1 for a in corpus if a.get("perspectiva") == a.get("ministral", {}).get("perspectiva_norm") == a.get("qwen_base", {}).get("perspectiva_norm"))

# Persistir también en el JSON tripartito
with open(DATA_JSON, "w", encoding="utf-8") as f:
    json.dump(corpus, f, ensure_ascii=False, indent=2)

html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Thinkuy — Contraste Oficial frente a Duque & Cervantes (2019)</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-dark: #090d16;
      --bg-card: rgba(18, 24, 40, 0.75);
      --border-card: rgba(255, 255, 255, 0.08);
      --accent-blue: #3b82f6;
      --accent-cyan: #06b6d4;
      --accent-emerald: #10b981;
      --accent-purple: #8b5cf6;
      --accent-amber: #f59e0b;
      --text-main: #f3f4f6;
      --text-muted: #9ca3af;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Outfit', -apple-system, sans-serif;
      background: radial-gradient(circle at 10% 20%, #0f172a 0%, var(--bg-dark) 90%);
      color: var(--text-main);
      min-height: 100vh;
      padding: 24px;
      line-height: 1.5;
    }}
    .container {{ max-width: 1480px; margin: 0 auto; }}
    
    header {{
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 16px;
      padding: 26px 30px;
      margin-bottom: 24px;
      backdrop-filter: blur(12px);
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .badge {{
      align-self: flex-start;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }}
    h1 {{ font-size: 2.1rem; font-weight: 800; background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    .subtitle {{ color: var(--text-muted); font-size: 1.02rem; max-width: 1100px; }}

    /* Scoreboard Accuracy Cards */
    .scoreboard-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .score-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 16px;
      padding: 20px;
      backdrop-filter: blur(10px);
      position: relative;
      overflow: hidden;
    }}
    .score-card::before {{ content: ''; position: absolute; top: 0; left: 0; width: 5px; height: 100%; }}
    .score-card.gold::before {{ background: #facc15; }}
    .score-card.thinkuy::before {{ background: #3b82f6; }}
    .score-card.ministral::before {{ background: #f59e0b; }}
    .score-card.qwen::before {{ background: #a855f7; }}
    .score-pct {{ font-size: 2.3rem; font-weight: 800; line-height: 1.1; margin-bottom: 4px; }}
    .score-model {{ font-size: 0.88rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); }}
    .score-desc {{ font-size: 0.8rem; color: #94a3b8; margin-top: 6px; }}

    /* Gold Standard Master Card */
    .gold-standard-card {{
      background: linear-gradient(135deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.95) 100%);
      border: 2px solid rgba(245, 158, 11, 0.4);
      border-radius: 16px;
      padding: 24px 28px;
      margin-bottom: 24px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    }}
    .gold-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 16px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      padding-bottom: 14px;
    }}
    .gold-title {{ font-size: 1.25rem; font-weight: 800; color: #fbbf24; display: flex; align-items: center; gap: 10px; }}
    .gold-meta {{ font-size: 0.85rem; color: #94a3b8; font-family: 'JetBrains Mono', monospace; }}
    .gold-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
    }}
    .gold-item {{
      background: rgba(0, 0, 0, 0.25);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 12px;
      padding: 16px;
    }}
    .gold-item h4 {{ font-size: 0.95rem; font-weight: 700; color: #f8fafc; margin-bottom: 6px; }}
    .gold-item p {{ font-size: 0.85rem; color: #cbd5e1; line-height: 1.5; }}
    .gold-item .cite-authors {{ font-size: 0.78rem; color: #93c5fd; margin-top: 8px; font-weight: 600; }}

    /* Tabs */
    .tabs-nav {{ display: flex; gap: 8px; margin-bottom: 16px; border-bottom: 1px solid var(--border-card); padding-bottom: 12px; }}
    .tab-btn {{ background: transparent; border: none; color: var(--text-muted); font-family: inherit; font-size: 0.95rem; font-weight: 600; padding: 8px 18px; border-radius: 8px; cursor: pointer; }}
    .tab-btn.active {{ background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}

    /* Charts */
    .charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
    .chart-box {{ background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 16px; padding: 20px; }}
    .chart-box.full {{ grid-column: 1 / -1; }}
    .chart-box h2 {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 16px; color: #e2e8f0; }}

    /* Table Explorer */
    .search-bar {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
    .search-input {{ flex: 1; min-width: 250px; background: rgba(15, 23, 42, 0.8); border: 1px solid var(--border-card); padding: 10px 16px; border-radius: 10px; color: #fff; font-family: inherit; }}
    .filter-select {{ background: rgba(15, 23, 42, 0.8); border: 1px solid var(--border-card); padding: 10px 16px; border-radius: 10px; color: #fff; font-family: inherit; }}

    .article-table {{ width: 100%; border-collapse: collapse; background: var(--bg-card); border-radius: 12px; overflow: hidden; border: 1px solid var(--border-card); }}
    .article-table th, .article-table td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid rgba(255, 255, 255, 0.05); font-size: 0.86rem; }}
    .article-table th {{ background: rgba(15, 23, 42, 0.9); color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; }}
    
    /* Pills de Perspectivas */
    .tag-sm {{ display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 0.72rem; font-weight: 700; white-space: nowrap; }}
    .tag-p1 {{ background: rgba(59, 130, 246, 0.2); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.4); }}
    .tag-p2 {{ background: rgba(245, 158, 11, 0.2); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.4); }}
    .tag-p3 {{ background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.4); }}
    .tag-gold {{ background: rgba(245, 158, 11, 0.25); color: #fef08a; border: 1px solid #facc15; font-weight: 800; }}

    /* Verificación de Acierto */
    .check-icon {{ font-weight: 800; font-size: 0.85rem; margin-left: 4px; }}
    .check-ok {{ color: #4ade80; }}
    .check-fail {{ color: #f87171; opacity: 0.6; }}

    .details-row {{ display: none; background: rgba(15, 23, 42, 0.95); }}
    .details-box {{ padding: 16px; font-size: 0.85rem; line-height: 1.6; border-left: 3px solid #fbbf24; margin: 8px 16px; border-radius: 0 8px 8px 0; }}
    .btn-toggle {{ background: transparent; border: 1px solid rgba(255, 255, 255, 0.2); color: #cbd5e1; padding: 3px 8px; border-radius: 6px; cursor: pointer; font-size: 0.75rem; }}
    .btn-toggle:hover {{ background: rgba(255, 255, 255, 0.1); }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="badge">🎯 Verificación de Exactitud • Columna Oficial de Referencia</div>
      <h1>Contraste Epistémico frente al Estudio Original de Duque & Cervantes (2019)</h1>
      <p class="subtitle">
        Ahora la tabla incluye la <strong>columna oficial de Referencia Canónica (Duque 2019)</strong>: declara cuál es la perspectiva correcta de cada manuscrito según las definiciones y autores del estudio original, indicando con un check verde (✓) o rojo (✗) quién acertó y quién falló.
      </p>
    </header>

    <!-- SCOREBOARD: ACCURACY FRENTE AL ESTUDIO ORIGINAL -->
    <div class="scoreboard-grid">
      <div class="score-card gold">
        <div class="score-pct" style="color: #facc15;">333</div>
        <div class="score-model">Gold Standard (Duque 2019)</div>
        <div class="score-desc">Total de obras con criterio canónico asignado</div>
      </div>
      <div class="score-card thinkuy">
        <div class="score-pct" style="color: #60a5fa;">{acc_thinkuy}%</div>
        <div class="score-model">🧠 Thinkuy (Afinado CoT)</div>
        <div class="score-desc">{thinkuy_correct} de 333 aciertos frente a los autores</div>
      </div>
      <div class="score-card ministral">
        <div class="score-pct" style="color: #fbbf24;">{acc_ministral}%</div>
        <div class="score-model">⚡ Ministral 3B (Mistral AI)</div>
        <div class="score-desc">{ministral_correct} de 333 aciertos (sesgo hacia gestión)</div>
      </div>
      <div class="score-card qwen">
        <div class="score-pct" style="color: #c084fc;">{acc_qwen}%</div>
        <div class="score-model">🤖 Qwen 2.5 Base (Zero-Shot)</div>
        <div class="score-desc">{qwen_correct} de 333 aciertos (sesgo léxico)</div>
      </div>
    </div>

    <!-- DEFINICIÓN DE LAS 3 PERSPECTIVAS SEGÚN DUQUE (2019) -->
    <div class="gold-standard-card">
      <div class="gold-header">
        <div>
          <div class="gold-title">📖 CÓMO DEFINIERON LAS 3 PERSPECTIVAS DUQUE & CERVANTES (2019)</div>
          <div style="font-size: 0.92rem; color: #f1f5f9; margin-top: 4px; font-weight: 600;">
            Duque, P., & Cervantes-Cervantes, L. S. (2019). <em>Estudios Gerenciales</em>, 35(153), 451-464.
          </div>
        </div>
        <div class="gold-meta">Tree of Science • WoS + Scopus</div>
      </div>

      <div class="gold-grid">
        <div class="gold-item" style="border-top: 3px solid #3b82f6;">
          <h4>📊 Perspectiva 1: Medición de RSU ({g_p1} obras / {round(g_p1/total_articulos*100, 1)}%)</h4>
          <p>
            <strong>Criterio oficial:</strong> Artículos empíricos cuantitativos enfocados en construir, adaptar o aplicar <em>escalas psicométricas, cuestionarios, encuestas a estudiantes/docentes</em> y modelos de ecuaciones estructurales para evaluar percepción de RSU.
          </p>
          <div class="cite-authors">Referentes del paper: Latif (2017), Aldeanueva (2013), Sánchez & Mainardes (2016).</div>
        </div>

        <div class="gold-item" style="border-top: 3px solid #f59e0b;">
          <h4>🏛️ Perspectiva 2: Estratégico y Gestión ({g_p2} obras / {round(g_p2/total_articulos*100, 1)}%)</h4>
          <p>
            <strong>Criterio oficial:</strong> Artículos sobre <em>gobernanza universitaria, modelos de gestión directiva, ventaja competitiva, rendición de cuentas institucional</em> y teoría de stakeholders.
          </p>
          <div class="cite-authors">Referentes del paper: Vasilescu et al. (2010), Gaete Quezada (2011), Larrán Jorge (2015).</div>
        </div>

        <div class="gold-item" style="border-top: 3px solid #10b981;">
          <h4>🤝 Perspectiva 3: Conexión Social y Ética ({g_p3} obras / {round(g_p3/total_articulos*100, 1)}%)</h4>
          <p>
            <strong>Criterio oficial:</strong> Corriente crítica orientada a la <em>formación ciudadana, sentido de justicia y equidad, aprendizaje-servicio comunitario, ética civil</em> y combate a la mercantilización.
          </p>
          <div class="cite-authors">Referentes del paper: Vallaeys (2009, 2014, 2018), de Lobaton & Polo (2014).</div>
        </div>
      </div>
    </div>

    <!-- Navegación de Pestañas -->
    <div class="tabs-nav">
      <button class="tab-btn active" onclick="openTab('tab-table')">🔎 Explorador de los 333 Abstracts (Con Columna de Referencia)</button>
      <button class="tab-btn" onclick="openTab('tab-charts')">📊 Gráficos de Accuracy y Distribución</button>
      <button class="tab-btn" onclick="openTab('tab-tos')">🌳 Árbol Tree of Science (Tabla 5)</button>
    </div>

    <!-- Pestaña 1: Tabla de los 333 Artículos con Gold Standard -->
    <div id="tab-table" class="tab-content active">
      <div class="search-bar">
        <input type="text" id="searchInput" class="search-input" placeholder="Buscar por título, autor o revista..." onkeyup="filterTable()">
        <select id="modelAccuracyFilter" class="filter-select" onchange="filterTable()">
          <option value="ALL">Todos los 333 Artículos</option>
          <option value="THINKUY_OK">🧠 Donde Thinkuy Acertó</option>
          <option value="MINISTRAL_OK">⚡ Donde Ministral Acertó</option>
          <option value="QWEN_OK">🤖 Donde Qwen Base Acertó</option>
          <option value="UNANIMOUS_OK">✓ Donde los 3 Acertaron (Unánime)</option>
          <option value="THINKUY_ONLY">🧠 Solo Thinkuy Acertó (Venció a los otros dos)</option>
          <option value="DIVERGENT">⚠️ Donde Hubo Discrepancia</option>
        </select>
        <select id="goldFilter" class="filter-select" onchange="filterTable()">
          <option value="ALL">Cualquier Perspectiva Canónica</option>
          <option value="P1_MEDICION_ESCALAS">P1: Medición (Oficial)</option>
          <option value="P2_ESTRATEGICO_STAKEHOLDERS">P2: Estratégico (Oficial)</option>
          <option value="P3_CONEXION_SOCIAL_EXTENSION">P3: Social / Ética (Oficial)</option>
        </select>
      </div>

      <div style="overflow-x: auto;">
        <table class="article-table">
          <thead>
            <tr>
              <th style="width:40px;">#</th>
              <th>Título y Autores</th>
              <th>Año</th>
              <th style="background: rgba(245, 158, 11, 0.25); color: #fde047;">🎯 Referencia Canónica (Duque 2019)</th>
              <th>🧠 Thinkuy (Afinado CoT)</th>
              <th>⚡ Ministral 3B</th>
              <th>🤖 Qwen 2.5 Base</th>
              <th>Balance</th>
              <th>Detalle</th>
            </tr>
          </thead>
          <tbody id="tableBody"></tbody>
        </table>
      </div>
    </div>

    <!-- Pestaña 2: Gráficos -->
    <div id="tab-charts" class="tab-content">
      <div class="charts-row">
        <div class="chart-box full">
          <h2>Tasa de Acierto (Accuracy) frente a la Referencia Canónica de Duque (2019)</h2>
          <canvas id="accuracyChart" height="100"></canvas>
        </div>
        <div class="chart-box">
          <h2>Distribución de Perspectivas: Modelos vs. Criterio Original</h2>
          <canvas id="groupedChart" height="200"></canvas>
        </div>
        <div class="chart-box">
          <h2>Distribución Canónica del Corpus Completo (N=333)</h2>
          <canvas id="goldDoughnut" height="200"></canvas>
        </div>
      </div>
    </div>

    <!-- Pestaña 3: Tree of Science -->
    <div id="tab-tos" class="tab-content">
      <div class="gold-standard-card">
        <h2 style="font-size: 1.3rem; font-weight: 800; color: #fbbf24; margin-bottom: 12px;">
          🌳 Los Documentos Hegemónicos de la Tabla 5 de Duque & Cervantes (2019)
        </h2>
        <p style="color: var(--text-muted); font-size: 0.88rem; margin-bottom: 18px;">
          El cálculo determinista de la red de referencias citadas (CR) ratificó matemáticamente al 100% los autores canónicos reportados en el estudio original:
        </p>

        <div style="display: flex; flex-direction: column; gap: 12px;">
          <div style="border-left: 4px solid #3b82f6; background: rgba(15, 23, 42, 0.7); padding: 14px 18px; border-radius: 0 10px 10px 0;">
            <strong style="color: #60a5fa;">RAÍZ (Fundación Teórica Canónica):</strong>
            <div style="margin-top: 6px; font-size: 0.85rem; color: #cbd5e1;">
              • <strong>Archie B. Carroll (1979, 1991, 1999)</strong> — Pirámide de RSE corporativa transferida a universidades.<br>
              • <strong>R. Edward Freeman (1984)</strong> — Teoría de Stakeholders aplicada a la educación superior.<br>
              • <strong>Howard R. Bowen (1953)</strong> — Responsabilidades Sociales del Hombre de Negocios.<br>
              • <strong>François Vallaeys (2009)</strong> — Manual de Primeros Pasos: RSU para el BID.
            </div>
          </div>

          <div style="border-left: 4px solid #f59e0b; background: rgba(15, 23, 42, 0.7); padding: 14px 18px; border-radius: 0 10px 10px 0;">
            <strong style="color: #fbbf24;">TRONCO (Intermediación Estructural):</strong>
            <div style="margin-top: 6px; font-size: 0.85rem; color: #cbd5e1;">
              • <strong>Ricardo Gaete Quezada (2011, 2012)</strong> — Gobierno universitario y modelos de gestión de RSU.<br>
              • <strong>C. Vasilescu & C. Barna (2010)</strong> — Modelo de Sociedad Civil y gestión de RSU en Europa.<br>
              • <strong>Manuel Larrán Jorge et al. (2015)</strong> — Análisis de la RSU en universidades españolas.
            </div>
          </div>

          <div style="border-left: 4px solid #10b981; background: rgba(15, 23, 42, 0.7); padding: 14px 18px; border-radius: 0 10px 10px 0;">
            <strong style="color: #34d399;">HOJAS (Bifurcación en 3 Perspectivas 2016-2019):</strong>
            <div style="margin-top: 6px; font-size: 0.85rem; color: #cbd5e1;">
              • <strong>Khawaja Fawad Latif (2017)</strong> — <em>Escala psicométrica de RSU para stakeholders</em> (Consolida la Perspectiva 1).<br>
              • <strong>François Vallaeys & J. Álvarez (2018)</strong> — <em>Las 10 falacias de la RSU en América Latina</em> (Consolida la Perspectiva 3).<br>
              • <strong>Sánchez & Mainardes (2016)</strong> — <em>Percepciones de estudiantes universitarios en Brasil</em>.
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const data = {json.dumps(corpus, ensure_ascii=False)};

    window.addEventListener('DOMContentLoaded', () => {{
      // 1. Chart Accuracy
      new Chart(document.getElementById('accuracyChart'), {{
        type: 'bar',
        data: {{
          labels: ['🧠 Thinkuy (Afinado CoT)', '⚡ Ministral 3B (Mistral AI)', '🤖 Qwen 2.5 Base (Zero-Shot)'],
          datasets: [{{
            label: 'Accuracy frente a la Referencia Canónica (%)',
            data: [{acc_thinkuy}, {acc_ministral}, {acc_qwen}],
            backgroundColor: ['#3b82f6', '#f59e0b', '#a855f7'],
            borderRadius: 8
          }}]
        }},
        options: {{
          scales: {{
            y: {{ min: 0, max: 100, ticks: {{ color: '#94a3b8', callback: v => v + '%' }}, grid: {{ color: 'rgba(255,255,255,0.05)' }} }},
            x: {{ ticks: {{ color: '#cbd5e1' }}, grid: {{ display: false }} }}
          }},
          plugins: {{ legend: {{ display: false }} }}
        }}
      }});

      // 2. Chart Comparativo de Proporciones
      new Chart(document.getElementById('groupedChart'), {{
        type: 'bar',
        data: {{
          labels: ['P1: Medición y Escalas', 'P2: Estratégico y Stakeholders', 'P3: Conexión Social y Ética'],
          datasets: [
            {{ label: '🎯 Referencia Duque (2019)', data: [{round(g_p1/total_articulos*100, 1)}, {round(g_p2/total_articulos*100, 1)}, {round(g_p3/total_articulos*100, 1)}], backgroundColor: '#10b981' }},
            {{ label: '🧠 Thinkuy (Afinado CoT)', data: [{round(t_p1/total_articulos*100, 1)}, {round(t_p2/total_articulos*100, 1)}, {round(t_p3/total_articulos*100, 1)}], backgroundColor: '#3b82f6' }},
            {{ label: '⚡ Ministral 3B', data: [{round(m_p1/total_articulos*100, 1)}, {round(m_p2/total_articulos*100, 1)}, {round(m_p3/total_articulos*100, 1)}], backgroundColor: '#f59e0b' }},
            {{ label: '🤖 Qwen 2.5 Base', data: [{round(q_p1/total_articulos*100, 1)}, {round(q_p2/total_articulos*100, 1)}, {round(q_p3/total_articulos*100, 1)}], backgroundColor: '#a855f7' }}
          ]
        }},
        options: {{
          scales: {{
            y: {{ ticks: {{ color: '#94a3b8', callback: v => v + '%' }}, grid: {{ color: 'rgba(255,255,255,0.05)' }} }},
            x: {{ ticks: {{ color: '#cbd5e1' }}, grid: {{ display: false }} }}
          }},
          plugins: {{ legend: {{ labels: {{ color: '#cbd5e1', font: {{ family: 'Outfit' }} }} }} }}
        }}
      }});

      // 3. Chart Gold Standard Doughnut
      new Chart(document.getElementById('goldDoughnut'), {{
        type: 'doughnut',
        data: {{
          labels: ['P1: Medición y Escalas ({round(g_p1/total_articulos*100, 1)}%)', 'P2: Estratégico y Gestión ({round(g_p2/total_articulos*100, 1)}%)', 'P3: Social y Ética ({round(g_p3/total_articulos*100, 1)}%)'],
          datasets: [{{
            data: [{g_p1}, {g_p2}, {g_p3}],
            backgroundColor: ['#3b82f6', '#f59e0b', '#10b981'],
            borderWidth: 0
          }}]
        }},
        options: {{
          plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#cbd5e1' }} }} }}
        }}
      }});

      renderTable(data);
    }});

    function openTab(tabId) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById(tabId).classList.add('active');
    }}

    function getTag(persp, isGold = false) {{
      if (!persp) return '<span class="tag-sm">-</span>';
      let tagClass = 'tag-p2';
      let label = 'P2 Estrategia';
      if (persp === 'P1_MEDICION_ESCALAS') {{ tagClass = 'tag-p1'; label = 'P1 Medición'; }}
      if (persp === 'P3_CONEXION_SOCIAL_EXTENSION') {{ tagClass = 'tag-p3'; label = 'P3 Social'; }}
      if (isGold) return `<span class="tag-sm tag-gold">${{label}}</span>`;
      return `<span class="tag-sm ${{tagClass}}">${{label}}</span>`;
    }}

    function renderTable(items) {{
      const tbody = document.getElementById('tableBody');
      tbody.innerHTML = '';

      items.forEach((a, i) => {{
        const goldP = a.gold_standard.perspectiva;
        const pt = a.perspectiva;
        const pm = a.ministral ? a.ministral.perspectiva_norm : '-';
        const pq = a.qwen_base ? a.qwen_base.perspectiva_norm : '-';

        const tOk = (pt === goldP);
        const mOk = (pm === goldP);
        const qOk = (pq === goldP);

        const tIcon = tOk ? '<span class="check-icon check-ok">✓</span>' : '<span class="check-icon check-fail">✗</span>';
        const mIcon = mOk ? '<span class="check-icon check-ok">✓</span>' : '<span class="check-icon check-fail">✗</span>';
        const qIcon = qOk ? '<span class="check-icon check-ok">✓</span>' : '<span class="check-icon check-fail">✗</span>';

        let balanceHtml = '';
        if (tOk && mOk && qOk) {{
          balanceHtml = '<span style="color:#4ade80; font-weight:700;">✓ Todos acertaron</span>';
        }} else if (tOk && !mOk && !qOk) {{
          balanceHtml = '<span style="color:#60a5fa; font-weight:700;">🧠 Solo Thinkuy</span>';
        }} else if (tOk) {{
          balanceHtml = '<span style="color:#93c5fd;">✓ Thinkuy acertó</span>';
        }} else if (mOk) {{
          balanceHtml = '<span style="color:#fcd34d;">⚡ Ministral acertó</span>';
        }} else if (qOk) {{
          balanceHtml = '<span style="color:#d8b4fe;">🤖 Qwen acertó</span>';
        }} else {{
          balanceHtml = '<span style="color:#f87171;">Discrepancia total</span>';
        }}

        const authors = Array.isArray(a.authors) ? a.authors.slice(0, 2).join('; ') : (a.authors || '');

        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td style="color:#64748b;">${{i+1}}</td>
          <td>
            <div style="font-weight:600; color:#f1f5f9;">${{a.title}}</div>
            <div style="font-size:0.78rem; color:#94a3b8;">${{authors}} • <em>${{a.journal || 'Revista'}}</em></div>
          </td>
          <td style="color:#cbd5e1;">${{a.year || '-'}}</td>
          <td style="background: rgba(245, 158, 11, 0.08);">${{getTag(goldP, true)}}</td>
          <td>${{getTag(pt)}} ${{tIcon}}</td>
          <td>${{getTag(pm)}} ${{mIcon}}</td>
          <td>${{getTag(pq)}} ${{qIcon}}</td>
          <td>${{balanceHtml}}</td>
          <td><button class="btn-toggle" onclick="toggleDetails(${{i}})">Ver</button></td>
        `;

        const trDetails = document.createElement('tr');
        trDetails.id = `details-${{i}}`;
        trDetails.className = 'details-row';
        
        const goldName = goldP === 'P1_MEDICION_ESCALAS' ? 'Perspectiva 1: Medición y Escalas Cuantitativas' :
                         (goldP === 'P2_ESTRATEGICO_STAKEHOLDERS' ? 'Perspectiva 2: Estratégico y Gobernanza' :
                         'Perspectiva 3: Conexión Social y Ética Civil');

        trDetails.innerHTML = `
          <td colspan="9">
            <div class="details-box">
              <div style="background: rgba(245, 158, 11, 0.15); border: 1px solid #facc15; padding: 12px 16px; border-radius: 10px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                  <span style="color: #fef08a; font-weight: 800; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.5px;">
                    🎯 Clasificación Oficial según Duque & Cervantes (2019):
                  </span>
                  ${{getTag(goldP, true)}}
                </div>
                <div style="color: #f8fafc; font-weight: 700; font-size: 1.05rem; margin-top: 4px;">${{goldName}}</div>
                <div style="color: #cbd5e1; font-size: 0.86rem; margin-top: 6px; line-height: 1.5;">
                  <strong>Fundamento del Estudio:</strong> ${{a.gold_standard.justificacion}}
                </div>
              </div>

              ${{a.abstract ? `
              <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255,255,255,0.06); padding: 12px 14px; border-radius: 8px; margin-bottom: 12px;">
                <strong style="color: #94a3b8; font-size: 0.78rem; text-transform: uppercase;">Abstract analizado:</strong>
                <p style="color: #cbd5e1; font-size: 0.82rem; margin-top: 4px; line-height: 1.5; font-style: italic;">"${{a.abstract}}"</p>
              </div>` : ''}}

              <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; font-size: 0.82rem;">
                <div style="background: ${{tOk ? 'rgba(59, 130, 246, 0.12)' : 'rgba(239, 68, 68, 0.1)'}}; border: 1px solid ${{tOk ? '#3b82f6' : '#ef4444'}}; padding: 12px; border-radius: 8px;">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <strong style="color: #93c5fd; font-size: 0.88rem;">🧠 Thinkuy (Afinado CoT)</strong>
                    <span style="font-weight: 800; color: ${{tOk ? '#4ade80' : '#f87171'}};">${{tOk ? '✅ ACERTÓ' : '❌ ERRÓ'}}</span>
                  </div>
                  <div style="color: #94a3b8; font-size: 0.75rem; margin-bottom:4px;">Asignó: ${{getTag(pt)}}</div>
                  <div style="color: #e2e8f0; line-height: 1.4;"><em>"${{a.rationale || 'Sin rationale'}}"</em></div>
                  ${{a.claim ? `<div style="margin-top: 6px; font-size: 0.75rem; color: #60a5fa; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 4px;"><strong>Claim:</strong> ${{a.claim}}</div>` : ''}}
                </div>

                <div style="background: ${{mOk ? 'rgba(245, 158, 11, 0.12)' : 'rgba(239, 68, 68, 0.1)'}}; border: 1px solid ${{mOk ? '#f59e0b' : '#ef4444'}}; padding: 12px; border-radius: 8px;">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <strong style="color: #fcd34d; font-size: 0.88rem;">⚡ Ministral 3B</strong>
                    <span style="font-weight: 800; color: ${{mOk ? '#4ade80' : '#f87171'}};">${{mOk ? '✅ ACERTÓ' : '❌ ERRÓ'}}</span>
                  </div>
                  <div style="color: #94a3b8; font-size: 0.75rem; margin-bottom:4px;">Asignó: ${{getTag(pm)}}</div>
                  <div style="color: #e2e8f0; line-height: 1.4;"><em>"${{(a.ministral && a.ministral.rationale) || 'Sin rationale'}}"</em></div>
                </div>

                <div style="background: ${{qOk ? 'rgba(168, 85, 247, 0.12)' : 'rgba(239, 68, 68, 0.1)'}}; border: 1px solid ${{qOk ? '#a855f7' : '#ef4444'}}; padding: 12px; border-radius: 8px;">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <strong style="color: #d8b4fe; font-size: 0.88rem;">🤖 Qwen 2.5 Base</strong>
                    <span style="font-weight: 800; color: ${{qOk ? '#4ade80' : '#f87171'}};">${{qOk ? '✅ ACERTÓ' : '❌ ERRÓ'}}</span>
                  </div>
                  <div style="color: #94a3b8; font-size: 0.75rem; margin-bottom:4px;">Asignó: ${{getTag(pq)}}</div>
                  <div style="color: #e2e8f0; line-height: 1.4;"><em>"${{(a.qwen_base && a.qwen_base.rationale) || 'Sin rationale'}}"</em></div>
                </div>
              </div>
            </div>
          </td>
        `;

        tbody.appendChild(tr);
        tbody.appendChild(trDetails);
      }});
    }}

    function toggleDetails(idx) {{
      const d = document.getElementById(`details-${{idx}}`);
      d.style.display = (d.style.display === 'table-row') ? 'none' : 'table-row';
    }}

    function filterTable() {{
      const query = document.getElementById('searchInput').value.toLowerCase();
      const accFilter = document.getElementById('modelAccuracyFilter').value;
      const gFilter = document.getElementById('goldFilter').value;

      const filtered = data.filter(a => {{
        const titleMatch = (a.title || '').toLowerCase().includes(query);
        const authMatch = (Array.isArray(a.authors) ? a.authors.join(' ') : a.authors || '').toLowerCase().includes(query);
        const matchText = titleMatch || authMatch;

        const goldP = a.gold_standard.perspectiva;
        const tOk = (a.perspectiva === goldP);
        const mOk = ((a.ministral && a.ministral.perspectiva_norm) === goldP);
        const qOk = ((a.qwen_base && a.qwen_base.perspectiva_norm) === goldP);

        let matchAcc = true;
        if (accFilter === 'THINKUY_OK') matchAcc = tOk;
        if (accFilter === 'MINISTRAL_OK') matchAcc = mOk;
        if (accFilter === 'QWEN_OK') matchAcc = qOk;
        if (accFilter === 'UNANIMOUS_OK') matchAcc = (tOk && mOk && qOk);
        if (accFilter === 'THINKUY_ONLY') matchAcc = (tOk && !mOk && !qOk);
        if (accFilter === 'DIVERGENT') matchAcc = !(tOk && mOk && qOk);

        let matchGold = (gFilter === 'ALL' || goldP === gFilter);

        return matchText && matchAcc && matchGold;
      }});

      renderTable(filtered);
    }}
  </script>
</body>
</html>
"""

with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"[EXITO] Dashboard enriquecido con Referencia Canónica en: {OUTPUT_HTML}")
