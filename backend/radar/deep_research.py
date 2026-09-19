"""Deep Research híbrido: síntesis determinista + LLM opcional con grounding estricto.

Modo `deterministic`: informes en capas generados por plantilla sobre fragmentos reales.
Modo `hybrid`: el LLM recibe SOLO el evidence pack (fragmentos literales + DOIs) y debe
redactar la síntesis; un post-check determinista verifica que cada DOI citado exista en
el pack. Sin LLM configurado, hybrid degrada a determinista con aviso.

Reglas de soberanía epistémica:
- Nunca se generan perfiles de autor (lección LeapSpace).
- Ninguna afirmación puede citar evidencia que no esté en el pack.
- El nivel de confianza siempre lo computa el motor, nunca el LLM.
"""
from __future__ import annotations

import json
import os
import sqlite3

import httpx

from . import librarian as _lib
from . import profile, reports
from .evidence_pack import build_pack

LLM_API = os.environ.get("THINKUY_LLM_API", "")
LLM_MODEL = os.environ.get("THINKUY_LLM_MODEL", "gpt-4o-mini")


def llm_available() -> bool:
    # El bibliotecario manda: URL + perfil habilitado. Fallback a vars clásicas.
    try:
        if _lib.available():
            return True
    except Exception:
        pass
    return bool(LLM_API) and bool(profile.field_profile.llm.get("enabled", False))


def _system_prompt() -> str:
    return (
        "Eres un sintetizador académico para Thinkuy (radar de comunicación científica). "
        "Recibes un evidence pack con fragmentos literales reales de artículos (cada uno con su DOI). "
        "REGLAS DURAS: "
        "1) Escribe un informe en capas: respuesta directa, hallazgos clave (con DOIs entre paréntesis), "
        "contradicciones si las hay, y tres preguntas focales. "
        "2) SOLO puedes citar DOIs presentes en el pack. No inventes fuentes. "
        "3) Si un punto no tiene evidencia en el pack, márcalo como [SIN EVIDENCIA EN EL CORPUS]. "
        "4) Responde en español, estilo académico formal y neutral."
    )


def _llm_synthesize(pack: dict) -> str:
    # Vía librarian (Mistral en LM Studio). Mantiene grounding estricto fuera.
    try:
        return _lib.synthesize(pack)
    except Exception:
        pass
    prompt = {
        "topic": pack["topic"],
        "evidence": [
            {"doi": i["doi"], "title": i["title"], "year": i["year"],
             "journal": i["journal"], "fragment": i["fragment"], "stance": i["stance"]}
            for i in pack["items"]
        ],
    }
    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": "Evidence pack (JSON):\n" + json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": 0.2,
    }
    resp = httpx.post(f"{LLM_API}/chat/completions", json=body, timeout=120,
                      headers={"Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _postcheck_grounding(text: str, pack: dict) -> dict:
    """Verifica que todo DOI citado en la síntesis exista en el pack (string-match)."""
    valid_dois = {i.get("doi") for i in pack["items"] if i.get("doi")}
    import re
    cited = set(re.findall(r"10\.\d{4,9}/[^\s)\]]+", text))
    cited = {c.rstrip(".,;") for c in cited}
    grounded = cited & valid_dois
    ungrounded = cited - valid_dois
    return {"cited_dois": sorted(cited), "grounded": sorted(grounded),
            "ungrounded": sorted(ungrounded),
            "verdict": "ok" if not ungrounded else "has_unverified"}


def deep_research(conn: sqlite3.Connection, topic: str, mode: str = "deterministic",
                  limit: int = 20) -> dict:
    if mode == "hybrid" and llm_available():
        pack = build_pack(conn, topic, limit=limit)
        synthesis = _llm_synthesize(pack)
        grounding = _postcheck_grounding(synthesis, pack)
        base = reports.layered_report(conn, topic, limit=limit)
        base["synthesis_llm"] = synthesis
        base["grounding_check"] = grounding
        base["mode"] = "hybrid"
        return base
    if mode == "hybrid":
        report = reports.layered_report(conn, topic, limit=limit)
        report["mode"] = "hybrid_degraded"
        report["warning"] = "LLM no configurado (THINKUY_LLM_API + perfil.llm.enabled): se devuelve el informe determinista."
        return report
    report = reports.layered_report(conn, topic, limit=limit)
    report["mode"] = "deterministic"
    return report