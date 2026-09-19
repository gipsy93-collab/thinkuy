"""Conversación con el corpus de referencia (anchors): citas, CFP y solapamiento temático.

La «conversación» de un artículo externo con el campo se explica por tres señales:
(a) cita artículos publicados por las revistas ancla del perfil, (b) encaja con el
CFP vigente del perfil (si lo hay), (c) solapa temáticamente con el corpus del campo.
"""
from __future__ import annotations

from functools import lru_cache

from . import profile
from .matching import match_article
from .normalize import norm

STOP = {
    "para", "como", "este", "esta", "estos", "estas", "desde", "entre", "sobre",
    "hasta", "donde", "cuando", "porque", "desde", "hacia", "segun", "ante",
    "bajo", "tras", "mediante", "durante", "contra", "aunque", "tambien",
    "desde", "todos", "todas", "otro", "otra", "otros", "otras", "mismo",
    "misma", "cada", "muy", "mas", "menos", "pero", "sino", "cual", "cuales",
    "cuya", "cuyo", "esto", "eso", "aqui", "alli", "asi", "then", "with",
    "from", "that", "this", "these", "those", "which", "their", "have", "been",
    "were", "will", "into", "about", "through", "after", "before", "between",
    "without", "within", "among", "there", "where", "when", "what", "than",
    "them", "they", "said", "also", "more", "some", "such", "only", "other",
    "over", "both", "most", "into", "una", "uno", "del", "las", "los", "por",
    "con", "que", "the", "and", "for", "are", "not", "was", "his", "her",
    "its", "our", "can", "has", "had", "did", "who", "how", "why", "any",
    "all", "out", "new", "use", "using", "used", "based", "study", "paper",
    "article", "analisis", "estudio", "articulo", "revista",
    "communication", "media", "social", "research",
}


def strip_oaid(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.strip().replace("https://openalex.org/", "").upper()


def anchor_matches(art: dict, anchors: list | None = None) -> list[str]:
    """Devuelve las claves de las revistas ancla a las que pertenece el artículo."""
    anchors = anchors if anchors is not None else profile.field_profile.anchors
    if not anchors:
        return []
    issn = (art.get("issn") or "").replace("-", "").replace(" ", "")
    doi = (art.get("doi") or "").lower()
    jt = norm(art.get("journal_title") or "")
    out: list[str] = []
    for an in anchors:
        key = an.get("key")
        if not key:
            continue
        if any(i.replace("-", "") in issn for i in (an.get("issns") or [])):
            out.append(key)
            continue
        if an.get("doi_prefix") and doi.startswith(an["doi_prefix"].lower()):
            out.append(key)
            continue
        if an.get("title_terms") and all(t in jt for t in an["title_terms"]):
            out.append(key)
    return out


def is_anchor_article(art: dict, anchors: list | None = None) -> bool:
    return bool(anchor_matches(art, anchors))


def _kw_strings(art: dict) -> list[str]:
    out = []
    for k in art.get("keywords") or []:
        if isinstance(k, str):
            out.append(k)
        elif isinstance(k, dict):
            out.append(str(k.get("k") or k.get("display_name") or ""))
    return [x for x in out if x]


def article_tokens(art: dict) -> set[str]:
    blob = " ".join([
        art.get("title") or "",
        " ".join(_kw_strings(art)),
        (art.get("abstract") or "")[:900],
    ])
    return {t for t in norm(blob).split() if len(t) > 3 and t not in STOP}


def _axis_tokens() -> set[str]:
    cfp_kws: list[str] = []
    for c in profile.field_profile.cfps:
        cfp_kws.extend(c.get("keywords") or [])
    blob = " ".join(profile.field_profile.editorial_axes + cfp_kws)
    return {t for t in norm(blob).split() if len(t) > 3 and t not in STOP}


def build_profile(anchor_articles: list[dict]) -> dict:
    """Perfil temático del corpus ancla (+ ejes editoriales y CFP como red de seguridad)."""
    oaids: set[str] = set()
    dois: set[str] = set()
    freq: dict[str, int] = {}
    for art in anchor_articles:
        raw_oa = art.get("openalex_id") or (art.get("source_id") if art.get("source") == "openalex" else None)
        oid = strip_oaid(raw_oa)
        if oid:
            oaids.add(oid)
        if art.get("doi"):
            dois.add(art["doi"].strip().lower())
        for t in article_tokens(art):
            freq[t] = freq.get(t, 0) + 1
    top = {t for t, n in freq.items() if n >= 2}
    if len(top) < 40:
        top |= {t for t, n in sorted(freq.items(), key=lambda kv: -kv[1])[:80]}
    top |= _axis_tokens()
    return {
        "openalex_ids": oaids,
        "dois": dois,
        "tokens": top,
        "n_works": len(anchor_articles),
        "cfp": profile.field_profile.first_cfp(),
        "axes": profile.field_profile.editorial_axes,
    }


@lru_cache(maxsize=1)
def _fallback_profile() -> dict:
    return {
        "openalex_ids": frozenset(),
        "dois": frozenset(),
        "tokens": frozenset(_axis_tokens()),
        "n_works": 0,
        "cfp": profile.field_profile.first_cfp(),
        "axes": profile.field_profile.editorial_axes,
    }


def fallback_profile() -> dict:
    p = _fallback_profile()
    return {
        "openalex_ids": set(p["openalex_ids"]),
        "dois": set(p["dois"]),
        "tokens": set(p["tokens"]),
        "n_works": 0,
        "cfp": p["cfp"],
        "axes": p["axes"],
    }


def _cites_anchor(art: dict, profile_data: dict) -> bool:
    if art.get("cites_anchor"):
        return True
    refs = art.get("referenced_ids") or []
    if not refs or not profile_data.get("openalex_ids"):
        return False
    return bool({strip_oaid(x) for x in refs} & profile_data["openalex_ids"])


def score_article(art: dict, profile_data: dict) -> dict:
    """Señales de conversación con el corpus de referencia. No usa keywords del usuario."""
    cfp = profile_data.get("cfp")
    cfp_kw = list((cfp or {}).get("keywords") or [])
    cfp_m = match_article(art, cfp_kw) if cfp_kw else {"score": 0, "matched": []}
    axis_m = match_article(art, profile_data.get("axes") or [])
    toks = article_tokens(art)
    inter = toks & (profile_data.get("tokens") or set())
    overlap_n = len(inter)
    overlap = (overlap_n / max(len(toks), 1)) if toks else 0.0
    cites = _cites_anchor(art, profile_data)
    home = is_anchor_article(art)

    score = 0
    if cites:
        score += 50
    score += min(30, int(cfp_m["score"]))
    score += min(18, int(axis_m["score"] * 0.6))
    score += min(40, overlap_n * 3)
    if overlap >= 0.18:
        score += 8
    if home:
        score = 0

    return {
        "cites_anchor": cites,
        "anchors": anchor_matches(art),
        "cfp_score": int(cfp_m["score"]),
        "cfp_matched": cfp_m.get("matched") or [],
        "axis_score": int(axis_m["score"]),
        "overlap": round(overlap, 3),
        "overlap_n": overlap_n,
        "conversation_score": score,
    }


def why_labels(sig: dict, lang: str = "es") -> list[str]:
    cfp = profile.field_profile.first_cfp()
    cfp_title = None
    if cfp:
        cfp_title = cfp.get("title_en") if lang == "en" else cfp.get("title_es")
    anchor_label = None
    anchors = profile.field_profile.anchors
    if anchors and sig.get("anchors"):
        first_key = sig["anchors"][0]
        anchor_label = next((a.get("label") for a in anchors if a.get("key") == first_key), None)
    out: list[str] = []
    if sig.get("cites_anchor"):
        if anchor_label:
            out.append(
                f"Cites the reference corpus ({anchor_label})"
                if lang == "en"
                else f"Cita el corpus de referencia ({anchor_label})"
            )
        else:
            out.append(
                "Cites the field reference corpus"
                if lang == "en"
                else "Cita el corpus de referencia del campo"
            )
    if sig.get("cfp_score", 0) > 0 and cfp_title:
        out.append(
            f"Fits the current CFP: {cfp_title}"
            if lang == "en"
            else f"Encaja con el CFP vigente: {cfp_title}"
        )
    elif sig.get("axis_score", 0) > 0:
        out.append(
            "Matches the field's editorial scope"
            if lang == "en"
            else "Encaja con las líneas editoriales del campo"
        )
    if sig.get("overlap_n", 0) >= 4 and not sig.get("cites_anchor"):
        n = sig["overlap_n"]
        out.append(
            f"In conversation with the field corpus ({n} thematic matches)"
            if lang == "en"
            else f"Dialoga con el corpus del campo ({n} coincidencias temáticas)"
        )
    return out[:3]


def _date_key(pub_date: str | None) -> int:
    if not pub_date:
        return 0
    d = str(pub_date).replace("-", "")[:8]
    return int(d) if d.isdigit() else 0


def rank_conversation(articles: list[dict], profile_data: dict, mode: str = "conversation") -> list[dict]:
    enriched = []
    for a in articles:
        if is_anchor_article(a):
            continue
        sig = score_article(a, profile_data)
        if sig["conversation_score"] <= 0:
            continue
        if mode == "cfp" and sig["cfp_score"] <= 0:
            continue
        enriched.append({**a, "conversation": sig})
    if mode == "cfp":
        key = lambda a: (-(a["conversation"]["cfp_score"] or 0), -_date_key(a.get("pub_date")))
    elif mode == "latest":
        key = lambda a: (-_date_key(a.get("pub_date")), a.get("doi") or "")
    else:
        key = lambda a: (
            -(a["conversation"]["conversation_score"] or 0),
            -(1 if a["conversation"]["cites_anchor"] else 0),
            -_date_key(a.get("pub_date")),
        )
    enriched.sort(key=key)
    return enriched