"""Detección de controversias (Claim Radar con clasificación retórica semántica).

Clasifica artículos del catálogo frente a una pregunta/tema según su función retórica:
- supporting: Posible consenso (respalda, confirma, valida, evidencia empírica a favor).
- contradicting: Posible disenso (contrasta, contradice, refuta, cuestiona o halla límites).
- methodological: Posible adopción metodológica (estudios centrados en método, protocolo o instrumento).
- mixed: Posible mención contextual (mención de estado del arte, revisión descriptiva o neutral).

Arquitectura en dos niveles:
1. Nivel Semántico (LLM local en librarian.py): infiere postura contextual por inferencia estructurada.
2. Nivel Heurístico Determinista: fallback transparente si el LLM está apagado o en timeout,
   rotulando explícitamente el nivel de confianza ('heuristic' vs 'ai_semantic').
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional

from . import db
from .matching import match_article, parse_keywords

STANCE_LABELS = {
    "supporting": "Posible consenso",
    "contradicting": "Posible disenso",
    "methodological": "Posible adopción metodológica",
    "mixed": "Posible mención contextual",
}

_SUPPORT_RE = re.compile(
    r"\b(confirma|confirman|apoya|apoyan|valida|validan|corrobora|corroboran|"
    r"respald|refuerza|evidencia a favor|evidencia empírica|respalda|respaldo|"
    r"supports|confirm|validate|corroborate|evidence supports|reinforces|"
    r"apoia|apoiam|valida|confirma|corrobora)\b",
    re.IGNORECASE,
)

_CONTRAST_RE = re.compile(
    r"\b(refuta|refutan|contradice|contradicen|cuestiona|cuestionan|desmiente|"
    r"desmienten|discrepa|discrepan|rechaza|rechazan|debate|debaten|en contra de|"
    r"contraevidencia|evidencia contradictoria|difiere|difieren|challenges?|"
    r"contradicts?|refutes?|disputes?|debates?|questions?|undermines?|"
    r"on the contrary|contesta|contestam|refuta|refutam|questiona|questionam|"
    r"rebuts?|diverge|diverges|inconsisten)\b",
    re.IGNORECASE,
)

_METHODOLOGY_RE = re.compile(
    r"\b(protocolo|metodolog|instrumento|escala|validacion psicometrica|"
    r"propuesta metodologica|diseno de investigacion|framework|benchmark|"
    r"psychometric|scale validation|measurement tool)\b",
    re.IGNORECASE,
)

_POSITIVE_RE = re.compile(
    r"\b(supporting|consistent|concord|aligned|evidence supports|supports? the|"
    r"coherente con|consistente con|apoya la)\b",
    re.IGNORECASE,
)


def classify_stance(text: str | None) -> str:
    """Clasificación heurística determinista offline ('supporting' | 'contradicting' | 'methodological' | 'mixed')."""
    if not text:
        return "mixed"
    has_contrast = bool(_CONTRAST_RE.search(text))
    has_support = bool(_SUPPORT_RE.search(text)) or bool(_POSITIVE_RE.search(text))
    has_methodology = bool(_METHODOLOGY_RE.search(text))

    if has_contrast and not has_support:
        return "contradicting"
    if has_support and not has_contrast:
        return "supporting"
    if has_methodology and not has_contrast and not has_support:
        return "methodological"
    return "mixed"


def analyze_topic(
    conn: sqlite3.Connection,
    topic: str,
    limit: int = 30,
    days: int = 3650,
    use_ai: bool = True,
) -> dict:
    """Analiza la controversia en torno a un tema/pregunta con doble capa (LLM semántico + fallback)."""
    from . import librarian

    kws = parse_keywords(topic)
    rows = conn.execute(
        "SELECT * FROM articles ORDER BY cited_by DESC, pub_date DESC LIMIT 2500"
    ).fetchall()
    arts = [db._row_to_article(r) for r in rows]
    candidates = [a for a in arts if match_article(a, kws)["score"] > 0][:limit]

    # Preparar payload para clasificador
    items_to_classify = [
        {
            "doi": a.get("doi"),
            "title": a.get("title"),
            "abstract": a.get("abstract") or "",
            "fragment": (a.get("abstract") or "")[:400],
        }
        for a in candidates
    ]

    ai_results = []
    model_mode = "heuristic_fallback"
    if use_ai and librarian.available() and items_to_classify:
        try:
            ai_results = librarian.classify_topic_stances_ai(items_to_classify, topic=topic)
            if ai_results and len(ai_results) == len(candidates):
                model_mode = "ai_semantic"
        except Exception:
            ai_results = []

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "supporting": [],
        "contradicting": [],
        "methodological": [],
        "mixed": [],
    }

    for idx, a in enumerate(candidates):
        text = a.get("abstract") or ""
        if model_mode == "ai_semantic" and idx < len(ai_results):
            ai_item = ai_results[idx]
            stance = ai_item.get("stance", "mixed")
            confidence = ai_item.get("confidence", "low")
            rationale = ai_item.get("rationale")
        else:
            stance = classify_stance(f"{text} {a.get('title') or ''}")
            confidence = "heuristic"
            rationale = "Marcadores léxico-sintácticos en título o abstract"

        if stance not in buckets:
            stance = "mixed"

        buckets[stance].append({
            "doi": a.get("doi"),
            "title": a.get("title"),
            "year": a.get("year"),
            "journal": a.get("journal_title"),
            "cited_by": a.get("cited_by"),
            "stance": stance,
            "stance_label": STANCE_LABELS.get(stance, "Posible mención contextual"),
            "confidence": confidence,
            "rationale": rationale,
            "fragment": (text[:400] + "…") if len(text) > 400 else text,
        })

    def _top(items, n=10):
        return items[:n]

    return {
        "topic": topic,
        "counts": {k: len(v) for k, v in buckets.items()},
        "stance_labels": STANCE_LABELS,
        "supporting": _top(buckets["supporting"]),
        "contradicting": _top(buckets["contradicting"]),
        "methodological": _top(buckets["methodological"]),
        "mixed": _top(buckets["mixed"]),
        "method": (
            "semántico: LLM local con etiquetas de prudencia epistemológica"
            if model_mode == "ai_semantic"
            else "determinista: marcadores léxico-sintácticos (Claim Radar Offline)"
        ),
        "model_mode": model_mode,
    }