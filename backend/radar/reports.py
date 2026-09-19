"""Informes en capas («estado de la conversación»), tipo LeapSpace pero verificable.

Capas:
  1. Matriz de hallazgos clave  (hallazgo / qué significa / contexto / citaciones)
  2. Claim Radar                 (apoya / contradice / mixto, con DOI y fragmento)
  3. Nivel de confianza          (computado: fuentes independientes + consistencia + cobertura)
  4. Respuesta directa           (resumen ejecutivo)
  5. Preguntas focales           (del módulo de vacíos)

Todo determinista: los hallazgos se derivan de los campos temáticos reales del
evidence pack; las citas apuntan a fragmentos literales del corpus.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import gaps, profile
from . import topics as topics_mod
from .evidence_pack import build_pack


def _confidence(pack: dict) -> dict:
    items = pack["items"]
    n = max(len(items), 1)
    support = sum(1 for i in items if i["stance"] == "supporting")
    contradict = sum(1 for i in items if i["stance"] == "contradicting")
    mixed = n - support - contradict
    journals = pack.get("independent_journals", 0)
    with_fragment = sum(1 for i in items if (i.get("fragment") or "").strip())
    consistency = support / n
    coverage = with_fragment / n
    independence = min(1.0, journals / max(5, n))
    score = round(0.4 * coverage + 0.3 * consistency + 0.3 * independence, 3)
    level = "alta" if score >= 0.7 else ("media" if score >= 0.45 else "baja")
    return {
        "score": score,
        "level": level,
        "n_evidence": len(items),
        "independent_journals": journals,
        "supporting": support,
        "contradicting": contradict,
        "mixed": mixed,
        "coverage_fragments": coverage,
        "note": ("Confiabilidad computada (determinista): cobertura de fragmentos + "
                 "consistencia de apoyo + independencia de fuentes."),
    }


def _hallazgos(pack: dict) -> list[dict]:
    """Deriva hallazgos agrupando la evidencia por campo temático dominante."""
    by_field: dict[str, list[dict]] = {}
    for it in pack["items"]:
        by_field.setdefault(it["thematic_field"], []).append(it)
    fields = {f["id"]: f for f in profile.field_profile.topics}
    out = []
    for fid, items in sorted(by_field.items(), key=lambda kv: -len(kv[1])):
        fname = fields.get(fid, {}).get("name") if fid != "general" else "General / transversal"
        total_cites = sum(i.get("cited_by") or 0 for i in items)
        out.append({
            "hallazgo": (f"La literatura del campo «{fname}» concentra {len(items)} "
                         f"publicaciones relevantes a la pregunta (media de citas "
                         f"recibidas {total_cites / len(items):.1f})."),
            "que_significa": (f"Hay una conversación activa y verificable en torno a "
                              f"{', '.join(k.lower() for k in pack['query_keywords'][:3])} "
                              f"dentro de esta vertiente; no es un tema huérfano."),
            "contextos": f"Revistas que lo publican: {', '.join(sorted({i['journal'] for i in items if i['journal']})[:5]) or '—'}.",
            "citas": [{"doi": i["doi"], "title": i["title"], "year": i["year"]} for i in items[:6]],
        })
    return out


def _claim_radar(pack: dict) -> dict:
    buckets = {"supporting": [], "contradicting": [], "mixed": []}
    for it in pack["items"]:
        buckets[it["stance"]].append({
            "doi": it["doi"], "title": it["title"], "year": it["year"],
            "journal": it["journal"], "fragment": it["fragment"][:220],
        })
    return {
        "claim": f"En el corpus cosechado, la pregunta «{pack['topic']}» cuenta con evidencia "
                 f"predominantemente {'consistente' if len(buckets['supporting']) >= len(buckets['contradicting']) else 'en debate'}.",
        "supporting": buckets["supporting"][:6],
        "contradicting": buckets["contradicting"][:6],
        "mixed": buckets["mixed"][:6],
    }


def layered_report(conn: sqlite3.Connection, topic: str, limit: int = 20) -> dict:
    pack = build_pack(conn, topic, limit=limit)
    hallazgos = _hallazgos(pack)
    return {
        "topic": topic,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "field": profile.field_profile.name,
        "direct_answer": _direct_answer(pack, hallazgos),
        "key_findings": hallazgos,
        "claim_radar": _claim_radar(pack),
        "confidence": _confidence(pack),
        "evidence_pack": pack,
        "focused_questions": gaps.three_questions(conn),
        "method": "determinista (fragmentos literales + marcadores + confianza computada)",
    }


def _direct_answer(pack: dict, hallazgos: list[dict]) -> str:
    n = pack["n"]
    j = pack["independent_journals"]
    if not hallazgos:
        return (f"Con {n} publicaciones en {j} revistas independientes, la pregunta "
                f"«{pack['topic']}» todavía no deja ver una conversación consolidada en el corpus.")
    main = hallazgos[0]
    q = ', '.join(k for k in pack['query_keywords'][:3])
    return (f"Resumen ejecutivo: la pregunta «{pack['topic']}» dialoga con {n} publicaciones "
            f"distribuidas en {j} revistas del campo. El hallazgo principal: {main['hallazgo']} "
            f"En cuanto a posturas, {pack['n'] - sum(1 for i in pack['items'] if i['stance'] == 'contradicting')} "
            f"de {n} piezas apoyan o matizan la conversación sobre {q}.")


# ---------------------------------------------------------------- export Markdown

def report_markdown(report: dict) -> str:
    lines = [
        f"# Estado de la conversación: «{report['topic']}»",
        "",
        f"*Campo: {report['field']} · {report['generated_at']} · método: {report['method']}*",
        "",
        "## Respuesta directa",
        "",
        report["direct_answer"],
        "",
        "## Hallazgos clave",
        "",
        "| Hallazgo | Qué significa | Contextos |",
        "|---|---|---|",
    ]
    for h in report["key_findings"]:
        lines.append(f"| {h['hallazgo']} | {h['que_significa']} | {h['contextos']} |")
    lines += ["", "## Claim Radar", ""]
    cr = report["claim_radar"]
    lines.append(f"**Afirmación:** {cr['claim']}")
    for stance, label in (("supporting", "Apoya"), ("contradicting", "Contradice"), ("mixed", "Mixto")):
        items = cr[stance]
        if items:
            lines.append(f"\n**{label} ({len(items)}):**")
            for it in items[:5]:
                lines.append(f"- {it['title']} *({it['year']})* · {it['journal']} — DOI {it['doi'] or '—'}")
    lines += ["", "## Nivel de confianza", "",
              f"- **Nivel:** {report['confidence']['level']} (score {report['confidence']['score']})",
              f"- Evidencia: {report['confidence']['n_evidence']} piezas · {report['confidence']['independent_journals']} revistas",
              f"- Apoya {report['confidence']['supporting']} · Contradice {report['confidence']['contradicting']} · Mixto {report['confidence']['mixed']}",
              f"- Nota: {report['confidence']['note']}", ""]
    qs = report.get("focused_questions", {}).get("questions") or []
    if qs:
        lines += ["## Preguntas focales", ""]
        for i, x in enumerate(qs, 1):
            lines.append(f"{i}. **[{x['type']}]** {x['question']}")
    lines += ["", "## Referencias (evidence pack)", ""]
    for i, it in enumerate(report["evidence_pack"]["items"], 1):
        lines.append(f"{i}. {it['title']} *({it['year']})* — {it['journal']} · DOI {it['doi'] or '—'}")
    return "\n".join(lines)