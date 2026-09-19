"""Texto completo y contextos de citación (Fase 1 Epistémica) en SQLite."""
from __future__ import annotations

import json
import sqlite3

from .connection import now_iso

CITATION_FUNCTIONS = (
    "supporting_or_agreement",
    "contrasting_or_refuting",
    "methodological_adoption",
    "neutral_or_mention",
)
CONTEXT_VALIDATIONS = ("pending", "validated", "corrected", "rejected")


def save_article_fulltext(
    conn: sqlite3.Connection,
    doi: str,
    markdown_text: str,
    sections: dict | None = None,
    word_count: int | None = None,
    page_count: int | None = None,
) -> None:
    norm_doi = doi.strip().lower()
    sections_json = json.dumps(sections, ensure_ascii=False) if sections else None
    words = word_count if word_count is not None else len(markdown_text.split())
    conn.execute(
        """INSERT INTO article_fulltext (doi, markdown_text, sections_json, word_count, page_count, extracted_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(doi) DO UPDATE SET
             markdown_text = excluded.markdown_text,
             sections_json = excluded.sections_json,
             word_count    = excluded.word_count,
             page_count    = excluded.page_count,
             extracted_at  = excluded.extracted_at""",
        (norm_doi, markdown_text, sections_json, words, page_count, now_iso()),
    )
    conn.commit()


def get_article_fulltext(conn: sqlite3.Connection, doi: str) -> dict | None:
    norm_doi = doi.strip().lower()
    r = conn.execute("SELECT * FROM article_fulltext WHERE doi = ?", (norm_doi,)).fetchone()
    if not r:
        return None
    d = dict(r)
    if d.get("sections_json"):
        try:
            d["sections"] = json.loads(d["sections_json"])
        except Exception:
            d["sections"] = {}
    return d


def save_citation_context(
    conn: sqlite3.Connection,
    citing_doi: str,
    cited_doi: str,
    context: dict,
) -> int:
    function = context.get("function") or context.get("sentiment")
    if function not in CITATION_FUNCTIONS:
        function = context.get("sentiment")
    cur = conn.execute(
        """INSERT INTO citation_contexts (citing_doi, cited_doi, paragraph, sentence, sentiment, section, context_type, claim_text, confidence, validation_status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            citing_doi.strip().lower(),
            cited_doi.strip().lower(),
            context.get("paragraph") or context.get("paragraph_text") or "",
            context.get("sentence") or "",
            function,
            context.get("section"),
            context.get("context_type"),
            context.get("claim_text") or context.get("claim"),
            context.get("confidence") or "heuristic",
            context.get("validation_status") or "pending",
            now_iso(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_citation_contexts(
    conn: sqlite3.Connection,
    citing_doi: str | None = None,
    cited_doi: str | None = None,
    limit: int = 50,
    status: str | None = None,
) -> list[dict]:
    clauses = []
    params: list = []
    if citing_doi:
        clauses.append("citing_doi = ?")
        params.append(citing_doi.strip().lower())
    if cited_doi:
        clauses.append("cited_doi = ?")
        params.append(cited_doi.strip().lower())
    if status:
        clauses.append("validation_status = ?")
        params.append(status.strip().lower())

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    query = f"SELECT * FROM citation_contexts{where} ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def validate_citation_context(
    conn: sqlite3.Connection,
    context_id: int,
    decision: str,
    corrected_function: str | None = None,
    corrected_claim: str | None = None,
    by: str = "researcher",
) -> dict | None:
    """Validación humana de un contexto: validated / corrected / rejected (o reopen a pending)."""
    clean = str(decision or "").strip().lower()
    if clean not in CONTEXT_VALIDATIONS:
        raise ValueError(f"decision inválida: {decision!r} (válidas: {', '.join(CONTEXT_VALIDATIONS)})")
    sets = ["validation_status = ?", "validated_by = ?", "validated_at = ?"]
    params: list = [clean, by, now_iso()]
    if clean == "corrected":
        if corrected_function:
            if corrected_function not in CITATION_FUNCTIONS:
                raise ValueError(f"función inválida: {corrected_function!r}")
            sets.append("sentiment = ?")
            params.append(corrected_function)
        if corrected_claim is not None:
            sets.append("claim_text = ?")
            params.append(corrected_claim)
    params.append(context_id)
    cur = conn.execute(
        f"UPDATE citation_contexts SET {', '.join(sets)} WHERE id = ?", params
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    r = conn.execute("SELECT * FROM citation_contexts WHERE id = ?", (context_id,)).fetchone()
    return dict(r) if r else None
