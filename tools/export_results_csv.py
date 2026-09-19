"""
Exportador Exhaustivo a CSV de las Pruebas Comparativas de Modelos Epistémicos
(Thinkuy Fine-Tuned vs. Ministral 3B vs. Qwen 2.5 Base)
frente al Estudio de Réplica de Duque & Cervantes (2019).
"""

import json
import csv
import os

JSON_PATH = "data/clasificacion_333_tripartita.json"
WOS_PATH = "data/savedrecs_duque_wos.txt"
SCOPUS_PATH = "data/scopus_duque.csv"
CSV_PATH = "data/auditorias_y_benchmarks/resultados_pruebas_modelos_333.csv"

def load_abstracts():
    """Carga los abstracts completos de WoS y Scopus indexados por título."""
    abstract_map = {}
    
    # Scopus
    if os.path.exists(SCOPUS_PATH):
        with open(SCOPUS_PATH, "r", encoding="utf-8-sig", errors="ignore") as f:
            for r in csv.DictReader(f):
                t = (r.get("Title") or "").strip().upper()
                ab = (r.get("Abstract") or "").strip()
                if t and ab:
                    abstract_map[t] = ab

    # WoS
    if os.path.exists(WOS_PATH):
        with open(WOS_PATH, "r", encoding="utf-8-sig", errors="ignore") as f:
            cur = {}
            tag = None
            for line in f:
                l = line.rstrip("\r\n")
                if not l:
                    continue
                if l == "ER":
                    t = " ".join(cur.get("TI", [])).strip().upper()
                    ab = " ".join(cur.get("AB", [])).strip()
                    if t and ab:
                        abstract_map[t] = ab
                    cur = {}
                    tag = None
                    continue
                if len(l) >= 3 and l[:2].isupper() and l[2] == " ":
                    tag = l[:2]
                    v = l[3:].strip()
                    if tag in cur:
                        cur[tag].append(v)
                    else:
                        cur[tag] = [v]
                elif tag and tag in cur:
                    cur[tag].append(l.strip())
                    
    return abstract_map

def main():
    print(f"Cargando datos desde {JSON_PATH}...")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    abstracts = load_abstracts()
    print(f"Abstracts indexados de fuentes originales: {len(abstracts)}")

    fieldnames = [
        "id",
        "title",
        "authors",
        "year",
        "journal",
        "times_cited",
        "source_db",
        "abstract",
        # Thinkuy (Fine-Tuned)
        "thinkuy_perspectiva",
        "thinkuy_rol",
        "thinkuy_acierto_estudio",
        "thinkuy_rationale_cot",
        "thinkuy_claim_central",
        "thinkuy_latencia_seg",
        # Ministral 3B (Mistral AI)
        "ministral_perspectiva",
        "ministral_rol",
        "ministral_acierto_estudio",
        "ministral_rationale",
        "ministral_claim_central",
        "ministral_latencia_seg",
        # Qwen 2.5 1.5B Base (Zero-Shot)
        "qwen_base_perspectiva",
        "qwen_base_rol",
        "qwen_base_acierto_estudio",
        "qwen_base_rationale",
        "qwen_base_claim_central",
        "qwen_base_latencia_seg",
        # Consensos
        "consenso_3_modelos",
        "coincidencia_thinkuy_ministral",
        # Referencia Canónica Duque 2019
        "referencia_canonica_perspectiva",
        "referencia_canonica_justificacion",
    ]

    rows = []
    tot_thinkuy_ok = 0
    tot_ministral_ok = 0
    tot_qwen_ok = 0
    tot_consenso = 0

    for r in records:
        t_upper = (r.get("title") or "").strip().upper()
        ab = abstracts.get(t_upper, "")

        gs = r.get("gold_standard", {})
        min_obj = r.get("ministral", {})
        qwen_obj = r.get("qwen_base", {})

        th_persp = r.get("perspectiva", "")
        min_persp = min_obj.get("perspectiva_norm", "")
        qwen_persp = qwen_obj.get("perspectiva_norm", "")

        th_ok = gs.get("thinkuy_ok", False)
        m_ok = gs.get("ministral_ok", False)
        q_ok = gs.get("qwen_ok", False)

        if th_ok: tot_thinkuy_ok += 1
        if m_ok: tot_ministral_ok += 1
        if q_ok: tot_qwen_ok += 1

        consenso_3 = (th_persp == min_persp == qwen_persp)
        if consenso_3: tot_consenso += 1

        row = {
            "id": r.get("id"),
            "title": r.get("title", ""),
            "authors": r.get("authors", "") if isinstance(r.get("authors"), str) else "; ".join(r.get("authors") or []),
            "year": r.get("year", ""),
            "journal": r.get("journal", ""),
            "times_cited": r.get("times_cited", 0),
            "source_db": r.get("source", ""),
            "abstract": ab,
            # Thinkuy
            "thinkuy_perspectiva": th_persp,
            "thinkuy_rol": r.get("rol", ""),
            "thinkuy_acierto_estudio": "ACIERTO" if th_ok else "FALLO",
            "thinkuy_rationale_cot": r.get("rationale", ""),
            "thinkuy_claim_central": r.get("claim_central", ""),
            "thinkuy_latencia_seg": r.get("latency", 0),
            # Ministral 3B
            "ministral_perspectiva": min_persp,
            "ministral_rol": min_obj.get("rol_norm", ""),
            "ministral_acierto_estudio": "ACIERTO" if m_ok else "FALLO",
            "ministral_rationale": min_obj.get("rationale", ""),
            "ministral_claim_central": min_obj.get("claim", ""),
            "ministral_latencia_seg": min_obj.get("latency", 0),
            # Qwen Base
            "qwen_base_perspectiva": qwen_persp,
            "qwen_base_rol": qwen_obj.get("rol_norm", ""),
            "qwen_base_acierto_estudio": "ACIERTO" if q_ok else "FALLO",
            "qwen_base_rationale": qwen_obj.get("rationale", ""),
            "qwen_base_claim_central": qwen_obj.get("claim", ""),
            "qwen_base_latencia_seg": qwen_obj.get("latency", 0),
            # Consensos
            "consenso_3_modelos": "SI" if consenso_3 else "NO",
            "coincidencia_thinkuy_ministral": "SI" if (th_persp == min_persp) else "NO",
            # Canónico
            "referencia_canonica_perspectiva": gs.get("perspectiva", ""),
            "referencia_canonica_justificacion": gs.get("justificacion", ""),
        }
        rows.append(row)

    # Escribir CSV con encoding utf-8-sig (con BOM para apertura directa y limpia en Microsoft Excel en Windows)
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[ÉXITO] Archivo CSV generado en: {CSV_PATH}")
    print(f"Total registros exportados: {len(rows)}")
    print(f"Consenso total entre los 3 modelos: {tot_consenso}/{len(rows)} ({tot_consenso/len(rows)*100:.1f}%)")

if __name__ == "__main__":
    main()
