"""Motor de Aprendizaje Activo Incremental (Active Learning) para Screening PRISMA.

Inspirado en los principios de ASReview (human-in-the-loop screening), optimizado
para soberanía de datos, ejecución ultrarrápida y cero dependencias pesadas:
- Vectorización TF-IDF con n-gramas (1, 2) y normalización trilingüe (ES/EN/PT).
- Retroalimentación de relevancia con centroides de Rocchio (artículos incluidos vs excluidos).
- Total explicabilidad: desglosa los términos conceptuales que causaron la priorización.
- Cálculo de métricas de progreso de saturación y ahorro estimado de lectura.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set

from .normalize import tokens

# Stopwords académicas trilingües (ES / EN / PT)
_STOPWORDS: Set[str] = {
    # Español
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "a", "al",
    "en", "para", "por", "con", "sin", "sobre", "entre", "tras", "durante", "mediante",
    "y", "e", "o", "u", "pero", "sino", "que", "cual", "quien", "cuyo", "como", "cuando",
    "donde", "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas", "aquel",
    "aquella", "su", "sus", "mi", "mis", "tu", "tus", "se", "lo", "le", "les", "nos",
    "ser", "es", "son", "fue", "fueron", "era", "eran", "ha", "han", "habia", "habian",
    "estudio", "articulo", "investigacion", "trabajo", "analisis", "objetivo", "metodo",
    "resultados", "conclusiones", "autor", "autores", "campo", "caso", "datos",
    # Inglés
    "the", "a", "an", "of", "to", "in", "for", "with", "without", "on", "at", "by",
    "from", "about", "between", "through", "after", "before", "and", "or", "but", "if",
    "that", "which", "who", "whom", "whose", "as", "when", "where", "this", "that",
    "these", "those", "its", "their", "our", "your", "his", "her", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "study", "article", "paper", "research", "analysis", "aim", "method", "methods",
    "results", "conclusion", "conclusions", "author", "authors", "data", "using",
    # Portugués
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "para", "por", "pelo", "pela", "pelos", "pelas",
    "com", "sem", "sobre", "entre", "e", "ou", "mas", "que", "qual", "quem", "cujo",
    "como", "quando", "onde", "este", "esta", "estes", "estas", "esse", "essa", "esses",
    "seu", "sua", "seus", "suas", "se", "estudo", "artigo", "pesquisa", "trabalho",
    "analise", "objetivo", "metodologia", "resultados", "conclusoes", "dados",
}


def _extract_ngrams(text: str, max_n: int = 2) -> List[str]:
    """Extrae unigramas y bigramas relevantes eliminando stopwords y puntuación."""
    toks = [t for t in tokens(text) if len(t) > 2 and t not in _STOPWORDS and not t.isdigit()]
    result = list(toks)
    if max_n >= 2 and len(toks) >= 2:
        for i in range(len(toks) - 1):
            result.append(f"{toks[i]}_{toks[i+1]}")
    return result


def _build_doc_repr(article: Dict[str, Any]) -> Counter:
    """Construye la bolsa de n-gramas ponderando título (x2.5) y keywords (x2.0) sobre abstract (x1.0)."""
    title = str(article.get("title") or "")
    abstract = str(article.get("abstract") or "")
    kws = article.get("keywords") or []
    if isinstance(kws, list):
        kws_text = " ".join(str(k) for k in kws if k)
    else:
        kws_text = str(kws or "")

    cnt = Counter()
    for tok in _extract_ngrams(title, max_n=2):
        cnt[tok] += 2.5
    for tok in _extract_ngrams(kws_text, max_n=2):
        cnt[tok] += 2.0
    for tok in _extract_ngrams(abstract, max_n=2):
        cnt[tok] += 1.0

    return cnt


class ScreeningActiveLearner:
    """Clasificador de aprendizaje activo incremental con Relevance Feedback (Rocchio)."""

    def __init__(self, alpha: float = 1.0, beta: float = 0.45):
        """
        alpha: peso de atracción hacia los artículos incluidos.
        beta: peso de repulsión respecto a los artículos excluidos.
        """
        self.alpha = alpha
        self.beta = beta
        self.idf: Dict[str, float] = {}
        self.doc_vectors: Dict[str, Dict[str, float]] = {}

    def fit_corpus(self, articles: Sequence[Dict[str, Any]]) -> None:
        """Calcula estadísticas IDF sobre el corpus completo para ponderación TF-IDF."""
        n_docs = len(articles)
        if n_docs == 0:
            return

        doc_freq: Counter = Counter()
        doc_counters: Dict[str, Counter] = {}

        for art in articles:
            key = str(art.get("doi") or art.get("id") or "").strip().lower()
            cnt = _build_doc_repr(art)
            doc_counters[key] = cnt
            for term in cnt.keys():
                doc_freq[term] += 1

        # Smooth IDF
        self.idf = {
            term: math.log((n_docs + 1.0) / (df + 1.0)) + 1.0
            for term, df in doc_freq.items()
        }

        # Vectorización normalizada L2 por documento
        self.doc_vectors = {}
        for key, cnt in doc_counters.items():
            vec = {}
            norm_sq = 0.0
            for term, tf in cnt.items():
                tfidf = tf * self.idf.get(term, 1.0)
                vec[term] = tfidf
                norm_sq += tfidf * tfidf
            norm_val = math.sqrt(norm_sq) or 1.0
            self.doc_vectors[key] = {term: val / norm_val for term, val in vec.items()}

    def _cosine_similarity(self, vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
        """Similitud coseno entre dos vectores dispersos."""
        if not vec_a or not vec_b:
            return 0.0
        if len(vec_a) > len(vec_b):
            vec_a, vec_b = vec_b, vec_a
        return sum(val * vec_b.get(term, 0.0) for term, val in vec_a.items())

    def _compute_centroid(self, keys: Sequence[str]) -> Dict[str, float]:
        """Calcula el vector centroide promedio y normalizado de un conjunto de documentos."""
        valid_keys = [k for k in keys if k in self.doc_vectors]
        if not valid_keys:
            return {}

        accum: Counter = Counter()
        for k in valid_keys:
            for term, val in self.doc_vectors[k].items():
                accum[term] += val

        n = float(len(valid_keys))
        centroid = {term: val / n for term, val in accum.items()}

        norm_sq = sum(v * v for v in centroid.values())
        norm_val = math.sqrt(norm_sq) or 1.0
        return {term: v / norm_val for term, v in centroid.items()}

    def rank_candidates(
        self,
        articles: Sequence[Dict[str, Any]],
        labeled_screenings: Dict[str, str] | Sequence[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Reordena los artículos pendientes según aprendizaje activo incremental."""
        decisions: Dict[str, str] = {}
        if isinstance(labeled_screenings, dict):
            for k, v in labeled_screenings.items():
                decisions[str(k).strip().lower()] = str(v).strip().lower()
        else:
            for s in labeled_screenings:
                k = str(s.get("doi") or s.get("article_id") or "").strip().lower()
                d = str(s.get("decision") or "pending").strip().lower()
                if k:
                    decisions[k] = d

        if not self.doc_vectors:
            self.fit_corpus(articles)

        included_keys = [k for k, d in decisions.items() if d == "included"]
        excluded_keys = [k for k, d in decisions.items() if d == "excluded"]
        maybe_keys = [k for k, d in decisions.items() if d == "maybe"]

        combined_pos_keys = list(included_keys) + list(maybe_keys)

        centroid_pos = self._compute_centroid(combined_pos_keys)
        centroid_neg = self._compute_centroid(excluded_keys)

        has_positive_evidence = bool(centroid_pos)

        ranked: List[Dict[str, Any]] = []
        for art in articles:
            key = str(art.get("doi") or art.get("id") or "").strip().lower()
            current_decision = decisions.get(key, "pending")

            vec = self.doc_vectors.get(key, {})
            score = 0.0
            explanation_terms: List[str] = []

            if has_positive_evidence:
                sim_pos = self._cosine_similarity(vec, centroid_pos)
                sim_neg = self._cosine_similarity(vec, centroid_neg) if centroid_neg else 0.0
                score = (self.alpha * sim_pos) - (self.beta * sim_neg)

                term_contributions = [
                    (term, val * centroid_pos.get(term, 0.0))
                    for term, val in vec.items()
                    if term in centroid_pos
                ]
                term_contributions.sort(key=lambda x: -x[1])
                explanation_terms = [t[0].replace("_", " ") for t in term_contributions[:4]]
            else:
                citations = float(art.get("cited_by") or 0)
                year = float(art.get("year") or 2020)
                score = math.log1p(citations) * 0.1 + (year - 2000) * 0.01

            ranked.append({
                "article": art,
                "key": key,
                "decision": current_decision,
                "priority_score": round(score, 4),
                "explanation_terms": explanation_terms,
            })

        pending = [r for r in ranked if r["decision"] in ("pending", "unscreened", "")]
        screened = [r for r in ranked if r["decision"] not in ("pending", "unscreened", "")]

        pending.sort(key=lambda x: -x["priority_score"])

        for i, item in enumerate(pending, start=1):
            item["suggested_order"] = i

        result = pending + screened
        if top_k is not None and top_k > 0:
            return result[:top_k]
        return result


def compute_screening_progress_metrics(
    articles_count: int,
    screenings: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Calcula métricas de progreso PRISMA y estimación de saturación / esfuerzo ahorrado."""
    included = 0
    excluded = 0
    maybe = 0
    for s in screenings:
        d = str(s.get("decision") or "").strip().lower()
        if d == "included":
            included += 1
        elif d == "excluded":
            excluded += 1
        elif d == "maybe":
            maybe += 1

    screened = included + excluded + maybe
    total = max(articles_count, screened)
    remaining = max(0, total - screened)

    pct_screened = round((screened / total) * 100, 1) if total > 0 else 0.0
    yield_rate = round((included / screened) * 100, 1) if screened > 0 else 0.0

    return {
        "total_corpus": total,
        "screened": screened,
        "remaining": remaining,
        "included": included,
        "excluded": excluded,
        "maybe": maybe,
        "pct_screened": pct_screened,
        "yield_rate": yield_rate,
        "has_active_learning": included >= 1,
    }
