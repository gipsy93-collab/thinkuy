"""Extractor Multi-Dominio del Corpus de Entrenamiento Thinkuy V3.

Recorre los 69 PDFs del corpus curado en 6 áreas disciplinares,
invoca el motor nativo text_extractor.py de Thinkuy (PyMuPDF) y
genera el dataset bruto estructurado para anotación Gold Standard.

USO:
    python tools/extract_training_corpus.py

SALIDAS:
    data/dataset_bruto_extraido.json   — Bloques atómicos por artículo y tarea
    data/cobertura_extraccion.json     — Reporte estadístico de cobertura

REGLAS INQUEBRANTABLES (Lecciones del entrenamiento fallido Qwen 1.5B V1):
    1. PROHIBIDO mono-tarea: se extraen las 3 micro-tareas por artículo.
    2. PROHIBIDO mono-dominio: se procesan las 6 áreas.
    3. PROHIBIDO inventar contenido: si algo no se extrae → "NO_EXTRAIDO".
    4. PROHIBIDO fallbacks silenciosos: cada campo lleva status explícito.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# ── Asegurar que el backend de Thinkuy está en el path ──────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.radar.text_extractor import (
    extract_paper_to_markdown,
    extract_citation_contexts,
    parse_reference_entry,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("extract_training_corpus")

# ── Configuración ───────────────────────────────────────────────────
CORPUS_DIR = Path(r"C:\Users\gipsy\Documents\CORPUS ENTRENAMIENTO\PDFS")
OUTPUT_DATASET = PROJECT_ROOT / "data" / "dataset_bruto_extraido.json"
OUTPUT_COVERAGE = PROJECT_ROOT / "data" / "cobertura_extraccion.json"

AREAS = [
    "ciencia-tecnologia",
    "ciencias-duras",
    "cts-epistemologia",
    "educacion-apropiacion",
    "medicina-social",
    "pensamiento-critico",
]

MAX_CITATION_BLOCKS_PER_PAPER = 5   # Top-5 párrafos con mayor densidad
MIN_ABSTRACT_CHARS = 60
MIN_METHODS_CHARS = 80


def _body_text_from_sections(sections: dict[str, str]) -> str:
    """Reconstruye el texto del cuerpo excluyendo preamble y references."""
    body_keys = [k for k in sections if k not in ("preamble", "references")]
    parts = [sections[k] for k in body_keys if sections[k]]
    return "\n\n".join(parts) if parts else ""


def _extract_citation_blocks(
    body_text: str,
    references: list[str],
    max_blocks: int = MAX_CITATION_BLOCKS_PER_PAPER,
) -> list[dict]:
    """Extrae los mejores bloques de citación del cuerpo usando nuestro motor nativo."""
    if not body_text:
        return []

    # Parsear todas las referencias bibliográficas del artículo
    parsed_refs = []
    for ref_str in references:
        parsed = parse_reference_entry(ref_str)
        if parsed and (parsed.get("author") or parsed.get("doi")):
            parsed_refs.append(parsed)

    # Buscar contextos de citación en el cuerpo para cada referencia
    all_contexts = []
    seen_sentences: set[str] = set()

    for ref in parsed_refs:
        author = ref.get("author")
        year = ref.get("year")
        doi = ref.get("doi")
        if not author and not doi:
            continue

        contexts = extract_citation_contexts(
            body_text,
            cited_doi=doi or "",
            cited_author=author,
            cited_year=year,
        )
        for ctx in contexts:
            # Deduplicar por oración
            sent_key = (ctx.get("sentence") or "")[:80].lower()
            if sent_key in seen_sentences:
                continue
            seen_sentences.add(sent_key)

            all_contexts.append({
                "parrafo": ctx.get("paragraph", ""),
                "oracion_clave": ctx.get("sentence", ""),
                "autor_citado": author,
                "ano_citado": year,
                "doi_citado": doi,
                "seccion": ctx.get("section", "body"),
                "sentimiento_heuristico": ctx.get("sentiment", "neutral_or_mention"),
                "tipo_match": ctx.get("context_type", "author_year"),
            })

    # Ordenar por longitud de párrafo (párrafos más sustantivos primero)
    # y luego tomar los top-N
    all_contexts.sort(key=lambda c: len(c["parrafo"]), reverse=True)
    return all_contexts[:max_blocks]


def process_single_pdf(pdf_path: Path, area: str, tipo_revision: str) -> dict:
    """Procesa un único PDF y retorna el registro del dataset."""
    doi_filename = pdf_path.stem  # e.g. "10.1007_s12053-025-10345-x"

    record = {
        "doi_filename": doi_filename,
        "area": area,
        "tipo_revision": tipo_revision,
        "pdf_path": str(pdf_path),
        "word_count": 0,
        "page_count": 0,
        "tarea_1_abstract": {"texto": "", "longitud_chars": 0, "status": "NO_EXTRAIDO", "motivo": ""},
        "tarea_2_metodologia": {"texto": "", "longitud_chars": 0, "status": "NO_EXTRAIDO", "motivo": ""},
        "tarea_3_bloques_citacion": [],
        "referencias_parseadas": 0,
        "tablas_detectadas": 0,
        "figuras_detectadas": 0,
    }

    # 1. Extraer con nuestro motor nativo
    result = extract_paper_to_markdown(pdf_path)
    if result is None:
        record["tarea_1_abstract"]["motivo"] = "PyMuPDF no pudo abrir el PDF"
        record["tarea_2_metodologia"]["motivo"] = "PyMuPDF no pudo abrir el PDF"
        return record

    sections = result.get("sections", {})
    references = result.get("references", [])
    record["word_count"] = result.get("word_count", 0)
    record["page_count"] = result.get("page_count", 0)
    record["tablas_detectadas"] = result.get("tables_count", 0)
    record["figuras_detectadas"] = result.get("figures_count", 0)
    record["referencias_parseadas"] = len(references)

    # ── Tarea 1: Abstract ─────────────────────────────────────────
    abstract = sections.get("abstract", "")
    if len(abstract) >= MIN_ABSTRACT_CHARS:
        record["tarea_1_abstract"] = {
            "texto": abstract,
            "longitud_chars": len(abstract),
            "status": "OK",
        }
    else:
        # Fallback: revisar preamble (en revistas Frontiers el abstract
        # queda en preamble antes de Introduction)
        preamble = sections.get("preamble", "")
        if len(preamble) >= MIN_ABSTRACT_CHARS:
            record["tarea_1_abstract"] = {
                "texto": preamble,
                "longitud_chars": len(preamble),
                "status": "PARCIAL",
                "motivo": "Extraído de preamble (no se detectó encabezado Abstract)",
            }
        else:
            record["tarea_1_abstract"]["motivo"] = (
                f"Sección 'abstract' tiene {len(abstract)} chars "
                f"y preamble tiene {len(preamble)} chars (ambos < {MIN_ABSTRACT_CHARS})"
            )

    # ── Tarea 2: Metodología ──────────────────────────────────────
    methods = sections.get("methods", "")
    if len(methods) >= MIN_METHODS_CHARS:
        record["tarea_2_metodologia"] = {
            "texto": methods,
            "longitud_chars": len(methods),
            "status": "OK",
        }
    else:
        record["tarea_2_metodologia"]["motivo"] = (
            f"Sección 'methods' tiene {len(methods)} chars (< {MIN_METHODS_CHARS}). "
            "Posible formato no estándar (Vancouver, secciones con títulos atípicos)."
        )

    # ── Tarea 3: Bloques de Citación ──────────────────────────────
    body_text = _body_text_from_sections(sections)
    blocks = _extract_citation_blocks(body_text, references)
    record["tarea_3_bloques_citacion"] = blocks

    return record


def main():
    """Punto de entrada principal."""
    t0 = time.time()
    log.info("=" * 70)
    log.info("EXTRACTOR MULTI-DOMINIO THINKUY V3")
    log.info("Motor: text_extractor.py (PyMuPDF nativo)")
    log.info("Corpus: %s", CORPUS_DIR)
    log.info("=" * 70)

    if not CORPUS_DIR.exists():
        log.error("Directorio del corpus no encontrado: %s", CORPUS_DIR)
        sys.exit(1)

    # ── Recopilar PDFs organizados por área y tipo ────────────────
    pdf_entries: list[tuple[Path, str, str]] = []
    for area in AREAS:
        area_dir = CORPUS_DIR / area
        if not area_dir.exists():
            log.warning("Área no encontrada: %s", area)
            continue
        for tipo in ["scoping", "sistematica"]:
            tipo_dir = area_dir / tipo
            if not tipo_dir.exists():
                continue
            for pdf_file in sorted(tipo_dir.glob("*.pdf")):
                pdf_entries.append((pdf_file, area, tipo))

    log.info("Total PDFs a procesar: %d", len(pdf_entries))
    if not pdf_entries:
        log.error("No se encontraron PDFs en el corpus.")
        sys.exit(1)

    # ── Procesar cada PDF ─────────────────────────────────────────
    dataset: list[dict] = []
    for i, (pdf_path, area, tipo) in enumerate(pdf_entries, 1):
        log.info("[%d/%d] Procesando [%s/%s]: %s",
                 i, len(pdf_entries), area, tipo, pdf_path.stem)
        try:
            record = process_single_pdf(pdf_path, area, tipo)
            dataset.append(record)

            # Resumen breve
            t1_st = record["tarea_1_abstract"]["status"]
            t2_st = record["tarea_2_metodologia"]["status"]
            t3_n = len(record["tarea_3_bloques_citacion"])
            log.info("         → Abstract:%s | Methods:%s | Citas:%d bloques",
                     t1_st, t2_st, t3_n)
        except Exception as e:
            log.error("   ERROR procesando %s: %s", pdf_path.name, e)
            dataset.append({
                "doi_filename": pdf_path.stem,
                "area": area,
                "tipo_revision": tipo,
                "pdf_path": str(pdf_path),
                "error": str(e),
            })

    # ── Guardar dataset bruto ─────────────────────────────────────
    OUTPUT_DATASET.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DATASET, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    log.info("Dataset bruto exportado: %s (%d artículos)", OUTPUT_DATASET, len(dataset))

    # ── Generar reporte de cobertura ──────────────────────────────
    coverage = _generate_coverage_report(dataset)
    with open(OUTPUT_COVERAGE, "w", encoding="utf-8") as f:
        json.dump(coverage, f, ensure_ascii=False, indent=2)
    log.info("Reporte de cobertura: %s", OUTPUT_COVERAGE)

    elapsed = time.time() - t0
    log.info("=" * 70)
    log.info("COMPLETADO en %.1f segundos", elapsed)
    log.info("=" * 70)

    # ── Imprimir resumen ──────────────────────────────────────────
    _print_summary(coverage)


def _generate_coverage_report(dataset: list[dict]) -> dict:
    """Genera estadísticas de cobertura por área y tarea."""
    total = len(dataset)
    by_area: dict[str, dict] = defaultdict(lambda: {
        "total": 0,
        "tarea_1_ok": 0, "tarea_1_parcial": 0, "tarea_1_fallo": 0,
        "tarea_2_ok": 0, "tarea_2_fallo": 0,
        "tarea_3_con_bloques": 0, "tarea_3_total_bloques": 0,
    })

    global_stats = {
        "total_articulos": total,
        "tarea_1_ok": 0, "tarea_1_parcial": 0, "tarea_1_fallo": 0,
        "tarea_2_ok": 0, "tarea_2_fallo": 0,
        "tarea_3_con_bloques": 0, "tarea_3_total_bloques": 0,
        "articulos_con_error": 0,
    }

    fallos_detalle: list[dict] = []

    for rec in dataset:
        if "error" in rec:
            global_stats["articulos_con_error"] += 1
            continue

        area = rec.get("area", "desconocida")
        a = by_area[area]
        a["total"] += 1

        # Tarea 1
        t1 = rec.get("tarea_1_abstract", {}).get("status", "NO_EXTRAIDO")
        if t1 == "OK":
            a["tarea_1_ok"] += 1
            global_stats["tarea_1_ok"] += 1
        elif t1 == "PARCIAL":
            a["tarea_1_parcial"] += 1
            global_stats["tarea_1_parcial"] += 1
        else:
            a["tarea_1_fallo"] += 1
            global_stats["tarea_1_fallo"] += 1
            fallos_detalle.append({
                "doi": rec["doi_filename"], "area": area,
                "tarea": "Tarea 1 (Abstract)",
                "motivo": rec.get("tarea_1_abstract", {}).get("motivo", "?"),
            })

        # Tarea 2
        t2 = rec.get("tarea_2_metodologia", {}).get("status", "NO_EXTRAIDO")
        if t2 == "OK":
            a["tarea_2_ok"] += 1
            global_stats["tarea_2_ok"] += 1
        else:
            a["tarea_2_fallo"] += 1
            global_stats["tarea_2_fallo"] += 1
            fallos_detalle.append({
                "doi": rec["doi_filename"], "area": area,
                "tarea": "Tarea 2 (Methods)",
                "motivo": rec.get("tarea_2_metodologia", {}).get("motivo", "?"),
            })

        # Tarea 3
        t3 = len(rec.get("tarea_3_bloques_citacion", []))
        if t3 > 0:
            a["tarea_3_con_bloques"] += 1
            global_stats["tarea_3_con_bloques"] += 1
        a["tarea_3_total_bloques"] += t3
        global_stats["tarea_3_total_bloques"] += t3

    return {
        "global": global_stats,
        "por_area": dict(by_area),
        "fallos_detalle": fallos_detalle,
    }


def _print_summary(coverage: dict):
    """Imprime resumen legible en consola."""
    g = coverage["global"]
    total = g["total_articulos"]

    print("\n" + "=" * 70)
    print("RESUMEN DE COBERTURA DEL CORPUS")
    print("=" * 70)
    print(f"Total artículos procesados: {total}")
    print(f"  Errores fatales: {g['articulos_con_error']}")
    print()
    print(f"TAREA 1 (Abstract -> Clasificacion Epistemologica):")
    print(f"  OK:         {g['tarea_1_ok']}/{total}")
    print(f"  PARCIAL:    {g['tarea_1_parcial']}/{total}")
    print(f"  FALLO:      {g['tarea_1_fallo']}/{total}")
    print()
    print(f"TAREA 2 (Methods -> Extraccion JBI PCC):")
    print(f"  OK:         {g['tarea_2_ok']}/{total}")
    print(f"  FALLO:      {g['tarea_2_fallo']}/{total}")
    print()
    print(f"TAREA 3 (Citas -> Postura Retorica):")
    print(f"  Artículos con bloques: {g['tarea_3_con_bloques']}/{total}")
    print(f"  Total bloques extraídos: {g['tarea_3_total_bloques']}")
    print()

    print("POR ÁREA:")
    for area, stats in coverage["por_area"].items():
        print(f"  [{area}] Total:{stats['total']} | "
              f"T1:{stats['tarea_1_ok']}ok/{stats['tarea_1_parcial']}parc/{stats['tarea_1_fallo']}fail | "
              f"T2:{stats['tarea_2_ok']}ok/{stats['tarea_2_fallo']}fail | "
              f"T3:{stats['tarea_3_con_bloques']}arts/{stats['tarea_3_total_bloques']}bloqs")

    fallos = coverage.get("fallos_detalle", [])
    if fallos:
        print(f"\nDETALLE DE FALLOS ({len(fallos)} secciones no extraídas):")
        for f in fallos[:15]:
            print(f"  • [{f['area']}] {f['doi']}: {f['tarea']} — {f['motivo']}")
        if len(fallos) > 15:
            print(f"  ... y {len(fallos) - 15} fallos más (ver cobertura_extraccion.json)")

    print("=" * 70)


if __name__ == "__main__":
    main()
