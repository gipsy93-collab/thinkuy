import os
import sys
import json
import time
import re
from collections import Counter

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath("."))

from backend.radar import librarian

def parse_wos_plaintext(filepath: str):
    records = []
    current_rec = {}
    current_tag = None

    with open(filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line_clean = line.rstrip("\r\n")
            if not line_clean:
                continue
            if line_clean == "ER":
                if current_rec:
                    records.append(current_rec)
                    current_rec = {}
                current_tag = None
                continue
            
            # Tags de dos letras en columna 0
            if len(line_clean) >= 3 and line_clean[:2].isupper() and line_clean[2] == " ":
                current_tag = line_clean[:2]
                val = line_clean[3:].strip()
                if current_tag in current_rec:
                    current_rec[current_tag].append(val)
                else:
                    current_rec[current_tag] = [val]
            elif current_tag and line_clean.startswith("   "):
                current_rec[current_tag].append(line_clean.strip())

    return records

def run_native_wos_analysis():
    wos_file = r"C:\Users\gipsy\Downloads\savedrecs.txt"
    print("=" * 85)
    print("THINKUY — PROCESAMIENTO DETERMINISTA DE LA RED NATIVA DE WEB OF SCIENCE")
    print(f"Archivo: {wos_file}")
    print("=" * 85)

    records = parse_wos_plaintext(wos_file)
    print(f"\n[1/3] {len(records)} artículos parseados desde el archivo ISI/WoS.")

    # 1. Extracción determinista de la Red de Referencias Citadas (In-Degree / Raíz)
    all_citations = []
    author_citations = Counter()
    work_citations = Counter()

    for r in records:
        cr_list = r.get("CR", [])
        for cr in cr_list:
            cr_clean = cr.strip()
            if len(cr_clean) > 8:
                all_citations.append(cr_clean)
                
                # Formato típico WoS: VALLAEYS F, 2009, RESPONSABILIDAD SOCI...
                parts = [p.strip() for p in cr_clean.split(",")]
                author = parts[0].title() if parts else "Desconocido"
                
                # Buscar año
                year_match = re.search(r"\b(19\d\d|20\d\d)\b", cr_clean)
                year = year_match.group(1) if year_match else ""

                author_citations[author] += 1
                if year:
                    work_citations[f"{author} ({year})"] += 1
                else:
                    work_citations[author] += 1

    print(f"[2/3] Red de Citaciones extraída:")
    print(f" - Total de enlaces de citas en el corpus: {len(all_citations):,}")
    print(f" - Autores citados únicos: {len(author_citations):,}")

    top_authors = author_citations.most_common(20)
    top_works = work_citations.most_common(20)

    print("\n" + "=" * 85)
    print("RESULTADO MATEMÁTICO 1: AUTORES MÁS CITADOS EN LA RED DE WoS (RAÍZ DEL ToS)")
    print("=" * 85)
    for i, (auth, count) in enumerate(top_authors, 1):
        print(f"  {i:<2}. {auth:<32} | In-Degree (Citas en la red): {count}")

    print("\n" + "=" * 85)
    print("RESULTADO MATEMÁTICO 2: OBRAS/AÑOS MÁS CITADAS (DOCUMENTOS HEGEMÓNICOS)")
    print("=" * 85)
    for i, (work, count) in enumerate(top_works, 1):
        print(f"  {i:<2}. {work:<32} | In-Degree (Citas en la red): {count}")

    # Comparación directa con la Tabla 5 de Duque & Cervantes (2019)
    print("\n" + "=" * 85)
    print("CONTRASTE DIRECTO CON LA TABLA 5 ('DOCUMENTOS HEGEMÓNICOS') DE DUQUE (2019)")
    print("Autores hegemónicos reportados en el estudio de referencia:")
    print(" - Archie B. Carroll (1979, 1991, 1999)")
    print(" - R. Edward Freeman (1984)")
    print(" - Howard R. Bowen (1953/1960)")
    print(" - François Vallaeys (2009, 2014, 2018)")
    print(" - Ricardo Gaete Quezada (2011, 2012)")
    print("-" * 85)

    gold_check = ["Carroll", "Freeman", "Bowen", "Vallaeys", "Gaete"]
    for g in gold_check:
        found = False
        for auth, count in author_citations.items():
            if g.lower() in auth.lower():
                print(f"  [CONCORDANCIA CONFIRMADA] '{g}' -> {auth} con {count} citas en tu archivo de WoS.")
                found = True
                break
        if not found:
            print(f"  [NO ENCONTRADO] '{g}'")

    # 2. Inferencia Ciega de Perspectivas con Ministral 3B
    print("\n" + "=" * 85)
    print("[3/3] INFERENCIA CIEGA CON MINISTRAL 3B SOBRE EL CORPUS DE WoS")
    print("(Prompt 100% neutro sin condicionamiento)")
    print("-" * 85)

    corpus_sample = []
    for r in records[:30]:
        t = " ".join(r.get("TI", [])).strip()
        ab = " ".join(r.get("AB", [])).strip()
        au = "; ".join(r.get("AU", [])[:2])
        py = r.get("PY", [""])[0]
        if t:
            corpus_sample.append({"title": t, "author": au, "year": py, "abstract": ab[:250]})

    blind_system = (
        "Eres un analista metodológico independiente. Analiza este corpus de artículos de Web of Science sobre "
        "Responsabilidad Social Universitaria. Clasifica objetivamente las perspectivas o líneas temáticas que dividen "
        "la literatura, identifica sus focos y señala los desacuerdos o tensiones conceptuales existentes."
    )
    user_prompt = "Corpus de Web of Science:\n" + json.dumps(corpus_sample, ensure_ascii=False, indent=2)

    t0 = time.time()
    try:
        report = librarian._chat(
            system=blind_system,
            user=user_prompt,
            temperature=0.1,
            max_tokens=1500,
            timeout=120,
            model=librarian._classify_model()
        )
        elapsed = round(time.time() - t0, 2)
        print(f"[ÉXITO] Ministral 3B respondió en {elapsed}s:\n")
        print(report)

        # Guardar informe
        with open("data/informe_wos_nativo.md", "w", encoding="utf-8") as f:
            f.write("# Informe de Procesamiento de Red Nativa de Web of Science\n")
            f.write(f"*Calculado matemáticamente y analizado a ciegas con Ministral 3B en {elapsed}s*\n\n")
            f.write("## 1. Top Autores Citados en la Red de Referencias (In-Degree Puro):\n\n")
            for i, (a, c) in enumerate(top_authors, 1):
                f.write(f"{i}. **{a}**: {c} citas\n")
            f.write("\n## 2. Top Obras Citadas:\n\n")
            for i, (w, c) in enumerate(top_works, 1):
                f.write(f"{i}. **{w}**: {c} citas\n")
            f.write("\n---\n\n## 3. Síntesis Temática Ciega de Ministral 3B:\n\n")
            f.write(report)
        print(f"\n[EXPORTACIÓN] Resultados guardados en: data/informe_wos_nativo.md")

    except Exception as e:
        print(f"[ERROR] Error llamando a Ministral 3B: {e}")

if __name__ == "__main__":
    run_native_wos_analysis()
