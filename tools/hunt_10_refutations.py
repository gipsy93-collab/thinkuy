import os
import sys
import json
import time
import re
import glob

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath("."))

from backend.radar.text_extractor import (
    extract_paper_to_markdown,
    parse_reference_entry,
    extract_citation_contexts,
)
from backend.radar import librarian

CONTRAST_REGEX = re.compile(
    r"\b(sin embargo|no obstante|por el contrario|en contraste|a diferencia de|lejos de|empero|"
    r"discrepa|discrepancia|refuta|objeta|critica|cuestiona|inadecuad[oa]s?|insuficiente[s]?|"
    r"sesgo[s]?|limitaci[oó]n|limitaciones|frente a la postura|a pesar de|pese a|aunque|pero|difiere|"
    r"diverge|controversia|debate|inconsistencia|carencia[s]?|falta[s]?|dificultad[es]?|desventaja[s]?|"
    r"tensi[oó]n|en desacuerdo|desaf[íi]a|contrast|however|nevertheless|despite|refute|differ|problem|tension)\b",
    re.IGNORECASE
)

VOLUMES_DIR = r"C:\Users\gipsy\Documents\CIENCIA TRANSMEDIA\RPP\ARTÍCULOS"
TARGET_VOLUMES = [
    os.path.join(VOLUMES_DIR, r"2026\Núm. 41 (2026)_ enero-junio"),
    os.path.join(VOLUMES_DIR, r"2025\Núm. 40 (2025)_ julio-diciembre"),
    os.path.join(VOLUMES_DIR, r"2025\Núm. 39 (2025)_ enero-junio"),
    os.path.join(VOLUMES_DIR, r"2024\Núm. 38 (2024)_ julio-diciembre"),
    os.path.join(VOLUMES_DIR, r"2024\Núm. 37 (2024)_ enero - junio"),
]

def score_contrast(sentence: str) -> int:
    matches = CONTRAST_REGEX.findall(sentence)
    return len(matches)

def hunt_refutations(target_count: int = 10):
    print("=" * 90)
    print("THINKUY — CACERÍA EPISTÉMICA: 10 REFUTACIONES EN 5 VOLÚMENES DE RPP")
    print("Motor de Inferencia: Ministral 3B (LM Studio @ :1234)")
    print("=" * 90)

    # 1. Recolectar todos los PDFs
    all_pdfs = []
    for v in TARGET_VOLUMES:
        if os.path.isdir(v):
            pdfs = glob.glob(os.path.join(v, "*.pdf"))
            valid_pdfs = [p for p in pdfs if not any(x in os.path.basename(p).lower() for x in ["portada", "editorial", "indice", "sumario", "creditos"])]
            all_pdfs.extend(valid_pdfs)

    print(f"\n[INVENTARIO] {len(all_pdfs)} artículos de investigación identificados en los 5 volúmenes.")

    refutations_found = []
    total_candidates_evaluated = 0
    total_articles_scanned = 0
    t_start = time.time()

    for pdf_path in all_pdfs:
        if len(refutations_found) >= target_count:
            break

        pdf_name = os.path.basename(pdf_path)
        vol_name = os.path.basename(os.path.dirname(pdf_path))
        print(f"\n[{total_articles_scanned + 1}/{len(all_pdfs)}] Procesando: [{vol_name}] {pdf_name[:45]}...")

        try:
            extracted = extract_paper_to_markdown(pdf_path)
        except Exception as e:
            print(f"   [AVISO] Error leyendo PDF: {e}")
            continue

        total_articles_scanned += 1
        if not extracted:
            continue

        full_text = extracted.get("full_text", "")
        sections = extracted.get("sections", {})
        references = extracted.get("references", [])

        # Parsear referencias
        parsed_refs = []
        for r in references:
            p = parse_reference_entry(r)
            if p and (p.get("author") or p.get("year")):
                parsed_refs.append(p)

        # Preparar cuerpo
        body_sections = [v for k, v in sections.items() if k != "references" and v]
        body_text = "\n\n".join(body_sections) if body_sections else full_text

        # Extraer contextos
        seen_keys = set()
        paper_contexts = []
        for ref in parsed_refs:
            author = ref.get("author")
            year = ref.get("year")
            doi = ref.get("doi")
            if not author or len(author) < 3:
                continue

            ctxs = extract_citation_contexts(body_text, cited_doi=doi, cited_author=author, cited_year=year)
            for c in ctxs:
                c["cited_author"] = author
                c["cited_year"] = year
                c["cited_ref_raw"] = ref.get("raw", "")
                c["source_article"] = pdf_name
                c["source_volume"] = vol_name
                c["contrast_score"] = score_contrast(c.get("sentence", ""))
                key = c.get("sentence", "")[:60].lower()
                if key not in seen_keys:
                    seen_keys.add(key)
                    paper_contexts.append(c)

        # Filtrar y ordenar contextos por sospecha de contraste
        contrast_candidates = [c for c in paper_contexts if c["contrast_score"] > 0]
        contrast_candidates.sort(key=lambda x: x["contrast_score"], reverse=True)

        if not contrast_candidates:
            print(f"   (0 contextos con tensión discursiva entre {len(paper_contexts)} citas)")
            continue

        print(f"   -> {len(contrast_candidates)} citas candidatas con tensión discursiva (de {len(paper_contexts)} citas totales).")

        # Evaluar candidatos con Ministral 3B
        for cand in contrast_candidates:
            if len(refutations_found) >= target_count:
                break

            total_candidates_evaluated += 1
            author_tag = f"{cand['cited_author']} ({cand.get('cited_year','')})"
            snippet = cand.get("sentence", "").replace("\n", " ").strip()
            
            # Asegurar que párrafo esté presente para _verbatim
            if not cand.get("paragraph"):
                cand["paragraph"] = cand.get("sentence", "")

            # Llamada al clasificador oficial de Thinkuy (Ministral 3B)
            res_list = librarian.classify_citation_functions([cand])
            if not res_list:
                continue
            
            res = res_list[0]
            func = res.get("function")
            claim = res.get("claim", "")
            confidence = res.get("confidence", "")

            # ¿Es refutación/disenso confirmado con verbatim?
            if func == "contrasting_or_refuting":
                is_verb = librarian._verbatim(claim, snippet)
                match_entry = {
                    "number": len(refutations_found) + 1,
                    "source_volume": cand["source_volume"],
                    "source_article": cand["source_article"],
                    "cited_author": cand["cited_author"],
                    "cited_year": cand.get("cited_year", ""),
                    "sentence": snippet,
                    "claim": claim,
                    "verbatim": is_verb,
                    "confidence": confidence,
                    "section": cand.get("section", "cuerpo"),
                }
                refutations_found.append(match_entry)

                print("\n" + "!" * 80)
                print(f"[REFUTACION CONFIRMADA #{len(refutations_found)}/{target_count}]")
                print(f"   Artículo : [{cand['source_volume']}] {cand['source_article']}")
                print(f"   Autor Cit: {author_tag}")
                print(f"   Oración  : \"{snippet}\"")
                print(f"   Claim    : \"{claim}\" (Verbatim: {is_verb})")
                print("!" * 80 + "\n")
            else:
                print(f"   [Candidato #{total_candidates_evaluated}] {author_tag[:20]} -> {func} (No es disenso)")

    elapsed_total = round(time.time() - t_start, 2)
    print("\n" + "=" * 90)
    print("CACERÍA COMPLETADA")
    print(f"Artículos procesados: {total_articles_scanned}/{len(all_pdfs)}")
    print(f"Citas candidatas auditadas por IA: {total_candidates_evaluated}")
    print(f"Refutaciones/Disensos confirmados: {len(refutations_found)}/{target_count}")
    print(f"Tiempo total: {elapsed_total}s (~{round(elapsed_total/max(1, total_candidates_evaluated), 2)}s por cita evaluada)")
    print("=" * 90)

    # Guardar reporte en JSON
    out_json = "data/refutations_rpp_5_volumes.json"
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(refutations_found, f, ensure_ascii=False, indent=2)
    print(f"\n[EXPORTACIÓN] Resultados guardados en: {out_json}")

    return refutations_found

if __name__ == "__main__":
    hunt_refutations(target_count=10)
