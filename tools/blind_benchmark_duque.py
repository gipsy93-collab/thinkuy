import os
import sys
import json
import time
import re
import pandas as pd
from collections import Counter

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath("."))

from backend.radar import librarian

def run_blind_benchmark():
    scopus_file = r"C:\Users\gipsy\Downloads\scopus_export_Sep 15-2026_84f7891b-d810-48b3-8908-2e6a769a21e3.csv"
    wos_file = r"C:\Users\gipsy\Downloads\savedrecs.xls"

    print("=" * 85)
    print("THINKUY — PROTOCOLO CIEGO DE RÉPLICA (DOUBLE-BLIND EXPERIMENT)")
    print("Corpus suministrado por el usuario: Archivos exportados de Scopus y WoS")
    print("REGLA: Cero contaminación de prompt. El algoritmo y la IA operan sin pistas.")
    print("=" * 85)

    # 1. Cargar datos
    df_scopus = pd.read_csv(scopus_file, encoding="utf-8-sig")
    df_wos = pd.read_excel(wos_file)

    print(f"\n[CARGA] Registros leídos:")
    print(f" - Scopus: {len(df_scopus)} artículos")
    print(f" - WoS   : {len(df_wos)} artículos")

    # 2. Análisis Determinista de Grafos: Red de Citas (In-degree sobre Cited References)
    # Extraer todas las referencias citadas del corpus de WoS
    raw_refs = df_wos["Cited References"].dropna().tolist()
    print(f"\n[GRAFOS 1/3] Extrayendo red de referencias citadas de WoS...")

    all_citations = []
    author_citations = Counter()
    work_citations = Counter()

    for entry in raw_refs:
        # Cada referencia suele estar separada por punto y coma o salto de línea
        items = re.split(r";\s*|\n", str(entry))
        for it in items:
            it_clean = it.strip()
            if len(it_clean) > 10:
                all_citations.append(it_clean)
                # Extraer primer autor y año de la referencia (ej: VALLAEYS F, 2009, ...)
                m = re.match(r"^([A-ZÁÉÍÓÚÑa-záéíóúñ\s\-\']+?),\s*([12]\d{3})", it_clean)
                if m:
                    auth = m.group(1).title()
                    yr = m.group(2)
                    author_citations[auth] += 1
                    work_citations[f"{auth} ({yr})"] += 1
                else:
                    # fallback solo autor
                    parts = it_clean.split(",")
                    if parts:
                        author_citations[parts[0].strip().title()] += 1

    print(f"[EXITO] Total de referencias citadas extraídas: {len(all_citations):,}")
    print(f"Total de autores citados únicos: {len(author_citations):,}")

    # Top autores más citados (Raíz matemática / In-degree más alto)
    top_root_authors = author_citations.most_common(15)
    top_root_works = work_citations.most_common(15)

    print("\n" + "=" * 85)
    print("RESULTADO DETERMINISTA 1: AUTORES MÁS CITADOS (RAÍZ / INDEGREE MÁS ALTO)")
    print("(Calculado de forma puramente matemática a partir de las referencias de los artículos)")
    print("=" * 85)
    for i, (auth, count) in enumerate(top_root_authors, 1):
        print(f"  {i:<2}. {auth:<30} | Citaciones recibidas (In-degree): {count}")

    print("\n" + "=" * 85)
    print("RESULTADO DETERMINISTA 2: OBRAS ESPECÍFICAS MÁS CITADAS EN LA RED")
    print("=" * 85)
    for i, (work, count) in enumerate(top_root_works, 1):
        print(f"  {i:<2}. {work:<30} | Citaciones recibidas (In-degree): {count}")

    # 3. Consolidación de Artículos del Corpus para Inferencia Ciega de Perspectivas
    corpus_articles = []
    seen_titles = set()

    for _, row in df_wos.iterrows():
        t = str(row.get("Article Title", "")).strip()
        ab = str(row.get("Abstract", "")).strip()
        yr = row.get("Publication Year")
        au = str(row.get("Authors", "")).strip()
        if t and t.lower() not in seen_titles and t.lower() != "nan":
            seen_titles.add(t.lower())
            corpus_articles.append({"title": t, "author": au, "year": yr, "abstract": ab if ab != "nan" else ""})

    for _, row in df_scopus.iterrows():
        t = str(row.get("Title", "")).strip()
        ab = str(row.get("Abstract", "")).strip()
        yr = row.get("Year")
        au = str(row.get("Authors", "")).strip()
        if t and t.lower() not in seen_titles and t.lower() != "nan":
            seen_titles.add(t.lower())
            corpus_articles.append({"title": t, "author": au, "year": yr, "abstract": ab if ab != "nan" else ""})

    print(f"\n[CORPUS] Total de artículos únicos consolidados: {len(corpus_articles)}")

    # 4. Inferencia Ciega con Ministral 3B
    # Tomar una muestra representativa de 30 artículos con título y abstract para síntesis
    articles_sample = [
        {"title": a["title"], "author": a["author"][:40], "year": a["year"], "abstract_snippet": a["abstract"][:250]}
        for a in corpus_articles[:35] if a["title"]
    ]

    # PROMPT ESTRICTAMENTE CIEGO Y NEUTRO
    # PROHIBIDO mencionar a Duque, Vallaeys, ToS, o los nombres de las perspectivas esperadas
    BLIND_SYSTEM = (
        "Eres un analista metodológico y epistemológico independiente. "
        "Recibes un conjunto de artículos científicos empíricos y teóricos sobre un campo de investigación. "
        "Tu labor es examinar objetivamente este corpus y realizar una categorización temática:\n"
        "1. Identifica cuáles son las PERSPECTIVAS O LÍNEAS TEMÁTICAS principales que dividen la producción del corpus.\n"
        "2. Describe brevemente el objetivo y foco de cada perspectiva a partir de los títulos y resúmenes provistos.\n"
        "3. Señala si observas desacuerdos, tensiones o diferencias de enfoque entre los trabajos.\n"
        "REGLA: Basa tus conclusiones exclusivamente en el corpus provisto. Sé analítico, riguroso y conciso."
    )

    blind_user_prompt = (
        "Por favor analiza este corpus de artículos científicos y extrae las perspectivas temáticas emergentes:\n\n"
        + json.dumps(articles_sample, ensure_ascii=False, indent=2)
    )

    print("\n" + "=" * 85)
    print("EJECUTANDO INFERENCIA CIEGA CON MINISTRAL 3B EN LM STUDIO...")
    print("(Prompt 100% neutro: sin pistas sobre autores ni categorías predefinidas)")
    print("=" * 85)

    t0 = time.time()
    try:
        report = librarian._chat(
            system=BLIND_SYSTEM,
            user=blind_user_prompt,
            temperature=0.1,
            max_tokens=1500,
            timeout=120,
            model=librarian._classify_model()
        )
        elapsed = round(time.time() - t0, 2)
        print(f"\n[ÉXITO] Ministral 3B completó el análisis ciego en {elapsed}s:\n")
        print("-" * 85)
        print(report)
        print("-" * 85)

        # Guardar informe ciego
        os.makedirs("data", exist_ok=True)
        with open("data/informe_ciego_scopus_wos.md", "w", encoding="utf-8") as f:
            f.write("# Informe Ciego de Análisis Bibliométrico y Epistemológico\n")
            f.write(f"*Generado de forma independiente y sin condicionamiento por Ministral 3B en {elapsed}s*\n\n")
            f.write("## 1. Autores y Obras más Citadas en las Referencias (Cálculo Matemático Puro)\n\n")
            f.write("### Top Autores Citados (In-Degree):\n")
            for i, (a, c) in enumerate(top_root_authors, 1):
                f.write(f"{i}. **{a}**: {c} citas\n")
            f.write("\n### Top Obras Citadas:\n")
            for i, (w, c) in enumerate(top_root_works, 1):
                f.write(f"{i}. **{w}**: {c} citas\n")
            f.write("\n---\n\n## 2. Categorización Temática Emitida por Ministral 3B (Blind Prompt)\n\n")
            f.write(report)

        print(f"\n[EXPORTACIÓN] Informe guardado en: data/informe_ciego_scopus_wos.md")

    except Exception as e:
        print(f"[ERROR] Error llamando a Ministral 3B: {e}")

if __name__ == "__main__":
    run_blind_benchmark()
