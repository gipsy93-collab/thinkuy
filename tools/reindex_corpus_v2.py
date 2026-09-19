"""Reindexado del corpus de entrenamiento Thinkuy V2 (Fase 2).

Recorre TODOS los PDFs del corpus (6 macro-areas + PRISMA_JBI + SIN_PRISMA),
ejecuta el extractor corregido (secciones robustas ES/PT/EN, corte de bibliografia,
exclusion de tablas, rescate de abstract estructurado) y produce:

    data/corpus_v2/extraccion_v2.json   — registro completo por articulo (secciones)
    data/corpus_v2/cobertura_v2.json    — metricas de calidad y cobertura
    data/corpus_v2/COBERTURA_V2.md      — informe legible

Regla: cada articulo lleva diagnostico explicito. No hay fallback silencioso.

USO:
    python tools/reindex_corpus_v2.py [--solo N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.radar.text_extractor import extract_paper_to_markdown  # noqa: E402

CORPUS_DIR_DEFAULT = Path(r"C:\Users\gipsy\Documents\CORPUS ENTRENAMIENTO\PDFS")
OUT_DIR = PROJECT_ROOT / "data" / "corpus_v2"

MIN_ABSTRACT_CHARS = 500
MIN_METHODS_CHARS = 800

PT_PAT = re.compile(r"ção|ções|\bnão\b|\bembora\b|\bainda que\b|Resumo|Objetivos:|Métodos:|Resultados:|Conclusões:")
ES_PAT = re.compile(r"ción|ciones|\bñ|Resumen|Objetiv[oa]s?:|Métodos:|Resultados:|Conclusiones:|no obstante")
EN_PAT = re.compile(r"\bthe\b|\bthis study\b|Objectives?:|Methods:|Results:|Conclusions?:|Background:", re.IGNORECASE)
TABLA_LEAK = re.compile(r"^Authors,|^Sample/?$|^IG\*|^CG", re.MULTILINE)


def strip_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def detect_language(text: str) -> str:
    if not text:
        return "UNKNOWN"
    pt, es, en = len(PT_PAT.findall(text)), len(ES_PAT.findall(text)), len(EN_PAT.findall(text))
    best = max(pt, es, en)
    if best == 0:
        return "UNKNOWN"
    wins = [n for n, v in (("PT", pt), ("ES", es), ("EN", en)) if v == best]
    return wins[0] if len(wins) == 1 else "UNCERTAIN"


def diagnosticar(rec: dict) -> dict:
    """Evaluacion de calidad por articulo: banderas explicitas, sin interpretacion optimista."""
    sect = rec.get("sections", {}) or {}
    abstract = sect.get("abstract", "") or sect.get("abstract_alt", "")
    methods = sect.get("methods", "")
    flags = []

    if not abstract or len(abstract) < MIN_ABSTRACT_CHARS:
        flags.append("ABSTRACT_CORTO_O_AUSENTE")
    if not methods or len(methods) < MIN_METHODS_CHARS:
        flags.append("METHODS_CORTO_O_AUSENTE")
    if methods and TABLA_LEAK.search(methods):
        flags.append("TABLA_EN_METHODS")
    if methods and len(re.findall(r"https?://(?:dx\.)?doi\.org", methods, re.IGNORECASE)) >= 2:
        flags.append("REFS_EN_METHODS")
    if methods and re.search(r"(19|20)\d{2}[;:]\s*\d+\s*[-,]", methods) and "RESULTS" not in methods.upper():
        flags.append("POSIBLE_BIBLIO_EN_METHODS")
    if rec.get("reference_cut") == "burst":
        flags.append("CORTE_REFS_POR_RAFAGA")
    if not rec.get("references"):
        flags.append("SIN_REFERENCIAS")
    if rec.get("abstract_rescatado", 0) > 0:
        flags.append("ABSTRACT_RESCATADO")
    if len(sect) <= 2:
        flags.append("SEGMENTACION_POBRE")

    # Métodos que absorben el artículo entero: no sirven como insumo T2.
    total = sum(len(v or "") for v in sect.values())
    if methods and total and len(methods) / total > 0.60:
        flags.append("METHODS_DESPROPORCIONADO")

    # Documentos que no son artículos de revisión (memorias de congreso, erratas, editoriales).
    wc = rec.get("word_count") or 0
    if wc < 1500 or (not rec.get("references") and not abstract):
        flags.append("POSIBLE_NO_ARTICULO")

    return {
        "idioma": detect_language(abstract or rec.get("full_text", "")[:4000]),
        "flags": flags,
        "ok": "SI" if not flags else "NO",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", type=int, default=0, help="Procesar solo los primeros N PDFs (prueba)")
    ap.add_argument("--raiz", type=str, default=str(CORPUS_DIR_DEFAULT), help="Carpeta raiz con los PDFs")
    ap.add_argument("--salida", type=str, default="extraccion_v2", help="Prefijo de los archivos de salida")
    args = ap.parse_args()

    corpus_dir = Path(args.raiz)
    if not corpus_dir.exists():
        print(f"ERROR: corpus no encontrado: {corpus_dir}")
        sys.exit(1)

    pdfs = sorted(corpus_dir.rglob("*.pdf"))
    if args.solo:
        pdfs = pdfs[: args.solo]
    print(f"Raiz: {corpus_dir}")
    print(f"PDFs a procesar: {len(pdfs)}")

    registros: list[dict] = []
    t0 = time.time()
    for i, pdf in enumerate(pdfs, 1):
        rel = pdf.relative_to(corpus_dir)
        area = rel.parts[0] if len(rel.parts) > 1 else corpus_dir.name
        tipo = rel.parts[1] if len(rel.parts) > 2 else ""
        try:
            rec = extract_paper_to_markdown(pdf)
        except Exception as e:  # nunca abortar el barrido completo por un PDF
            rec = None
            err = str(e)
        if rec is None:
            registros.append({
                "doi_filename": pdf.stem, "area": area, "tipo": tipo,
                "pdf_path": str(pdf), "error": locals().get("err", "extraccion devolvio None"),
            })
            print(f"[{i:03d}/{len(pdfs)}] ERROR {rel}")
            continue

        diag = diagnosticar(rec)
        try:
            sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        except Exception:
            sha = ""
        registros.append({
            "doi_filename": pdf.stem,
            "sha256": sha,
            "area": area,
            "tipo": tipo,
            "ruta_relativa": str(rel),
            "pdf_path": str(pdf),
            "page_count": rec.get("page_count"),
            "word_count": rec.get("word_count"),
            "idioma": diag["idioma"],
            "flags": diag["flags"],
            "ok": diag["ok"],
            "headings_detected": rec.get("headings_detected"),
            "reference_cut": rec.get("reference_cut"),
            "table_lines_excluded": rec.get("table_lines_excluded"),
            "abstract_rescatado": rec.get("abstract_rescatado"),
            "sections_meta": rec.get("sections_meta"),
            "n_referencias": len(rec.get("references") or []),
            "tables_count": rec.get("tables_count"),
            "figures_count": rec.get("figures_count"),
            "sections": rec.get("sections"),
            "references": (rec.get("references") or [])[:200],
        })
        estado = "OK " if diag["ok"] == "SI" else "REV"
        print(f"[{i:03d}/{len(pdfs)}] {estado} {diag['idioma']:9} {rel}  "
              f"(pal={rec.get('word_count')}, refs={len(rec.get('references') or [])}, flags={','.join(diag['flags']) or '-'})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / f"{args.salida}.json", "w", encoding="utf-8") as fh:
        json.dump(registros, fh, ensure_ascii=False)

    # ── Cobertura ──
    validos = [r for r in registros if "error" not in r]
    cobertura = {
        "total_pdfs": len(registros),
        "errores": sum(1 for r in registros if "error" in r),
        "ok": sum(1 for r in validos if r["ok"] == "SI"),
        "revisar": sum(1 for r in validos if r["ok"] == "NO"),
        "por_idioma": dict(Counter(r["idioma"] for r in validos).most_common()),
        "por_area": {a: dict(Counter(x["idioma"] for x in validos if x["area"] == a).most_common())
                     for a in sorted({x["area"] for x in validos})},
        "flags": dict(Counter(f for r in validos for f in r["flags"]).most_common()),
        "con_abstract": sum(1 for r in validos if (r.get("sections_meta") or {}).get("abstract")),
        "con_methods": sum(1 for r in validos if (r.get("sections_meta") or {}).get("methods")),
        "con_referencias": sum(1 for r in validos if r["n_referencias"] > 0),
        "segundos": round(time.time() - t0, 1),
    }
    with open(OUT_DIR / f"cobertura_{args.salida}.json", "w", encoding="utf-8") as fh:
        json.dump(cobertura, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 78)
    print("COBERTURA V2 DEL CORPUS")
    print("=" * 78)
    print(f"PDFs: {cobertura['total_pdfs']} | errores: {cobertura['errores']} | OK: {cobertura['ok']} | a revisar: {cobertura['revisar']}")
    print(f"Idiomas: {cobertura['por_idioma']}")
    print(f"Con abstract: {cobertura['con_abstract']} | con methods: {cobertura['con_methods']} | con referencias: {cobertura['con_referencias']}")
    print(f"Flags: {cobertura['flags']}")
    print("\nPOR AREA (idiomas):")
    for a, d in cobertura["por_area"].items():
        print(f"  {a:28} {d}")
    print(f"\nTiempo: {cobertura['segundos']} s")
    print(f"Salida: {OUT_DIR}")
    print("=" * 78)


if __name__ == "__main__":
    main()
