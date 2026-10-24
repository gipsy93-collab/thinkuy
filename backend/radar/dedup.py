"""Deduplicación por título casi idéntico (fuzzy), **sin modelo**.

Motivo medido (22-09-2026): la misma obra entra por dos fuentes con el título apenas distinto
(«Políticas» vs «Política», acentos, puntuación, subtítulo) y el dedup exacto por DOI/título
normalizado no lo veía. El re-ranker juntó dos registros de ese tipo en las posiciones 1 y 3.

Reglas:
- Compara conjuntos de palabras del título (insensible a acentos y orden).
- Solo fusiona títulos con **≥ 3 palabras** y similitud ≥ umbral (Jaccard), para no juntar
  títulos genéricos cortos («Editorial»).
- Conserva el registro de **mejor calidad** (con resumen, con DOI, más citado).
- **Declara cada fusión**: nunca borra en silencio.
"""
from __future__ import annotations

from .normalize import tokens, word_variants

MIN_TOKENS = 3


def _canon(token: str) -> str:
    """Forma canónica de una palabra (une inflexiones: «política»/«políticas»)."""
    variantes = word_variants(token)
    return min(variantes) if variantes else token


def _firma(titulo: str) -> frozenset[str]:
    return frozenset(_canon(t) for t in tokens(titulo) if len(t) >= 3)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _calidad(art: dict) -> tuple:
    """Clave de preferencia: resumen, DOI, citas, longitud del título."""
    return (
        bool(art.get("abstract")),
        bool(art.get("doi")),
        int(art.get("cited_by") or 0),
        len(art.get("title") or ""),
    )


def deduplicar(articles: list[dict], umbral: float = 0.85) -> tuple[list[dict], list[dict]]:
    """Fusiona títulos casi idénticos. Devuelve `(conservados, fusiones)`.

    `fusiones` es la lista de pares `{conservado, descartado}` para auditar qué se juntó.
    """
    conservados: list[dict] = []
    firmas: list[frozenset[str]] = []
    fusiones: list[dict] = []

    for art in articles:
        firma = _firma(art.get("title") or "")
        elegible = len(firma) >= MIN_TOKENS
        indice = None
        if elegible:
            for i, f in enumerate(firmas):
                if len(f) >= MIN_TOKENS and _jaccard(firma, f) >= umbral:
                    indice = i
                    break

        if indice is None:
            conservados.append(art)
            firmas.append(firma)
            continue

        actual = conservados[indice]
        if _calidad(art) > _calidad(actual):
            fusiones.append({"conservado": art.get("title"), "descartado": actual.get("title"),
                             "fuente_conservada": art.get("source"),
                             "fuente_descartada": actual.get("source")})
            conservados[indice] = art
            firmas[indice] = firma
        else:
            fusiones.append({"conservado": actual.get("title"), "descartado": art.get("title"),
                             "fuente_conservada": actual.get("source"),
                             "fuente_descartada": art.get("source")})

    return conservados, fusiones
