import os
import sys
import json
import time

sys.path.insert(0, os.path.abspath("."))

from backend.radar.text_extractor import (
    extract_paper_to_markdown,
    parse_reference_entry,
    extract_citation_contexts,
    batch_classify_contexts,
)
from backend.radar import librarian

def audit_paper(pdf_path: str, max_contexts_to_classify: int = 15):
    print("=" * 80)
    print("THINKUY — AUDITORÍA EPISTÉMICA DE MANUSCRITO REAL")
    print(f"Archivo: {os.path.basename(pdf_path)}")
    print("=" * 80)

    # 1. Extracción PyMuPDF
    print("\n[PASO 1] Desglosando PDF con PyMuPDF...")
    t0 = time.time()
    extracted = extract_paper_to_markdown(pdf_path)
    if not extracted:
        print("[ERROR] No se pudo procesar el PDF.")
        return

    full_text = extracted.get("full_text", "")
    sections = extracted.get("sections", {})
    references = extracted.get("references", [])
    word_count = extracted.get("word_count", 0)
    elapsed_pdf = round(time.time() - t0, 2)

    print(f"[EXITO] PDF procesado en {elapsed_pdf}s:")
    print(f" - Palabras totales: {word_count:,}")
    print(f" - Secciones detectadas: {list(sections.keys())}")
    print(f" - Entradas de referencias al final: {len(references)} referencias bibliográficas")

    # 2. Parsear referencias bibliográficas para identificar autores y años citados
    print("\n[PASO 2] Parseando catálogo de referencias del artículo...")
    parsed_refs = []
    for r in references:
        p = parse_reference_entry(r)
        if p and (p.get("author") or p.get("year")):
            parsed_refs.append(p)
    print(f"[EXITO] {len(parsed_refs)} referencias identificadas con Autor y Año válidos.")

    # 3. Preparar texto del cuerpo (excluyendo la bibliografía final)
    body_sections = [v for k, v in sections.items() if k != "references" and v]
    body_text = "\n\n".join(body_sections) if body_sections else full_text

    # 4. Rastrear contextos de citación en el cuerpo del artículo
    print("\n[PASO 3] Rastreando menciones y citas en el cuerpo del manuscrito...")
    all_contexts = []
    seen_keys = set()

    for ref in parsed_refs:
        author = ref.get("author")
        year = ref.get("year")
        doi = ref.get("doi")
        if not author:
            continue
        
        ctxs = extract_citation_contexts(body_text, cited_doi=doi, cited_author=author, cited_year=year)
        for c in ctxs:
            c["cited_author"] = author
            c["cited_year"] = year
            c["cited_ref_raw"] = ref.get("raw", "")
            key = c.get("sentence", "")[:60].lower()
            if key not in seen_keys:
                seen_keys.add(key)
                all_contexts.append(c)

    print(f"[EXITO] Se localizaron {len(all_contexts)} citas activas en el cuerpo del manuscrito.")

    if not all_contexts:
        print("[AVISO] No se hallaron contextos de citación coincidentes en el cuerpo.")
        return

    # Limitar para la prueba cualitativa
    target_contexts = all_contexts[:max_contexts_to_classify]
    print(f"\n[PASO 4] Auditando las primeras {len(target_contexts)} citas con Ministral 3B en LM Studio...")
    t1 = time.time()
    classified = batch_classify_contexts(target_contexts)
    elapsed_ai = round(time.time() - t1, 2)
    print(f"[EXITO] Auditoría completada en {elapsed_ai}s (~{round(elapsed_ai/len(target_contexts), 2)}s por cita).\n")

    # Mapeo de posturas
    STANCE_NAMES = {
        "supporting_or_agreement": "POSIBLE CONSENSO / APOYO (+)",
        "contrasting_or_refuting": "POSIBLE DISENSO / CONTRASTE (-)",
        "methodological_adoption": "ADOPCIÓN METODOLÓGICA (M)",
        "neutral_or_mention": "MENCIÓN CONTEXTUAL / ESTADO DEL ARTE (~)",
    }

    print("=" * 80)
    print(f"{'#':<2} | {'AUTOR CITADO':<22} | {'POSTURA':<32} | {'SECCIÓN':<10}")
    print("=" * 80)

    for i, (ctx, res) in enumerate(zip(target_contexts, classified), 1):
        author = ctx.get("cited_author", "Desconocido")
        year = ctx.get("cited_year", "")
        author_str = f"{author} ({year})" if year else author
        fn = res.get("function") or "neutral_or_mention"
        label = STANCE_NAMES.get(fn, fn.upper())
        section = ctx.get("section", "cuerpo")
        sentence = ctx.get("sentence", "").replace("\n", " ").strip()
        claim = res.get("claim") or ""
        confidence = res.get("confidence", "low")

        print(f"{i:<2} | {author_str[:22]:<22} | {label:<32} | {section[:10]:<10}")
        print(f"   | Oración extraída del PDF : \"{sentence[:110]}...\"")
        print(f"   | Claim literal exacto (IA): \"{claim[:110]}\"")
        print(f"   | Confianza: {confidence}")
        print("-" * 80)

if __name__ == "__main__":
    pdf_file = r"C:\Users\gipsy\Documents\CIENCIA TRANSMEDIA\RPP\ARTÍCULOS\2026\Núm. 41 (2026)_ enero-junio\3557_Prince_Galban_Meza.pdf"
    audit_paper(pdf_file, max_contexts_to_classify=10)
