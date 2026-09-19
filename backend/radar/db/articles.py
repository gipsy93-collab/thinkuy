"""Gestión y consulta de artículos, keywords y señales de anclaje en SQLite."""
from __future__ import annotations

import json
import sqlite3

from .. import profile
from ..normalize import norm, norm_lang
from .connection import now_iso
from .journals import count_journals


def _detect_anchors(a: dict) -> list[str]:
    """Anclas del perfil a las que pertenece el artículo (por ISSN/DOI/título)."""
    from ..conversation import anchor_matches
    return anchor_matches(a)


def upsert_article(conn: sqlite3.Connection, a: dict) -> tuple[str, int]:
    """Inserta o actualiza por DOI. Devuelve (status, id). El idioma se normaliza a ISO 639-1."""
    ts = now_iso()
    lang = norm_lang(a.get("lang"))
    refs = a.get("referenced_ids") or []
    if isinstance(refs, str):
        refs_json = refs
    else:
        refs_json = json.dumps(refs, ensure_ascii=False)
    anchor_ids = _detect_anchors(a) or []
    if isinstance(anchor_ids, str):
        anchor_ids = json.loads(anchor_ids) if anchor_ids else []
    cites_anchor = a.get("cites_anchor") or []
    if isinstance(cites_anchor, str):
        cites_anchor = json.loads(cites_anchor) if cites_anchor else []
    s2_refs = a.get("s2_references") or []
    if isinstance(s2_refs, str):
        s2_refs = json.loads(s2_refs) if s2_refs else []
    cur = conn.execute(
        """INSERT INTO articles (doi, title, title_alt, abstract, keywords, authors, journal_id,
                                 journal_title, issn, volume, issue, pages, year, pub_date, lang,
                                 url, source, source_id, access, cited_by, openalex_id, referenced_ids,
                                 anchor_ids, cites_anchor, pdf_url, oa_status, s2_paper_id, s2_cited_by,
                                 s2_references, created_at, updated_at)
           VALUES (:doi, :title, :title_alt, :abstract, :keywords, :authors, :journal_id,
                   :journal_title, :issn, :volume, :issue, :pages, :year, :pub_date, :lang,
                   :url, :source, :source_id, :access, :cited_by, :openalex_id, :referenced_ids,
                   :anchor_ids, :cites_anchor, :pdf_url, :oa_status, :s2_paper_id, :s2_cited_by,
                   :s2_references, :created_at, :updated_at)
           ON CONFLICT(doi) DO UPDATE SET
             title        = excluded.title,
             title_alt    = excluded.title_alt,
             abstract     = CASE WHEN excluded.abstract IS NOT NULL AND excluded.abstract != ''
                                 THEN excluded.abstract ELSE articles.abstract END,
             keywords     = CASE WHEN excluded.keywords IS NOT NULL AND excluded.keywords != '[]'
                                 THEN excluded.keywords ELSE articles.keywords END,
             authors      = CASE WHEN excluded.authors IS NOT NULL AND excluded.authors != '[]'
                                 THEN excluded.authors ELSE articles.authors END,
             journal_id   = excluded.journal_id,
             journal_title= excluded.journal_title,
             issn         = excluded.issn,
             volume       = excluded.volume,
             issue        = excluded.issue,
             pages        = excluded.pages,
             year         = excluded.year,
             pub_date     = excluded.pub_date,
             lang         = excluded.lang,
             url          = excluded.url,
             access       = CASE WHEN excluded.access != 'unknown' THEN excluded.access ELSE articles.access END,
             cited_by     = MAX(COALESCE(excluded.cited_by, 0), COALESCE(articles.cited_by, 0)),
             openalex_id  = COALESCE(excluded.openalex_id, articles.openalex_id),
             referenced_ids = CASE
                 WHEN excluded.referenced_ids IS NOT NULL AND excluded.referenced_ids != '[]'
                 THEN excluded.referenced_ids ELSE articles.referenced_ids END,
             anchor_ids   = CASE
                 WHEN excluded.anchor_ids IS NOT NULL AND excluded.anchor_ids != '[]'
                 THEN excluded.anchor_ids ELSE articles.anchor_ids END,
             pdf_url      = COALESCE(excluded.pdf_url, articles.pdf_url),
             oa_status    = COALESCE(excluded.oa_status, articles.oa_status),
             s2_paper_id  = COALESCE(excluded.s2_paper_id, articles.s2_paper_id),
             s2_cited_by  = MAX(COALESCE(excluded.s2_cited_by, 0), COALESCE(articles.s2_cited_by, 0)),
             s2_references = CASE
                 WHEN excluded.s2_references IS NOT NULL AND excluded.s2_references != '[]'
                 THEN excluded.s2_references ELSE articles.s2_references END,
             updated_at   = excluded.updated_at
           RETURNING id, (updated_at <> created_at) AS was_update""",
        {
            "doi": a.get("doi"),
            "title": a["title"],
            "title_alt": a.get("title_alt"),
            "abstract": a.get("abstract"),
            "keywords": json.dumps(a.get("keywords") or [], ensure_ascii=False),
            "authors": json.dumps(a.get("authors") or [], ensure_ascii=False),
            "journal_id": a.get("journal_id"),
            "journal_title": a.get("journal_title"),
            "issn": a.get("issn"),
            "volume": a.get("volume"),
            "issue": a.get("issue"),
            "pages": a.get("pages"),
            "year": a.get("year"),
            "pub_date": a.get("pub_date"),
            "lang": lang,
            "url": a.get("url"),
            "source": a["source"],
            "source_id": a.get("source_id"),
            "access": a.get("access", "unknown"),
            "cited_by": a.get("cited_by"),
            "openalex_id": a.get("openalex_id"),
            "referenced_ids": refs_json,
            "anchor_ids": json.dumps(sorted(anchor_ids), ensure_ascii=False),
            "cites_anchor": json.dumps(sorted(cites_anchor), ensure_ascii=False),
            "pdf_url": a.get("pdf_url"),
            "oa_status": a.get("oa_status"),
            "s2_paper_id": a.get("s2_paper_id"),
            "s2_cited_by": a.get("s2_cited_by"),
            "s2_references": json.dumps(s2_refs, ensure_ascii=False),
            "created_at": ts,
            "updated_at": ts,
        },
    )
    row = cur.fetchone()
    conn.commit()
    was_update = bool(row and row["was_update"]) if row else False
    return ("updated" if was_update else "new", row["id"] if row else None)


def _row_to_article(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("keywords", "authors", "referenced_ids", "anchor_ids", "cites_anchor", "s2_references"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[k] = []
    # Alias de compatibilidad: referenced_works apunta a referenced_ids
    d["referenced_works"] = d.get("referenced_ids", [])
    return d


def row_to_article(r) -> dict:
    """Alias público de _row_to_article para uso externo."""
    return _row_to_article(r)


def get_article(conn: sqlite3.Connection, doi: str) -> dict | None:
    if not doi:
        return None
    r = None
    clean_doi = str(doi).strip()
    # 1. Soporte para identificadores sintéticos de sesión/local (ej. "article:45918")
    if clean_doi.lower().startswith("article:"):
        art_id_str = clean_doi[8:].strip()
        if art_id_str.isdigit():
            r = conn.execute("SELECT * FROM articles WHERE id = ?", (int(art_id_str),)).fetchone()
    # 2. Soporte para ID numérico directo
    if not r and clean_doi.isdigit():
        r = conn.execute("SELECT * FROM articles WHERE id = ?", (int(clean_doi),)).fetchone()
    # 3. Búsqueda por DOI exacto
    if not r:
        r = conn.execute("SELECT * FROM articles WHERE doi = ?", (clean_doi,)).fetchone()
    # 4. Fallback por DOI en minúsculas
    if not r:
        r = conn.execute("SELECT * FROM articles WHERE lower(doi) = lower(?)", (clean_doi,)).fetchone()
    return _row_to_article(r) if r else None


def count_articles(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"]


def stats(conn: sqlite3.Connection) -> dict:
    by_source = {
        r["source"]: r["n"]
        for r in conn.execute("SELECT source, COUNT(*) AS n FROM articles GROUP BY source").fetchall()
    }
    anchor_n = conn.execute(
        "SELECT COUNT(*) AS n FROM articles WHERE anchor_ids IS NOT NULL AND anchor_ids != '[]'"
    ).fetchone()["n"]
    cites_n = conn.execute(
        "SELECT COUNT(*) AS n FROM articles WHERE cites_anchor IS NOT NULL AND cites_anchor != '[]'"
    ).fetchone()["n"]
    return {
        "articles": count_articles(conn),
        "journals": count_journals(conn),
        "by_source": by_source,
        "anchor_articles": anchor_n,
        "cites_anchor": cites_n,
    }


def load_anchor_articles(conn: sqlite3.Connection, anchors: list | None = None) -> list[dict]:
    """Artículos publicados por las revistas ancla del perfil (corpus de referencia)."""
    anchors = anchors if anchors is not None else profile.field_profile.anchors
    keys = [a.get("key") for a in anchors if a.get("key")]
    if not keys:
        return []
    rows = conn.execute(
        "SELECT * FROM articles WHERE anchor_ids IS NOT NULL AND anchor_ids != '[]'"
    ).fetchall()
    return [a for a in (_row_to_article(r) for r in rows) if set(a.get("anchor_ids") or []) & set(keys)]


def rebuild_anchor_signals(conn: sqlite3.Connection, anchors: list | None = None) -> dict:
    """Marca el corpus ancla y las citas hacia él a partir de referenced_ids de OpenAlex.

    Determinista y explicable: solo usa ISSN/DOI/título del perfil y la intersección
    de `referenced_ids` con los IDs OpenAlex de las revistas ancla.
    """
    from ..conversation import strip_oaid

    anchors = anchors if anchors is not None else profile.field_profile.anchors
    conn.execute("UPDATE articles SET anchor_ids = '[]', cites_anchor = '[]'")
    if not anchors:
        conn.commit()
        return {"anchors": 0, "anchor_articles": 0, "cites_anchor": 0}

    rows = conn.execute(
        "SELECT id, issn, doi, journal_title, openalex_id, source_id, source, referenced_ids FROM articles"
    ).fetchall()
    anchor_oaids: dict[str, set[str]] = {an["key"]: set() for an in anchors if an.get("key")}
    belongs: dict[int, set[str]] = {}

    for r in rows:
        issn = (r["issn"] or "").replace("-", "").replace(" ", "")
        doi = (r["doi"] or "").lower()
        jt = norm(r["journal_title"] or "")
        hits: set[str] = set()
        for an in anchors:
            key = an.get("key")
            if not key:
                continue
            if any(i.replace("-", "") in issn for i in (an.get("issns") or [])):
                hits.add(key)
                continue
            if an.get("doi_prefix") and doi.startswith(an["doi_prefix"].lower()):
                hits.add(key)
                continue
            if an.get("title_terms") and all(t in jt for t in an["title_terms"]):
                hits.add(key)
        if hits:
            belongs[r["id"]] = hits
            oid = strip_oaid(r["openalex_id"] or (r["source_id"] if r["source"] == "openalex" else None))
            if oid:
                for k in hits:
                    anchor_oaids[k].add(oid)

    for aid, keys in belongs.items():
        conn.execute(
            "UPDATE articles SET anchor_ids = ? WHERE id = ?",
            (json.dumps(sorted(keys), ensure_ascii=False), aid),
        )

    cites: dict[int, set[str]] = {}
    for r in rows:
        if not r["referenced_ids"]:
            continue
        try:
            refs = json.loads(r["referenced_ids"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        hit_keys = {k for k, oids in anchor_oaids.items() if oids and {strip_oaid(x) for x in refs} & oids}
        if hit_keys:
            cites[r["id"]] = hit_keys

    for aid, keys in cites.items():
        conn.execute(
            "UPDATE articles SET cites_anchor = ? WHERE id = ?",
            (json.dumps(sorted(keys), ensure_ascii=False), aid),
        )

    conn.commit()
    n_anchor = conn.execute(
        "SELECT COUNT(*) AS n FROM articles WHERE anchor_ids IS NOT NULL AND anchor_ids != '[]'"
    ).fetchone()["n"]
    n_cites = conn.execute(
        "SELECT COUNT(*) AS n FROM articles WHERE cites_anchor IS NOT NULL AND cites_anchor != '[]'"
    ).fetchone()["n"]
    return {"anchors": len(anchors), "anchor_articles": n_anchor, "cites_anchor": n_cites}


def rebuild_keywords(conn: sqlite3.Connection) -> None:
    """Reconstruye keywords_flat y el índice FTS5 desde los artículos.

    Se invoca al final de cada cosecha; es barato (tabla << 50k filas).
    """
    conn.execute("DELETE FROM keywords_flat")
    try:
        conn.execute("DELETE FROM keywords_fts")
    except sqlite3.OperationalError:
        pass
    counts: dict[str, int] = {}
    rows = conn.execute("SELECT keywords FROM articles WHERE keywords IS NOT NULL").fetchall()
    for r in rows:
        try:
            kws = json.loads(r["keywords"])
        except (json.JSONDecodeError, TypeError):
            continue
        for kw in kws:
            if isinstance(kw, dict):
                kw = kw.get("k", "")
            kw = str(kw).strip()
            if kw:
                counts[kw] = counts.get(kw, 0) + 1
    conn.executemany(
        "INSERT INTO keywords_flat (kw, norm_kw, n) VALUES (?, ?, ?)",
        ((k, norm(k), v) for k, v in counts.items()),
    )
    try:
        conn.executemany("INSERT INTO keywords_fts (kw) VALUES (?)", ((k,) for k in counts))
    except sqlite3.OperationalError:
        pass
    conn.commit()


def suggest_keywords(conn: sqlite3.Connection, q: str, limit: int = 12) -> list[str]:
    """Autocompletado: FTS5 con prefijo; si FTS no está disponible, LIKE por frecuencia."""
    qn = norm(q)
    if not qn:
        rows = conn.execute(
            "SELECT kw FROM keywords_flat ORDER BY n DESC, kw LIMIT ?",
            (limit,),
        ).fetchall()
        return [r["kw"] for r in rows]
    if " " in qn:
        rows = conn.execute(
            "SELECT kw FROM keywords_flat WHERE norm_kw LIKE ? ORDER BY n DESC, kw LIMIT ?",
            (f"%{qn}%", limit),
        ).fetchall()
        return [r["kw"] for r in rows]
    try:
        term = qn.replace('"', '""')
        rows = conn.execute(
            "SELECT kw FROM keywords_fts WHERE keywords_fts MATCH ? ORDER BY rank LIMIT ?",
            (f'"{term}"*', limit),
        ).fetchall()
        if rows:
            return [r["kw"] for r in rows]
    except sqlite3.OperationalError:
        pass
    rows = conn.execute(
        "SELECT kw FROM keywords_flat WHERE norm_kw LIKE ? ORDER BY n DESC, kw LIMIT ?",
        (f"{qn}%", limit),
    ).fetchall()
    return [r["kw"] for r in rows]


def rebuild_author_stats(conn: sqlite3.Connection) -> None:
    """Reconstruye autorías agregadas (primera/última publicación, nº de artículos).

    Señal de autor 'emergente': primera publicación en el catálogo reciente + ≥2 artículos.
    """
    conn.execute("DELETE FROM author_stats")
    rows = conn.execute("SELECT pub_date, year, authors, journal_title FROM articles").fetchall()
    stats_dict: dict[str, dict] = {}
    for r in rows:
        try:
            authors = json.loads(r["authors"])
        except (json.JSONDecodeError, TypeError):
            continue
        pd = r["pub_date"] or (f"{r['year']}-01-01" if r["year"] else "")
        for au in authors:
            if not isinstance(au, dict):
                continue
            given = str(au.get("given") or "").strip()
            family = str(au.get("family") or "").strip()
            if not (given or family):
                continue
            key = norm(f"{family} {given}")
            s = stats_dict.setdefault(key, {
                "name": f"{given} {family}".strip()[:200],
                "first": None, "last": None, "n": 0, "journals": set(),
            })
            if pd:
                s["first"] = pd if (s["first"] is None or pd < s["first"]) else s["first"]
                s["last"] = pd if (s["last"] is None or pd > s["last"]) else s["last"]
            s["n"] += 1
            if r["journal_title"]:
                s["journals"].add(r["journal_title"])
    for key, s in stats_dict.items():
        conn.execute(
            "INSERT INTO author_stats (author_key, name, first_pub_date, last_pub_date, n, journals)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (key, s["name"], s["first"], s["last"], s["n"],
             json.dumps(sorted(s["journals"])[:12], ensure_ascii=False)),
        )
    conn.commit()
