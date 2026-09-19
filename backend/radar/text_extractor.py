"""Extractor de texto completo y contextos de citación cualitativa (Thinkuy).

Convierte PDFs científicos en Markdown estructurado preservando secciones,
y analiza las menciones en el texto para responder al "¿CÓMO se citan?"
(acuerdo, refutación, adopción metodológica o contraste teórico).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pymupdf as fitz
    HAS_FITZ = True
except ImportError:
    try:
        import fitz
        HAS_FITZ = True
    except ImportError:
        HAS_FITZ = False

from . import db

log = logging.getLogger("radar.text_extractor")


# ==============================================================================
# 1. CONVERSIÓN PDF / TEXTO → MARKDOWN ESTRUCTURADO
# ==============================================================================

SECTION_PATTERNS: list[tuple[str, str]] = [
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(resumen|resumo|abstract)\b", "abstract"),
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(introducci[oó]n|introdu[çc][aã]o|introduction|marco te[oó]rico|antecedentes|justificaci[oó]n)\b", "introduction"),
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(m[eé]todos|metodolog[ií]a|materia(?:l|les)\s+y\s+m[eé]todos|materiais\s+e\s+m[eé]todos|dise[nñ]o(?:\s+metodol[oó]gico)?|methods?|materials?\s+and\s+methods?|methodology|methodological\s+approach)\b", "methods"),
    # Sinónimos metodológicos frecuentes en revisiones (Frontiers, SciELO, enfermería).
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(systematic\s+approach|research\s+approach|review\s+methodology|methodological\s+framework|research\s+design|data\s+and\s+methods|methods\s+and\s+materials|protocol|procedures?|delineamento|abordagem\s+metodol[oó]gica|enfoque\s+metodol[oó]gico|estrat[eé]gia\s+metodol[oó]gica|marco\s+metodol[oó]gico|material\s+e\s+m[eé]todos)\b", "methods"),
    # Subsecciones que pertenecen a MÉTODOS y deben anclarse ahí, no abrir sección propia.
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(study\s+design|search\s+strategy|data\s+sources?|information\s+sources?|eligibility\s+criteria|inclusion\s+criteria|exclusion\s+criteria|study\s+selection|selection\s+of\s+(?:studies|articles)|data\s+extraction|data\s+charting|quality\s+assessment|risk\s+of\s+bias|statistical\s+analysis|delineamento|estrat[eé]gia\s+de\s+busca|crit[eé]rios\s+de\s+elegibilidade|crit[eé]rios\s+de\s+inclus[aã]o|sele[çc][aã]o\s+dos\s+estudos|extra[çc][aã]o\s+dos\s+dados|an[aá]lise\s+dos\s+dados|crit[eé]rios\s+de\s+inclusi[oó]n|selecci[oó]n\s+de\s+(?:estudios|art[ií]culos)|extracci[oó]n\s+de\s+datos|an[aá]lisis\s+de\s+datos|evaluaci[oó]n\s+de\s+la\s+calidad)\b", "methods"),
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(resultados|results?|findings|hallazgos|s[ií]ntesis\s+de\s+hallazgos|principais\s+achados|main\s+findings)\b", "results"),
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(discusi[oó]n|discuss[aã]o|discussion|limitaciones|limita[çc][oõ]es|limitations|implicaciones|implica[çc][oõ]es|interpretation)\b", "discussion"),
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(conclusiones?|conclus[aã]o|conclus[oõ]es|consideraciones\s+finales|considera[çc][oõ]es\s+finais|implicaciones|comentarios\s+finales|final\s+remarks)\b", "conclusion"),
    (r"^(?:\d+(?:\.\d+)*\.?\s*)?(referencias?(?:\s+bibliogr[aá]ficas?)?|refer[eê]ncias?(?:\s+bibliogr[aá]ficas?)?|bibliograf[ií]a|bibliography|references?|works?\s+cited|literature\s+cited|fuentes\s+consultadas)\b", "references"),
]


def _is_numbered_heading(text: str) -> bool:
    return bool(re.match(r"^\d+(?:\.\d+){0,3}\.?\s+[A-ZÁÉÍÓÚÑÇÃa-záéíóúñçã]", text.strip()))


def _classify_heading(text: str) -> Optional[str]:
    """Devuelve la sección canónica del encabezado, o None si es subencabezado desconocido."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    for pattern, name in SECTION_PATTERNS:
        if re.match(pattern, t, re.IGNORECASE):
            return name
    return None


def _norm(t: str) -> str:
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


EXACT_HEADINGS = {
    "abstract", "resumen", "resumo", "summary",
    "introduction", "introduccion", "introducao",
    "methods", "method", "methodology", "metodologia", "metodos",
    "materials and methods", "material and methods", "materials and method",
    "materiais e metodos", "material e metodos", "materiales y metodos", "material y metodos",
    "results", "resultados", "findings", "hallazgos",
    "discussion", "discusion", "discussao",
    "conclusion", "conclusions", "conclusiones", "conclusao", "conclusoes",
    "references", "referencias", "references bibliographic", "referencias bibliograficas",
    "referencias bibliograficas", "bibliografia", "bibliography",
}


def _exact_canonical_heading(text: str) -> bool:
    """Etiqueta canónica exacta, independiente del estilo (revistas con encabezado sin negrita)."""
    t = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", (text or "").strip())
    t = t.strip(" .:\u2013-")
    return _norm(t) in EXACT_HEADINGS


def _is_run_in_label(text: str) -> bool:
    """Etiqueta corrida de abstract: 'Objetivo: ... texto ...' (no es un encabezado)."""
    t = (text or "").strip()
    m = re.match(r"^([A-Za-zÁÉÍÓÚÑÇáéíóúñç][\wáéíóúñç\s]{2,25}):\s+(\S.*)$", t)
    if not m:
        return False
    return len(m.group(2).split()) >= 3


def _line_is_heading(text: str, size: float, body_size: float, bold: bool) -> bool:
    """Un encabezado real destaca por TAMAÑO; la negrita sola no basta (abstracts en negrita)."""
    t = (text or "").strip()
    if not t or len(t) > 90:
        return False
    if _is_run_in_label(t):
        return False
    if _exact_canonical_heading(t):
        return True
    if t.endswith(".") and not _is_numbered_heading(t):
        return False
    if re.match(r"^[\d\s\.,;:()\-%]+$", t):  # líneas puramente numéricas (tablas)
        return False
    if len(re.findall(r"\d", t)) > len(t) * 0.35:
        return False
    size_ok = body_size > 0 and size >= body_size * 1.06
    if size_ok:
        return True
    # Vía tolerante para PDFs con encabezados del mismo tamaño: negrita + nombre canónico corto.
    if bold and len(t) <= 45 and _classify_heading(t) is not None:
        return True
    # Encabezado numerado ("2.1 Diseño del estudio") en negrita.
    if _is_numbered_heading(t) and bold:
        return True
    return False


def _short_line_flags(lines: list[dict]) -> list[bool]:
    """Marca ráfagas de líneas cortas sin puntuación final: tablas no detectadas por PyMuPDF."""
    shorty: list[bool] = []
    for ln in lines:
        t = (ln.get("text") or "").strip()
        corto = len(t) < 45 and len(t.split()) <= 8 and not re.search(r"[.!?]\s*$", t)
        if _classify_heading(t):
            corto = False
        shorty.append(corto)
    flags = [False] * len(lines)
    i = 0
    while i < len(lines):
        if shorty[i]:
            j = i
            while j < len(lines) and shorty[j]:
                j += 1
            if (j - i) >= 12:
                for k in range(i, j):
                    flags[k] = True
            i = j
        else:
            i += 1
    return flags


def _page_lines(page) -> list[dict]:
    """Líneas de la página con tamaño y negrita (necesario para detectar encabezados)."""
    out: list[dict] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return out
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            sizes = [float(s.get("size", 0) or 0) for s in spans]
            out.append({
                "text": text,
                "size": max(sizes) if sizes else 0.0,
                "bold": any(int(s.get("flags", 0) or 0) & 16 for s in spans),
                "bbox": line.get("bbox"),
            })
    return out


def _table_rects(page) -> list:
    """Rectángulos de tablas de la página, para excluir su texto del cuerpo corrido."""
    rects = []
    if not hasattr(page, "find_tables"):
        return rects
    try:
        for t in page.find_tables():
            bb = getattr(t, "bbox", None)
            if bb:
                rects.append(fitz.Rect(bb[0] - 2, bb[1] - 2, bb[2] + 2, bb[3] + 2))
    except Exception:
        pass
    return rects


def _inside_any(rect, rects) -> bool:
    if not rect or not rects:
        return False
    try:
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        return any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in rects)
    except Exception:
        return False


def _looks_like_reference_line(text: str) -> bool:
    """Heurística de entrada bibliográfica (para detectar el inicio de la lista de referencias)."""
    t = (text or "").strip()
    if len(t) < 25 or len(t) > 400:
        return False
    if re.search(r"https?://(?:dx\.)?doi\.org", re.sub(r"\s+", "", t), re.IGNORECASE):
        return True
    if re.search(r"\b(19|20)\d{2}[;:]\s*\d+", t):
        return True
    if re.search(r"\(\s*(19|20)\d{2}[a-z]?\s*\)", t) and re.search(r"\d+\s*[\(:,]\s*\d*", t):
        return True
    if re.match(r"^\[\d+\]|^\d{1,3}\.\s+[A-ZÁÉÍÓÚÑÇ]", t):
        return True
    return False


def _body_size(page_lines: list[dict]) -> float:
    """Tamaño de fuente dominante de la página, ponderado por caracteres."""
    weights: dict[float, int] = {}
    for ln in page_lines:
        sz = round(float(ln.get("size", 0) or 0) * 2) / 2
        if sz <= 0:
            continue
        weights[sz] = weights.get(sz, 0) + len(ln.get("text", ""))
    if not weights:
        return 0.0
    return max(weights.items(), key=lambda kv: kv[1])[0]


RUN_IN_START = re.compile(
    r"\b(objetiv[oa]s?|objectives?|background|antecedentes|introducci[oó]n|introdu[çc][aã]o|introduction|aim|aims|purpose)\s*:",
    re.IGNORECASE,
)
RUN_IN_ANY = re.compile(
    r"\b(objetiv[oa]s?|objectives?|m[eé]todos?|m[eé]todo|methods?|method|resultados?|results?|"
    r"conclusi[oó]n|conclusiones?|conclus[aã]o|conclus[oõ]es|conclusions?|background|antecedentes|"
    r"aim|purpose|dise[nñ]o|design)\s*:",
    re.IGNORECASE,
)


def _rescue_structured_abstract(ordered: list[dict], limit: int = 80) -> int:
    """Rescata un abstract estructurado SIN encabezado: 'Objetivos: … Métodos: … Resultados: …'.

    Acepta etiquetas corridas al inicio o en medio de la línea (los PDF a dos columnas
    parten las etiquetas). Devuelve cuántos ítems fueron reasignados a la sección abstract.
    """
    candidatos = [
        k for k, it in enumerate(ordered[:limit])
        if it["kind"] in ("line", "subheading")
        and len(it.get("text") or "") < 300
        and RUN_IN_ANY.search(it.get("text") or "")
    ]
    if len(candidatos) < 3:
        return 0
    if not RUN_IN_START.search(ordered[candidatos[0]].get("text") or ""):
        return 0
    start, end = candidatos[0], candidatos[-1]
    reasignados = 0
    for k in range(start, end + 1):
        if ordered[k]["kind"] in ("line", "subheading"):
            ordered[k]["kind"] = "abstract_line"
            reasignados += 1
    return reasignados


def _detect_reference_burst(ordered: list[dict]) -> Optional[int]:
    """Fallo de seguridad: detecta el inicio de la bibliografía por ráfaga de entradas.

    Solo se aplica cuando NO se detectó encabezado de referencias, y jamás antes del
    35 % del documento (la bibliografía va al final).
    """
    n = len(ordered)
    if n < 40:
        return None
    min_idx = int(n * 0.35)
    for i in range(min_idx, n - 8):
        window = [it["text"] for it in ordered[i:i + 8] if it["kind"] in ("line", "ref", "subheading")]
        if len(window) < 6:
            continue
        hits = sum(1 for t in window[:8] if _looks_like_reference_line(t))
        if hits >= 6:
            return i
    return None


def extract_paper_to_markdown(pdf_path: str | Path) -> Optional[Dict[str, Any]]:
    """Convierte un archivo PDF científico en Markdown estructurado por secciones."""
    if not HAS_FITZ:
        log.warning("PyMuPDF (fitz) no está disponible en este entorno.")
        return None

    path = Path(pdf_path)
    if not path.exists():
        log.error(f"Archivo PDF no encontrado: {path}")
        return None

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        log.error(f"Error abriendo PDF {path}: {e}")
        return None

    ordered: list[dict] = []
    current_section = "preamble"
    in_references = False
    seen_abstract = False
    page_count = len(doc)

    tables: list[dict] = []
    figures: list[dict] = []
    table_counter = 0
    figure_counter = 0

    for page_idx, page in enumerate(doc, start=1):
        blocks = page.get_text("blocks")
        page_lines = _page_lines(page)
        table_rects = _table_rects(page)

        # 1. Extracción de tablas de la página
        if hasattr(page, "find_tables"):
            try:
                page_tables = page.find_tables()
                for t in page_tables:
                    table_counter += 1
                    md_table = ""
                    if hasattr(t, "to_markdown"):
                        try:
                            md_table = t.to_markdown()
                        except Exception:
                            md_table = ""
                    rows = []
                    if hasattr(t, "extract"):
                        try:
                            rows = t.extract()
                        except Exception:
                            rows = []

                    # Caption tentativo buscando bloques de texto que contengan Tabla / Cuadro / Table
                    cap = None
                    for b in blocks:
                        b_text = (b[4] or "").strip()
                        if re.match(r"^(?:tabla|table|cuadro)\s*\d+[:.]?", b_text, re.IGNORECASE):
                            cap = b_text.split("\n")[0][:140]
                            break

                    tables.append({
                        "table_num": table_counter,
                        "page": page_idx,
                        "caption": cap or f"Tabla {table_counter} (pág. {page_idx})",
                        "markdown": md_table,
                        "rows": rows,
                        "bbox": list(t.bbox) if hasattr(t, "bbox") else None,
                    })
            except Exception as e:
                log.debug(f"Error procesando tablas de pág {page_idx}: {e}")

        # 2. Extracción de imágenes / figuras de la página
        if hasattr(page, "get_images"):
            try:
                images = page.get_images(full=True)
                for img in images:
                    xref = img[0]
                    w = img[2]
                    h = img[3]
                    # Descartar iconos o viñetas ornamentales menores a 70x70
                    if w < 70 or h < 70:
                        continue
                    figure_counter += 1

                    # Caption tentativo buscando bloques de texto con Figura / Figure / Gráfico
                    fig_cap = None
                    for b in blocks:
                        b_text = (b[4] or "").strip()
                        if re.match(r"^(?:figura|figure|gr[aá]fico|grafico|chart|imagen)\s*\d+[:.]?", b_text, re.IGNORECASE):
                            fig_cap = b_text.split("\n")[0][:140]
                            break

                    figures.append({
                        "fig_num": figure_counter,
                        "page": page_idx,
                        "caption": fig_cap or f"Figura {figure_counter} (pág. {page_idx})",
                        "width": w,
                        "height": h,
                        "xref": xref,
                    })
            except Exception as e:
                log.debug(f"Error procesando figuras de pág {page_idx}: {e}")

        body_size = _body_size(page_lines)
        short_flags = _short_line_flags(page_lines)

        for ln_idx, ln in enumerate(page_lines):
            text = ln["text"].strip()
            if not text:
                continue

            # Texto dentro de una tabla (por bbox o por ráfaga de líneas cortas):
            # se conserva aparte y no contamina las secciones.
            if _inside_any(ln.get("bbox"), table_rects) or short_flags[ln_idx]:
                ordered.append({"kind": "table", "text": text})
                continue

            # Blindaje: una vez iniciada la bibliografía, ninguna línea la reabre.
            if in_references:
                ordered.append({"kind": "ref", "text": text})
                continue

            if _line_is_heading(text, ln.get("size", 0), body_size, ln.get("bold", False)):
                canon = _classify_heading(text)
                if canon:
                    if canon == "abstract":
                        if seen_abstract:
                            canon = "abstract_alt"
                        else:
                            seen_abstract = True
                    current_section = canon
                    if canon == "references":
                        in_references = True
                    ordered.append({"kind": "heading", "text": text, "section": canon})
                    continue
                # Subencabezado desconocido: se registra sin abrir sección nueva.
                ordered.append({"kind": "subheading", "text": text})
                continue

            ordered.append({"kind": "line", "text": text})

    # ── Rescate de abstract estructurado sin encabezado ──
    hay_abstract_encabezado = any(i["kind"] == "heading" and i.get("section") == "abstract" for i in ordered)
    abstract_rescatado = 0 if hay_abstract_encabezado else _rescue_structured_abstract(ordered)

    # ── Corte de la bibliografía: por encabezado detectado, o por ráfaga (fallback) ──
    ref_start = None
    ref_cut_reason = "none"
    for i, item in enumerate(ordered):
        if item["kind"] == "heading" and item.get("section") == "references":
            ref_start = i
            ref_cut_reason = "heading"
            break
    if ref_start is None:
        ref_start = _detect_reference_burst(ordered)
        if ref_start is not None:
            ref_cut_reason = "burst"

    cuerpo = ordered if ref_start is None else ordered[:ref_start]
    cola_refs = [] if ref_start is None else ordered[ref_start:]

    # ── Ensamblado acumulativo de secciones (nunca sobrescribe) ──
    buffers: dict[str, list[str]] = {}
    cur = "preamble"
    for item in cuerpo:
        if item["kind"] == "heading":
            cur = item["section"]
            continue
        if item["kind"] == "table":
            continue
        if item["kind"] == "abstract_line":
            buffers.setdefault("abstract", []).append(item["text"])
            continue
        buffers.setdefault(cur, []).append(item["text"])
    sections: dict[str, str] = {k: "\n".join(v).strip() for k, v in buffers.items() if "".join(v).strip()}

    # ── Referencias ──
    references = [
        i["text"].strip() for i in cola_refs
        if i["kind"] in ("ref", "line") and len(i["text"].strip()) > 25
    ]
    if not references and "references" in sections:
        references = [l.strip() for l in sections["references"].split("\n") if len(l.strip()) > 15]

    # ── Markdown ordenado (el contenido de tablas no se vuelca al cuerpo) ──
    full_text_lines: list[str] = []
    for item in ordered:
        if item["kind"] == "heading":
            full_text_lines.append(f"\n## {item['text']}\n")
        elif item["kind"] == "table":
            continue
        else:
            full_text_lines.append(item["text"])

    doc.close()
    full_markdown = "\n\n".join(full_text_lines)

    return {
        "full_text": full_markdown,
        "sections": sections,
        "references": references,
        "tables": tables,
        "figures": figures,
        "tables_count": len(tables),
        "figures_count": len(figures),
        "word_count": len(full_markdown.split()),
        "page_count": page_count,
        "pdf_path": str(path),
        # Telemetría de segmentación (auditoría de calidad; no altera consumidores existentes)
        "body_size_ultimo": round(float(_body_size(page_lines) or 0), 2) if page_lines else 0.0,
        "headings_detected": sum(1 for i in ordered if i["kind"] == "heading"),
        "reference_cut": ref_cut_reason,
        "abstract_rescatado": abstract_rescatado,
        "table_lines_excluded": sum(1 for i in ordered if i["kind"] == "table"),
        "sections_meta": {k: len(v) for k, v in sections.items()},
    }


def extract_xml_to_markdown(xml_text: str | None) -> Optional[Dict[str, Any]]:
    """Convierte un XML JATS (Europe PMC, vía limpia y legal) a Markdown por secciones.

    Misma segmentación por encabezados que la ruta PDF, sin PyMuPDF.
    """
    import html as _html
    if not xml_text or not xml_text.strip():
        return None
    block_tags = r"(?:sec|title|p|section|body|front|back|ref-list|ref|article-title|abstract)"
    # Tags de bloque -> salto de línea (se preserva); el resto -> espacio.
    # (normalize.unescape no sirve aquí: colapsa todos los saltos.)
    spaced = re.sub(rf"</?{block_tags}\b[^>]*>", "\n", xml_text, flags=re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", spaced)
    plain = _html.unescape(no_tags)
    lines = [l.strip() for l in plain.split("\n") if l.strip()]
    if not lines:
        return None

    sections: dict[str, str] = {}
    current_section = "preamble"
    current_lines: list[str] = []
    full_lines: list[str] = []

    for line in lines:
        matched = False
        if len(line) < 80:
            for pattern, sec_name in SECTION_PATTERNS:
                if re.match(pattern, line.lower(), re.IGNORECASE):
                    if current_lines:
                        sections[current_section] = "\n".join(current_lines).strip()
                    current_section = sec_name
                    current_lines = []
                    full_lines.append(f"\n## {line}\n")
                    matched = True
                    break
        if not matched:
            current_lines.append(line)
            full_lines.append(line)
    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    references = [l for l in sections.get("references", "").split("\n") if len(l.strip()) > 15]
    full_markdown = "\n\n".join(full_lines)
    if len(full_markdown.split()) < 50:
        return None
    return {
        "full_text": full_markdown,
        "sections": sections,
        "references": references,
        "word_count": len(full_markdown.split()),
        "page_count": None,
    }


# ==============================================================================
# 2. EXTRACCIÓN Y CLASIFICACIÓN DE CONTEXTOS DE CITACIÓN
# ==============================================================================

def extract_citation_contexts(
    full_text: str,
    cited_doi: str,
    cited_author: Optional[str] = None,
    cited_year: Optional[int | str] = None,
) -> List[Dict[str, Any]]:
    """Localiza los párrafos y oraciones donde se cita a una obra específica."""
    if not full_text:
        return []

    contexts: list[dict[str, Any]] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", full_text) if len(p.strip()) > 30]

    # 1. Búsqueda explícita por DOI
    doi_clean = (cited_doi or "").lower().replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip()
    if doi_clean:
        for para in paragraphs:
            if _looks_like_reference_entry(para):
                continue
            if doi_clean in para.lower():
                sent = _extract_relevant_sentence(para, doi_clean)
                contexts.append({
                    "paragraph": para,
                    "sentence": sent,
                    "sentiment": _classify_sentiment(para),
                    "section": _detect_section(para, full_text),
                    "context_type": "doi",
                })

    # 2. Búsqueda por Autor + Año (ej. "García et al. (2022)", "Torres (2020)")
    if cited_author:
        surname = cited_author.split(",")[0].strip()
        if " " in surname:
            surname = surname.split()[-1]
        author_clean = re.escape(surname)
        year_str = str(cited_year) if cited_year else r"\d{4}"
        patterns = [
            rf"\b{author_clean}\s*(?:et\s+al\.?)?\s*\(({year_str}[a-z]?)\)",
            rf"\b{author_clean}\s*(?:et\s+al\.?)?,\s*({year_str}[a-z]?)",
            rf"\({author_clean}\s*(?:et\s+al\.?)?,\s*({year_str}[a-z]?)\)",
            rf"\b{author_clean}\s+(?:y|e|and|&)\s+[A-ZÁÉÍÓÚÑa-záéíóúñ\-]+\s*\(({year_str}[a-z]?)\)",
            rf"\({author_clean}\s+(?:y|e|and|&)\s+[A-ZÁÉÍÓÚÑa-záéíóúñ\-]+[,\s]+({year_str}[a-z]?)\)",
            rf"\({author_clean}[^)]*?\b({year_str}[a-z]?)\)",
        ]
        for para in paragraphs:
            if _looks_like_reference_entry(para):
                continue
            for pat in patterns:
                match = re.search(pat, para, re.IGNORECASE)
                if match:
                    sent = _extract_relevant_sentence(para, surname)
                    contexts.append({
                        "paragraph": para,
                        "sentence": sent,
                        "sentiment": _classify_sentiment(para),
                        "section": _detect_section(para, full_text),
                        "context_type": "author_year",
                        "matched_year": match.group(1) if match.groups() else None,
                    })
                    break  # Un solo contexto por párrafo para este autor

    # Deduplicar por similitud de oración
    seen_sentences: set[str] = set()
    unique_contexts: list[dict[str, Any]] = []
    for ctx in contexts:
        key = ctx["sentence"][:80].lower()
        if key not in seen_sentences:
            seen_sentences.add(key)
            unique_contexts.append(ctx)

    return unique_contexts


def _looks_like_reference_entry(paragraph: str) -> bool:
    """Detecta entradas de la lista de referencias (no son actos de citación).

    La prosa académica cita como Autor (Año) y casi nunca incrusta URLs doi.org;
    las entradas bibliográficas sí: cortas, con URL DOI y forma año-volumen-páginas.
    """
    p = paragraph or ""
    if len(p) >= 500:
        return False
    # Sin espacios: atrapa URLs partidas por salto de línea (https://doi.\norg/...)
    nospace = re.sub(r"\s+", "", p)
    has_doi_url = bool(re.search(r"https?://(?:dx\.)?doi\.org", nospace, re.IGNORECASE))
    has_ref_shape = bool(re.search(
        r"\(\s*19\d{2}[a-z]?\s*\)|\(\s*20\d{2}[a-z]?\s*\)", p)) and bool(re.search(
        r"\d+\s*\(\s*\d+\s*\)\s*,\s*\d+\s*[-–]\s*\d+", p))
    return has_doi_url or has_ref_shape


def _extract_relevant_sentence(paragraph: str, search_term: str) -> str:
    """Extrae la oración precisa que contiene el término de citación."""
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    for s in sentences:
        if search_term.lower() in s.lower():
            return s.strip()
    return paragraph[:220] + "..." if len(paragraph) > 220 else paragraph


def _classify_sentiment(text: str) -> str:
    """Clasificación retórica del propósito de la cita."""
    t = text.lower()

    # Adopción metodológica
    method_markers = [
        "utilizando el método", "siguiendo a", "adaptando la escala", "según el protocolo",
        "con el instrumento de", "using the method", "following", "adapted from", "scale by"
    ]
    if any(m in t for m in method_markers):
        return "methodological_adoption"

    # Contraste o refutación
    refutation_markers = [
        "contradice", "refuta", "en desacuerdo", "cuestiona", "crítica", "a diferencia de",
        "sin embargo", "no obstante", "contradicts", "refutes", "however", "in contrast to", "disagrees"
    ]
    if any(m in t for m in refutation_markers):
        return "contrasting_or_refuting"

    # Confirmación o respaldo
    support_markers = [
        "confirma", "demuestra", "respalda", "en concordancia", "valida", "apoya",
        "confirms", "supports", "demonstrates", "in accordance with", "validates"
    ]
    if any(m in t for m in support_markers):
        return "supporting_or_agreement"

    return "neutral_or_mention"


def _detect_section(context_window: str, full_text: str) -> str:
    """Identifica en qué sección del manuscrito ocurre la cita."""
    pos = full_text.find(context_window[:40])
    if pos == -1:
        return "body"

    preceding = full_text[max(0, pos - 600):pos].lower()
    for pattern, name in SECTION_PATTERNS:
        if re.search(pattern, preceding, re.IGNORECASE):
            return name

    return "body"


# ==============================================================================
# 3. INTERPRETACIÓN IA EN LOTE (ETAPA 2) + INGESTA INTEGRAL
# ==============================================================================

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>\)\]]+", re.IGNORECASE)


def parse_reference_entry(ref: str) -> Optional[Dict[str, Any]]:
    """Extrae autor principal, año y DOI de una entrada de referencia bibliográfica.

    Tolerante con formatos APA, Harvard, Chicago y numéricos (Vancouver/IEEE).
    """
    if not ref or len(ref.strip()) < 10:
        return None
    r = ref.strip()

    # 1. DOI
    m_doi = DOI_RE.search(r)
    doi = m_doi.group(0).rstrip(".,;:)]}").strip().lower() if m_doi else None

    # 2. Limpiar numeración inicial tipo '1. ', '[12] ', '(3) '
    clean = re.sub(r"^[\[\(]?\d+[\]\.\)\s\-]+\s*", "", r).strip()

    # 3. Extraer año (1900-2099)
    m_yr = re.search(r"\b(19\d{2}|20\d{2})([a-z]?)\b", clean)
    year = int(m_yr.group(1)) if m_yr else None
    year_suffix = m_yr.group(2) if m_yr else ""

    # 4. Extraer apellido del primer autor
    author = None
    if "," in clean:
        first_part = clean.split(",")[0].strip()
        if len(first_part.split()) <= 3 and len(first_part) < 40:
            author = first_part
    if not author:
        m_auth = re.match(r"^([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\-]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\-]+)?)", clean)
        if m_auth:
            cand = m_auth.group(1).strip()
            if len(cand.split()) <= 3 and len(cand) < 40:
                author = cand

    return {
        "author": author,
        "year": year,
        "year_suffix": year_suffix,
        "doi": doi,
        "raw": r,
    }


def batch_classify_contexts(detected: list[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fusiona heurística + IA: si la IA da función válida, manda ella.

    Devuelve la misma lista con claves function/claim/confidence. Sin LLM
    disponible, conserva la heurística con la afirmación literal de la oración y confidence='heuristic'.
    """
    merged = [
        {
            "function": c.get("sentiment"),
            "claim": c.get("sentence"),  # Afirmación literal por defecto: la oración exacta donde se inserta la cita
            "confidence": "heuristic",
        }
        for c in detected
    ]
    try:
        from . import librarian
        ai = librarian.classify_citation_functions(detected)
    except Exception as e:
        log.warning("Clasificador IA no disponible, heurística: %s", e)
        return merged
    if not ai:
        return merged
    for m, a, orig in zip(merged, ai, detected):
        if a and a.get("function"):
            m["function"] = a["function"]
            # Si el LLM extrajo claim literal, usarlo; de lo contrario mantener la oración literal original
            m["claim"] = a.get("claim") or orig.get("sentence")
            m["confidence"] = a.get("confidence") or "low"
    return merged


def extract_numeric_citation_contexts(
    body_text: str,
    references: list[str],
    max_refs: int = 300,
) -> List[Dict[str, Any]]:
    """Resuelve citas de estilo NUMERICO ([12], [12,13], [12-14], (12)) a la n-esima referencia.

    Es la via que falta para los articulos que no citan por apellido. La resolucion es
    determinista: el indice apunta a la posicion en la lista de referencias.
    """
    if not body_text or not references:
        return []

    parseadas: list[dict] = []
    for ref in references[:max_refs]:
        pr = parse_reference_entry(ref)
        parseadas.append(pr or {})
    n_refs = len(parseadas)
    if n_refs < 5:
        return []

    # Solo indices de 1-3 digitos; un anio de 4 cifras nunca casa y ademas se descarta
    # al validar contra n_refs.
    patron = re.compile(r"[\(\[]\s*(\d{1,3}(?:\s*[-,]\s*\d{1,3})*)\s*[\)\]]")
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", body_text) if len(p.strip()) > 40]

    out: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for para in parrafos:
        if _looks_like_reference_entry(para):
            continue
        for m in patron.finditer(para):
            indices: list[int] = []
            for trozo in re.split(r"[,\-]", m.group(1)):
                trozo = trozo.strip()
                if trozo.isdigit():
                    indices.append(int(trozo))
            for n in indices:
                if not (1 <= n <= n_refs):
                    continue
                ref = parseadas[n - 1]
                if not ref:
                    continue
                oracion = _extract_sentence_at(para, m.start())
                clave = f"{_norm(oracion)[:70]}|{n}"
                if clave in vistos:
                    continue
                vistos.add(clave)
                out.append({
                    "paragraph": para,
                    "sentence": oracion,
                    "sentiment": _classify_sentiment(para),
                    "section": "body",
                    "context_type": "numeric",
                    "numeric_index": n,
                    "cited_author": ref.get("author"),
                    "cited_year": ref.get("year"),
                    "cited_doi": ref.get("doi"),
                })
    return out


def _extract_sentence_at(paragraph: str, pos: int) -> str:
    """Oracion que contiene la posicion indicada."""
    inicio = 0
    for m in re.finditer(r"(?<=[.!?])\s+", paragraph):
        if m.end() > pos:
            return paragraph[inicio:m.start()].strip() or paragraph[:220]
        inicio = m.end()
    return paragraph[inicio:].strip() or paragraph[:220]


def extract_dois_from_texts(texts: list[str] | None) -> List[str]:
    """Extrae DOIs canónicos de textos de referencias."""
    out: list[str] = []
    seen: set[str] = set()
    for t in texts or []:
        for m in DOI_RE.finditer(str(t or "")):
            doi = m.group(0).rstrip(".,;:)]}").strip().lower()
            if doi and doi not in seen:
                seen.add(doi)
                out.append(doi)
    return out


def ingest_fulltext_and_contexts(
    conn,
    citing_doi: str,
    full_text: str,
    sections: dict | None = None,
    word_count: int | None = None,
    page_count: int | None = None,
    cited_dois: list[str] | None = None,
    references_texts: list[str] | None = None,
    http=None,
    auto_ingest_refs: bool = True,
    max_cited: int = 60,
) -> Dict[str, Any]:
    """Ruta integral compartida (manual + automática): guarda fulltext, detecta,
    interpreta (IA + heurística) y persiste contextos; auto-ingiere citados ausentes.
    """
    citing_doi = (citing_doi or "").strip().lower()
    db.save_article_fulltext(
        conn, doi=citing_doi, markdown_text=full_text,
        sections=sections, word_count=word_count, page_count=page_count,
    )

    # 1. Auto-ingesta PREVIA de referencias para poblar catálogo SQLite con autor/año oficiales
    ingested_cited: list[str] = []
    ref_dois = extract_dois_from_texts(references_texts)
    if auto_ingest_refs:
        extra = [d for d in ref_dois if d != citing_doi]
        if extra:
            try:
                from .harvester import cited as cited_mod
                ingested_cited = cited_mod.ensure_cited_articles(conn, http, extra)
            except Exception as e:
                log.warning("Auto-ingesta previa de citados falló: %s", e)

    # 2. Parseo directo de referencias bibliográficas (rescata autor y año aun sin DOI o sin red)
    parsed_refs: list[dict] = []
    for r_str in (references_texts or []):
        parsed = parse_reference_entry(r_str)
        if parsed and (parsed.get("author") or parsed.get("doi")):
            parsed_refs.append(parsed)

    # 3. Preparar texto del cuerpo (excluyendo la lista de referencias para evitar falsos positivos)
    body_text = full_text
    if sections and isinstance(sections, dict):
        body_sections = [v for k, v in sections.items() if k != "references" and v]
        if body_sections:
            body_text = "\n\n".join(body_sections)
    elif "## References" in full_text or "## Referencias" in full_text:
        body_text = re.split(r"\n##\s*(?:references|referencias|bibliograf[ií]a)\b", full_text, flags=re.IGNORECASE)[0]

    # 4. Consolidar catálogo de obras a rastrear en el texto del cuerpo
    from .citation_graph import build_index
    targets_to_check: list[dict] = []
    seen_keys: set[str] = set()

    # Prioridad A: Referencias bibliográficas del propio artículo (con autor/año parseados)
    for pr in parsed_refs:
        p_doi = pr.get("doi")
        if p_doi and p_doi == citing_doi:
            continue
        p_auth = pr.get("author")
        p_yr = pr.get("year")
        # Si tiene DOI y ya fue ingestada en BD, obtener metadata oficial más rica
        if p_doi:
            c_art = db.get_article(conn, p_doi)
            if c_art:
                p_yr = c_art.get("year") or p_yr
                authors = c_art.get("authors") or []
                if authors and isinstance(authors[0], dict):
                    p_auth = authors[0].get("family") or authors[0].get("name", "").split()[-1] or p_auth
                elif authors and isinstance(authors[0], str):
                    p_auth = authors[0].split()[-1] or p_auth

        target_key = p_doi or f"{p_auth}_{p_yr}"
        if target_key and target_key not in seen_keys:
            seen_keys.add(target_key)
            targets_to_check.append({
                "doi": p_doi or f"ref:{re.sub(r'[^a-zA-Z0-9]', '', str(p_auth or 'autor')).lower()}_{p_yr or 'nd'}",
                "author": p_auth,
                "year": p_yr,
                "raw_ref": pr.get("raw"),
            })

    # Prioridad B: DOIs explícitos pasados como argumento o del catálogo de la revisión
    catalog_dois = list(cited_dois or [])
    if len(targets_to_check) < max_cited:
        if not catalog_dois:
            idx = build_index(conn)
            for k in idx.keys():
                if k.startswith("doi:") and k[4:] != citing_doi:
                    catalog_dois.append(k[4:])
                if len(catalog_dois) >= max_cited:
                    break
        for c_doi in catalog_dois:
            if c_doi == citing_doi or c_doi in seen_keys:
                continue
            seen_keys.add(c_doi)
            c_art = db.get_article(conn, c_doi)
            first_author = None
            year = None
            if c_art:
                year = c_art.get("year")
                authors = c_art.get("authors") or []
                if authors and isinstance(authors[0], dict):
                    first_author = authors[0].get("family") or authors[0].get("name", "").split()[-1]
                elif authors and isinstance(authors[0], str):
                    first_author = authors[0].split()[-1]
            targets_to_check.append({
                "doi": c_doi,
                "author": first_author,
                "year": year,
                "raw_ref": None,
            })
            if len(targets_to_check) >= max_cited:
                break

    # 5. Rastrear párrafos y oraciones donde se insertan las citas en el cuerpo del manuscrito
    pending: list[tuple[str, dict]] = []
    for tgt in targets_to_check:
        t_doi = tgt["doi"]
        t_auth = tgt["author"]
        t_yr = tgt["year"]
        for c in extract_citation_contexts(body_text, cited_doi=t_doi,
                                           cited_author=t_auth, cited_year=t_yr):
            if tgt.get("raw_ref"):
                c["reference_source"] = tgt["raw_ref"]
            pending.append((t_doi, c))

    labels = batch_classify_contexts([c for _, c in pending])
    detected: list[dict] = []
    for (c_doi, c), lab in zip(pending, labels):
        merged = {
            **c,
            "function": lab.get("function") or c.get("sentiment"),
            "claim": lab.get("claim") or c.get("sentence"),
            "confidence": lab.get("confidence") or "heuristic",
        }
        db.save_citation_context(conn, citing_doi=citing_doi, cited_doi=c_doi, context=merged)
        detected.append({**merged, "citing_doi": citing_doi, "cited_doi": c_doi})

    by_function: dict[str, int] = {}
    for d in detected:
        fn = d.get("function") or d.get("sentiment") or "unknown"
        by_function[fn] = by_function.get(fn, 0) + 1
    return {
        "contexts": detected,
        "citation_contexts_extracted": len(detected),
        "by_function": by_function,
        "ingested_cited": ingested_cited,
    }
