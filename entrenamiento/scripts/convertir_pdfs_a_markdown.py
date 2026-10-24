"""
=============================================================================
Thinkuy — Conversor Masivo de PDFs a Markdown Estructurado
=============================================================================
Procesa todos los PDFs descargados en 'data/descargas_revisiones_es_pt/'
utilizando el extractor de alta fidelidad basado en PyMuPDF (fitz)
preservando la segmentación canónica de secciones (Abstract, Métodos,
Resultados, Discusión, Conclusiones, Referencias) y excluyendo ruido de tablas.

Genera:
  1. data/markdown_revisiones_es_pt/<id>.md con frontmatter YAML y secciones.
  2. data/markdown_revisiones_es_pt/manifest_conversion.json con telemetría.
=============================================================================
"""

import os
import sys
import io
import json
import glob
import re
from pathlib import Path

# Forzar codificación UTF-8 en consola para Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.radar.text_extractor import extract_paper_to_markdown

PDF_DIR = ROOT_DIR / "data" / "descargas_revisiones_es_pt"
OUT_DIR = ROOT_DIR / "data" / "markdown_revisiones_es_pt"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def clean_title_from_preamble(preamble: str, filename: str) -> str:
    """Intenta extraer un título limpio de las primeras líneas del preámbulo."""
    if not preamble:
        return filename.replace(".pdf", "")
    lines = [l.strip() for l in preamble.split("\n") if l.strip()]
    for ln in lines[:5]:
        if len(ln) > 15 and len(ln) < 250 and not re.match(r"^(doi|issn|vol|http|cc\s+by|art[ií]culo)", ln, re.IGNORECASE):
            return ln
    return filename.replace(".pdf", "")

def main():
    pdf_files = sorted(glob.glob(str(PDF_DIR / "*.pdf")))
    total_pdfs = len(pdf_files)
    print("=" * 80)
    print(f"Iniciando conversión de {total_pdfs} PDFs a Markdown estructurado")
    print(f"Directorio origen:  {PDF_DIR}")
    print(f"Directorio destino: {OUT_DIR}")
    print("=" * 80 + "\n", flush=True)

    manifest = []
    exitosos = 0
    fallidos = 0
    total_palabras = 0

    for idx, pdf_path_str in enumerate(pdf_files, 1):
        pdf_path = Path(pdf_path_str)
        file_size_kb = round(pdf_path.stat().st_size / 1024, 1)
        base_name = pdf_path.stem
        md_out_path = OUT_DIR / f"{base_name}.md"

        try:
            res = extract_paper_to_markdown(pdf_path)
            if not res or not res.get("full_text") or res.get("word_count", 0) < 50:
                print(f"[{idx:03d}/{total_pdfs:03d}] [WARN] FALLO / VACÍO: {pdf_path.name} ({file_size_kb} KB)", flush=True)
                fallidos += 1
                continue

            full_text = res["full_text"]
            sections = res.get("sections", {})
            word_count = res.get("word_count", 0)
            page_count = res.get("page_count", 0)
            tables_count = res.get("tables_count", 0)
            figures_count = res.get("figures_count", 0)
            ref_count = len(res.get("references", []))
            
            # Título y metadatos
            preamble = sections.get("preamble", "")
            title_guess = clean_title_from_preamble(preamble, pdf_path.name)
            
            # Crear frontmatter YAML
            frontmatter = [
                "---",
                f"title: \"{title_guess.replace('\"', '')}\"",
                f"source_pdf: \"{pdf_path.name}\"",
                f"pages: {page_count}",
                f"words: {word_count}",
                f"tables_detected: {tables_count}",
                f"figures_detected: {figures_count}",
                f"references_count: {ref_count}",
                f"sections_found: {list(sections.keys())}",
                "---",
                "",
            ]

            # Construir Markdown estructurado
            md_content = "\n".join(frontmatter) + full_text

            # Guardar archivo .md
            with open(md_out_path, "w", encoding="utf-8") as f_out:
                f_out.write(md_content)

            item_info = {
                "file_name": md_out_path.name,
                "source_pdf": pdf_path.name,
                "title": title_guess,
                "word_count": word_count,
                "page_count": page_count,
                "tables_count": tables_count,
                "figures_count": figures_count,
                "references_count": ref_count,
                "sections": list(sections.keys()),
                "has_abstract": "abstract" in sections or "abstract_alt" in sections,
                "has_methods": "methods" in sections,
                "has_results": "results" in sections,
                "has_discussion": "discussion" in sections,
                "has_references": "references" in sections or ref_count > 0,
            }
            manifest.append(item_info)

            exitosos += 1
            total_palabras += word_count
            
            sec_flags = "".join([
                "A" if item_info["has_abstract"] else ".",
                "M" if item_info["has_methods"] else ".",
                "R" if item_info["has_results"] else ".",
                "D" if item_info["has_discussion"] else ".",
                "B" if item_info["has_references"] else ".",
            ])

            print(f"[{idx:03d}/{total_pdfs:03d}] [OK] [{sec_flags}] {page_count:2d} págs | {word_count:5d} pal | {pdf_path.name[:45]}", flush=True)

        except Exception as e:
            print(f"[{idx:03d}/{total_pdfs:03d}] [ERROR] en {pdf_path.name}: {e}", flush=True)
            fallidos += 1

    # Guardar manifiesto JSON
    manifest_path = OUT_DIR / "manifest_conversion.json"
    with open(manifest_path, "w", encoding="utf-8") as f_manifest:
        json.dump({
            "total_pdfs": total_pdfs,
            "convertidos_exitosamente": exitosos,
            "fallidos": fallidos,
            "total_palabras_corpus": total_palabras,
            "promedio_palabras_articulo": round(total_palabras / exitosos, 1) if exitosos else 0,
            "articulos": manifest
        }, f_manifest, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80, flush=True)
    print(f"RESUMEN FINAL DE CONVERSIÓN A MARKDOWN:", flush=True)
    print(f"  • Total PDFs procesados:      {total_pdfs}", flush=True)
    print(f"  • Convertidos con éxito:      {exitosos} ({round(exitosos/total_pdfs*100, 1)}%)", flush=True)
    print(f"  • Fallidos / ilegibles:       {fallidos}", flush=True)
    print(f"  • Total palabras en corpus:   {total_palabras:,}", flush=True)
    print(f"  • Promedio palabras/artículo: {round(total_palabras / exitosos, 1) if exitosos else 0:,}", flush=True)
    print(f"  • Carpeta de salida:          {OUT_DIR}", flush=True)
    print(f"  • Manifiesto telemetría:      {manifest_path}", flush=True)
    print("=" * 80, flush=True)

if __name__ == "__main__":
    main()
