"""Ontología de campos de conocimiento y clasificación temática (desde el perfil de campo).

La lista de campos canónicos de la disciplina vive en el perfil (`profiles/<campo>.json`),
no aquí: `fields()` la expone y `classify_article_fields()` la usa para etiquetar artículos.
"""
from __future__ import annotations

import re
from collections import Counter

from . import profile
from .conversation import STOP
from .matching import match_article
from .normalize import norm


def fields(p=None) -> list[dict]:
    """Campos canónicos del perfil activo."""
    p = p or profile.field_profile
    return p.topics or []


_EDGE_PUNCTUATION_RE = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)
_DERIVED_STOPWORDS = STOP | {
    "articulo",
    "articulos",
    "estudio",
    "estudios",
    "objetivo",
    "objetivos",
    "metodo",
    "metodologia",
    "resultados",
    "datos",
    "trabajo",
    "plantea",
    "conclusiones",
    "presenta",
    "introduccion",
    "contexto",
    "proceso",
    "forma",
    "caso",
    "casos",
    "tema",
    "texto",
    "uso",
    "usos",
    "nuevo",
    "nueva",
    "artigo",
    "artigos",
    "analise",
    "estudo",
    "estudos",
    "pesquisa",
    "pesquisas",
    "objetivos",
    "metodo",
    "autores",
    "trabalho",
    "apresenta",
    "apresentam",
    "conclusao",
    "conclusoes",
    "introducao",
    "processo",
    "meio",
    "meios",
}


def declared_keyword_strings(article: dict) -> list[str]:
    """Devuelve las palabras clave declaradas en los metadatos, sin modificarlas."""
    keywords: list[str] = []
    for keyword in article.get("keywords") or []:
        if isinstance(keyword, dict):
            text = keyword.get("k") or keyword.get("display_name") or ""
        else:
            text = keyword
        text = str(text or "").strip()
        if text:
            keywords.append(text)
    return keywords


def _content_token(text: str, excluded: set[str]) -> str | None:
    """Normaliza un token candidato y descarta ruido determinista."""
    stripped = _EDGE_PUNCTUATION_RE.sub("", text or "")
    normalized = norm(stripped)
    if (
        not normalized
        or len(normalized) < 4
        or not any(character.isalpha() for character in normalized)
        or normalized in _DERIVED_STOPWORDS
        or normalized in excluded
    ):
        return None
    return normalized


def _title_phrases(article: dict, excluded: set[str], limit: int = 8) -> list[str]:
    """Extrae frases representativas del título y, si hace falta, del resumen."""
    sources = [
        (article.get("title") or "", 3),
        (article.get("abstract") or "", 1),
    ]
    sequences: list[tuple[list[tuple[str, str]], int]] = []
    displays: dict[tuple[str, ...], str] = {}
    counts: Counter = Counter()
    first_seen: dict[tuple[str, ...], int] = {}
    order = 0

    for text, weight in sources:
        for segment in re.split(r"[,:;()\[\]{}«»“”\"'’/\\|—–-]+", str(text or "")):
            current: list[tuple[str, str]] = []
            for raw_token in segment.split():
                cleaned = _EDGE_PUNCTUATION_RE.sub("", raw_token)
                normalized = _content_token(cleaned, excluded) if cleaned else None
                if normalized:
                    current.append((cleaned, normalized))
                    continue
                if current:
                    sequences.append((current, weight))
                    current = []
            if current:
                sequences.append((current, weight))

    for sequence, _ in sequences:
        for size in (3, 2, 1):
            for start in range(len(sequence) - size + 1):
                window = sequence[start:start + size]
                key = tuple(normalized for _, normalized in window)
                display = " ".join(display for display, _ in window)
                displays.setdefault(key, display)
                counts[key] += weight
                first_seen.setdefault(key, order)
                order += 1

    ranked = sorted(
        counts,
        key=lambda key: (-len(key), -counts[key], first_seen[key]),
    )
    return [displays[key] for key in ranked[:limit]]


def display_keywords(
    article: dict, candidate_terms: list[str] | None = None, limit: int = 6
) -> tuple[list[str], str]:
    """Devuelve palabras clave utilizables y su procedencia.

    Las palabras declaradas se preservan intactas. Cuando no existen, se derivan
    de forma determinista desde la ontología del campo y el título/resumen; esas
    palabras nunca deben presentarse como metadatos editoriales originales.
    """
    declared = declared_keyword_strings(article)
    if declared:
        return declared[:limit], "declared"

    suggestions: list[str] = []
    seen: set[str] = set()

    def remember(text: str | None) -> None:
        cleaned = str(text or "").strip()
        normalized = norm(cleaned)
        if cleaned and normalized and normalized not in seen:
            seen.add(normalized)
            suggestions.append(cleaned)

    for field in classify_article_fields(article):
        for matched in field.get("matched_kws") or []:
            remember(matched)
            if len(suggestions) >= limit:
                return suggestions, "derived"

    for candidate in candidate_terms or []:
        if candidate and match_article(article, [candidate])["score"] > 0:
            remember(candidate)
        if len(suggestions) >= limit:
            return suggestions, "derived"

    excluded: set[str] = set()
    for author in article.get("authors") or []:
        if isinstance(author, dict):
            for value in (str(author.get("given") or ""), str(author.get("family") or "")):
                excluded.update(part for part in (norm(token) for token in value.split()) if part)
    excluded.update(
        part
        for part in (norm(token) for token in str(article.get("journal_title") or "").split())
        if part
    )
    for phrase in _title_phrases(article, excluded, limit=max(limit * 3, 8)):
        remember(phrase)
        if len(suggestions) >= limit:
            break

    return suggestions, "derived" if suggestions else "none"


def classify_article_fields(art: dict, fields_list: list[dict] | None = None) -> list[dict]:
    """Asigna los campos temáticos del perfil a los que pertenece el artículo."""
    fields_list = fields_list if fields_list is not None else fields()
    if not fields_list:
        return []
    text = " ".join([
        norm(art.get("title") or ""),
        norm(art.get("abstract") or ""),
        " ".join(norm(k if isinstance(k, str) else k.get("k", "")) for k in (art.get("keywords") or []))
    ])
    if not text.strip():
        return []

    tokens = set(text.split())
    scored_fields = []

    for f in fields_list:
        score = 0
        matched_kws = []
        all_kws = f["keywords_es"] + f["keywords_pt"]
        for kw in all_kws:
            nkw = norm(kw)
            if " " in nkw:
                if nkw in text:
                    score += 3
                    matched_kws.append(kw)
            else:
                if nkw in tokens:
                    score += 1
                    matched_kws.append(kw)

        # Bonus si la revista está focalizada en este campo
        jt = norm(art.get("journal_title") or "")
        if any(norm(jf) in jt for jf in f["journals_focus"]):
            score += 4

        if score >= 3:
            scored_fields.append({
                "id": f["id"],
                "name": f["name"],
                "score": score,
                "matched_kws": list(dict.fromkeys(matched_kws))[:4],
            })

    scored_fields.sort(key=lambda x: -x["score"])
    return scored_fields[:2]
