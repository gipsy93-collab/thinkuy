import os
import sys
import json
import time
import httpx

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath("."))

from backend.radar import librarian

def fetch_openalex_works():
    url = "https://api.openalex.org/works"
    from_date = "2001-01-01"
    to_date = "2019-06-20"
    headers = {"User-Agent": "ThinkuyReplication/1.0 (mailto:tinkuy.lab@thinkuy.org)"}

    # Consultar tanto en inglés como en español para tener la muestra bilingüe real
    params_en = {
        "filter": f"title.search:University Social Responsibility,from_publication_date:{from_date},to_publication_date:{to_date}",
        "per_page": 50,
        "sort": "cited_by_count:desc"
    }
    params_es = {
        "filter": f"title.search:Responsabilidad Social Universitaria,from_publication_date:{from_date},to_publication_date:{to_date}",
        "per_page": 50,
        "sort": "cited_by_count:desc"
    }

    all_works = []
    seen_ids = set()

    with httpx.Client(timeout=25.0) as client:
        print("[1/3] Descargando corpus en inglés desde OpenAlex (2001-2019)...")
        r_en = client.get(url, params=params_en, headers=headers).json()
        for w in r_en.get("results", []):
            if w["id"] not in seen_ids:
                seen_ids.add(w["id"])
                all_works.append(w)

        print("[2/3] Descargando corpus en español desde OpenAlex (2001-2019)...")
        r_es = client.get(url, params=params_es, headers=headers).json()
        for w in r_es.get("results", []):
            if w["id"] not in seen_ids:
                seen_ids.add(w["id"])
                all_works.append(w)

    print(f"[EXITO] {len(all_works)} obras recuperadas y consolidadas para el benchmark.")
    return all_works

def categorize_tos(works: list[dict]):
    # Ordenar por citas
    works_sorted = sorted(works, key=lambda x: x.get("cited_by_count", 0), reverse=True)
    
    # Raíz (Top citadas / Seminales)
    raiz = works_sorted[:10]
    
    # Tronco (Estructurales: entre 30 y 80 citas, o con marco teórico/revisión)
    tronco = [w for w in works_sorted[10:] if w.get("cited_by_count", 0) >= 25][:15]
    
    # Hojas (Recientes del final del periodo: 2016-2019)
    hojas = [w for w in works_sorted if 2016 <= (w.get("publication_year") or 0) <= 2019][:15]

    return raiz, tronco, hojas

def run_replication():
    print("=" * 85)
    print("THINKUY — RÉPLICA CONTROLADA DE REVISIÓN SISTEMÁTICA / SCOPING REVIEW")
    print("Artículo Base: Duque & Cervantes (2019) — Estudios Gerenciales")
    print("Tema: 'Responsabilidad Social Universitaria: una revisión sistemática (2001-2019)'")
    print("=" * 85)

    raw_works = fetch_openalex_works()
    raiz, tronco, hojas = categorize_tos(raw_works)

    print("\n" + "=" * 85)
    print("ESTRUCTURA TREE OF SCIENCE (ToS) RECUPERADA POR OPENALEX:")
    print("=" * 85)

    print("\n--- RAÍZ (Obras Hegemónicas / Seminales más Citadas) ---")
    for i, w in enumerate(raiz[:7], 1):
        auth = [a["author"]["display_name"] for a in w.get("authorships", [])[:2]]
        print(f"  {i}. ({w.get('publication_year')}) {', '.join(auth)}: \"{w.get('title')}\" [Citas: {w.get('cited_by_count')}]")

    print("\n--- TRONCO (Obras Estructurales / Intermediación) ---")
    for i, w in enumerate(tronco[:7], 1):
        auth = [a["author"]["display_name"] for a in w.get("authorships", [])[:2]]
        print(f"  {i}. ({w.get('publication_year')}) {', '.join(auth)}: \"{w.get('title')}\" [Citas: {w.get('cited_by_count')}]")

    print("\n--- HOJAS (Obras Recientes / Perspectivas 2016-2019) ---")
    for i, w in enumerate(hojas[:7], 1):
        auth = [a["author"]["display_name"] for a in w.get("authorships", [])[:2]]
        print(f"  {i}. ({w.get('publication_year')}) {', '.join(auth)}: \"{w.get('title')}\" [Citas: {w.get('cited_by_count')}]")

    # Preparar datos para Ministral 3B
    print("\n" + "=" * 85)
    print("[FASE 3] SÍNTESIS EPISTÉMICA Y PERSPECTIVAS CON MINISTRAL 3B")
    print("Evaluando si Ministral 3B identifica las 3 perspectivas del paper de Duque:")
    print("  1. Medición / Escalas de RSU")
    print("  2. Enfoque Estratégico y de Stakeholders")
    print("  3. Conexión RSU y Sociedad / Compromiso Comunitario")
    print("-" * 85)

    sample_for_llm = {
        "raiz": [{"year": w.get("publication_year"), "title": w.get("title"), "cites": w.get("cited_by_count"), "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:2]]} for w in raiz[:6]],
        "tronco": [{"year": w.get("publication_year"), "title": w.get("title"), "cites": w.get("cited_by_count"), "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:2]]} for w in tronco[:6]],
        "hojas": [{"year": w.get("publication_year"), "title": w.get("title"), "cites": w.get("cited_by_count"), "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:2]]} for w in hojas[:6]],
    }

    user_prompt = (
        "Eres el metodólogo experto de Thinkuy. Estás replicando de forma independiente la revisión sistemática sobre "
        "'Responsabilidad Social Universitaria (2001-2019)' de Duque & Cervantes (2019).\n\n"
        "Recibes la estructura extraída por teoría de grafos (Raíz, Tronco y Hojas):\n"
        + json.dumps(sample_for_llm, ensure_ascii=False, indent=2)
        + "\n\nTu tarea:\n"
        "1. Identifica y describe las PERSPECTIVAS O ESCUELAS TEMÁTICAS que emergen de la literatura.\n"
        "2. Detalla los consensos y contradicciones epistemológicas del campo.\n"
        "3. Compara críticamente si este mapa coincide con las tres perspectivas clásicas: "
        "(a) Medición y escalas, (b) Enfoque estratégico de gestión y stakeholders, (c) Conexión con la sociedad y extensión.\n"
        "Devuelve un informe académico estructurado, riguroso y formal en español."
    )

    t0 = time.time()
    try:
        report = librarian._chat(
            system="Eres un asistente experto en cienciometría, teoría de grafos y revisiones sistemáticas (PRISMA-ScR).",
            user=user_prompt,
            temperature=0.2,
            max_tokens=1500,
            timeout=120,
            model=librarian._classify_model()
        )
        elapsed = round(time.time() - t0, 2)
        print(f"\n[ÉXITO] Informe de replicación generado por Ministral 3B en {elapsed}s:\n")
        print("=" * 85)
        print(report)
        print("=" * 85)

        out_path = "data/informe_replica_duque_2019.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# Informe de Réplica Controlada — Revisión Sistemática RSU (2001-2019)\n")
            f.write("*Benchmark metodológico frente al estudio de Duque & Cervantes (2019) en Estudios Gerenciales*\n\n")
            f.write(report)
        print(f"\n[EXPORTACIÓN] Informe guardado en: {out_path}")

    except Exception as e:
        print(f"[ERROR] Error llamando a Ministral 3B: {e}")

if __name__ == "__main__":
    run_replication()
