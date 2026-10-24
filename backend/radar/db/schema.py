"""Esquema DDL e inicialización / migraciones incrementales de SQLite."""
from __future__ import annotations

import sqlite3

from ..normalize import norm

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    issn_print    TEXT,
    issn_online   TEXT,
    country       TEXT,
    source        TEXT NOT NULL DEFAULT 'seed',
    collection    TEXT,
    subject_areas TEXT,
    auto_discovered INTEGER DEFAULT 0,
    last_harvest  TEXT,
    sjr           REAL,
    quartile      TEXT,
    UNIQUE(title)
);
CREATE INDEX IF NOT EXISTS idx_journals_issn_print  ON journals(issn_print);
CREATE INDEX IF NOT EXISTS idx_journals_issn_online ON journals(issn_online);

CREATE TABLE IF NOT EXISTS anchors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT UNIQUE NOT NULL,
    label       TEXT NOT NULL,
    issns       TEXT,
    doi_prefix  TEXT,
    title_terms TEXT,
    field       TEXT,
    active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doi           TEXT UNIQUE,
    title         TEXT NOT NULL,
    title_alt     TEXT,
    abstract      TEXT,
    keywords      TEXT,
    authors       TEXT,
    journal_id    INTEGER,
    journal_title TEXT,
    issn          TEXT,
    volume        TEXT,
    issue         TEXT,
    pages         TEXT,
    year          INTEGER,
    pub_date      TEXT,
    lang          TEXT,
    url           TEXT,
    source        TEXT NOT NULL,
    source_id     TEXT,
    access        TEXT DEFAULT 'unknown',
    cited_by      INTEGER DEFAULT 0,
    openalex_id   TEXT,
    referenced_ids TEXT,
    anchor_ids    TEXT,
    cites_anchor  TEXT,
    pdf_url       TEXT,
    oa_status     TEXT,
    s2_paper_id   TEXT,
    s2_cited_by   INTEGER DEFAULT 0,
    s2_references TEXT,
    created_at    TEXT,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_pubdate ON articles(pub_date);
CREATE INDEX IF NOT EXISTS idx_articles_year    ON articles(year);
CREATE INDEX IF NOT EXISTS idx_articles_doi     ON articles(doi);
CREATE INDEX IF NOT EXISTS idx_articles_journal ON articles(journal_id);

CREATE TABLE IF NOT EXISTS harvest_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    status         TEXT,
    articles_found INTEGER,
    articles_new   INTEGER,
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS keywords_flat (
    kw      TEXT PRIMARY KEY,
    norm_kw TEXT,
    n       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_keywords_flat_n  ON keywords_flat(n);
CREATE INDEX IF NOT EXISTS idx_articles_cited   ON articles(cited_by DESC, pub_date DESC);

CREATE TABLE IF NOT EXISTS watch_keywords (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    label        TEXT,
    keywords     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_seen_id INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS author_stats (
    author_key     TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    first_pub_date TEXT,
    last_pub_date  TEXT,
    n              INTEGER DEFAULT 0,
    journals       TEXT
);
CREATE INDEX IF NOT EXISTS idx_author_stats_first ON author_stats(first_pub_date);
CREATE INDEX IF NOT EXISTS idx_author_stats_n ON author_stats(n);

CREATE TABLE IF NOT EXISTS article_fulltext (
    doi           TEXT PRIMARY KEY,
    markdown_text TEXT NOT NULL,
    sections_json TEXT,
    word_count    INTEGER,
    page_count    INTEGER,
    extracted_at  TEXT
);

CREATE TABLE IF NOT EXISTS citation_contexts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    citing_doi   TEXT NOT NULL,
    cited_doi    TEXT NOT NULL,
    paragraph    TEXT NOT NULL,
    sentence     TEXT NOT NULL,
    sentiment    TEXT,
    section      TEXT,
    context_type TEXT,
    claim_text   TEXT,
    confidence   TEXT,
    validation_status TEXT DEFAULT 'pending',
    validated_by TEXT,
    validated_at TEXT,
    created_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_cit_ctx_citing ON citation_contexts(citing_doi);
CREATE INDEX IF NOT EXISTS idx_cit_ctx_cited  ON citation_contexts(cited_doi);
/* NOTA: idx_cit_ctx_status se crea en init_db tras la migración de columnas,
   porque en bases existentes la columna aún no existe al correr _SCHEMA. */

CREATE TABLE IF NOT EXISTS review_protocols (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id           TEXT DEFAULT 'default',
    title              TEXT NOT NULL,
    research_question  TEXT,
    framework          TEXT DEFAULT 'PICO',
    inclusion_criteria TEXT,
    exclusion_criteria TEXT,
    target_disciplines TEXT,
    date_from          INTEGER,
    date_to            INTEGER,
    seed_dois          TEXT,
    status             TEXT DEFAULT 'draft',
    created_at         TEXT,
    updated_at         TEXT
);

CREATE TABLE IF NOT EXISTS article_screenings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id        TEXT DEFAULT 'default',
    protocol_id     INTEGER NOT NULL,
    article_id      INTEGER,
    doi             TEXT,
    decision        TEXT NOT NULL DEFAULT 'pending',
    reason          TEXT,
    screened_by     TEXT DEFAULT 'researcher',
    stage           TEXT DEFAULT 'title_abstract',
    created_at      TEXT,
    UNIQUE(protocol_id, doi, stage)
);
CREATE INDEX IF NOT EXISTS idx_screenings_proto ON article_screenings(protocol_id);
CREATE INDEX IF NOT EXISTS idx_screenings_doi   ON article_screenings(doi);

CREATE TABLE IF NOT EXISTS charting_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id        TEXT DEFAULT 'default',
    protocol_id     INTEGER NOT NULL,
    article_id      INTEGER,
    doi             TEXT,
    population      TEXT,
    concept         TEXT,
    context         TEXT,
    methodology     TEXT,
    key_findings    TEXT,
    limitations     TEXT,
    quality_score   REAL,
    notes           TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    UNIQUE(protocol_id, doi)
);
CREATE INDEX IF NOT EXISTS idx_charting_proto ON charting_data(protocol_id);

CREATE TABLE IF NOT EXISTS protocol_searches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id            TEXT DEFAULT 'default',
    protocol_id         INTEGER NOT NULL,
    source              TEXT NOT NULL,
    query               TEXT,
    year_from           INTEGER,
    year_to             INTEGER,
    records_identified  INTEGER NOT NULL DEFAULT 0,
    searched_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_protocol_searches_proto ON protocol_searches(protocol_id);
"""


def _migrate_screening_links(conn: sqlite3.Connection) -> None:
    """Normaliza los DOI y enlaza cada cribado con su artículo por clave primaria."""
    # 1) DOI normalizados a minúsculas. **No destructivo**: si bajar una fila chocaría con el
    #    `UNIQUE(doi)` de otra que ya está en minúsculas (caso real medido 22-09-2026:
    #    `openalex:W7117640167` y `openalex:w7117640167`), esa fila se deja como está. Antes el
    #    UPDATE lanzaba `IntegrityError` —que NO es `OperationalError`— y **abortaba init_db**.
    try:
        conn.execute(
            """UPDATE articles SET doi = LOWER(doi)
                WHERE doi IS NOT NULL AND doi != LOWER(doi)
                  AND NOT EXISTS (
                      SELECT 1 FROM articles a2
                       WHERE a2.doi = LOWER(articles.doi) AND a2.id != articles.id)"""
        )
    except sqlite3.Error:
        pass
    # 2) Cribados sin artículo, resueltos por DOI directo (ya normalizado en ambos lados).
    try:
        conn.execute(
            """UPDATE article_screenings
                  SET article_id = (SELECT a.id FROM articles a WHERE a.doi = article_screenings.doi)
                WHERE (article_id IS NULL OR article_id <= 0)
                  AND doi IS NOT NULL AND doi != '' AND doi NOT LIKE 'article:%'"""
        )
    except sqlite3.OperationalError:
        pass
    # 3) Cribados con el pseudo-DOI 'article:N'.
    try:
        conn.execute(
            """UPDATE article_screenings
                  SET article_id = CAST(SUBSTR(doi, 9) AS INTEGER)
                WHERE (article_id IS NULL OR article_id <= 0) AND doi LIKE 'article:%'
                  AND CAST(SUBSTR(doi, 9) AS INTEGER) IN (SELECT id FROM articles)"""
        )
    except sqlite3.OperationalError:
        pass


def _rebuild_screenings_unique_stage(conn: sqlite3.Connection) -> None:
    """Reconstruye `article_screenings` a UNIQUE(protocol_id, doi, stage) si aún es (protocol_id, doi).

    SQLite no permite alterar una restricción UNIQUE, así que hay que recrear la tabla. Se copian
    todas las filas: los cribados existentes quedan en `title_abstract` (no se pierde nada).
    """
    try:
        uniques = []
        for idx in conn.execute("PRAGMA index_list(article_screenings)").fetchall():
            if idx[3] == "u":  # columna `origin`: restricción UNIQUE
                info = conn.execute(f"PRAGMA index_info({idx[1]})").fetchall()
                uniques.append([r[2] for r in info])
        if not any(cols == ["protocol_id", "doi"] for cols in uniques):
            return  # ya migrada (o la tabla no existe todavía)
        conn.execute("ALTER TABLE article_screenings RENAME TO _article_screenings_old")
        conn.execute("""
            CREATE TABLE article_screenings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id        TEXT DEFAULT 'default',
                protocol_id     INTEGER NOT NULL,
                article_id      INTEGER,
                doi             TEXT,
                decision        TEXT NOT NULL DEFAULT 'pending',
                reason          TEXT,
                screened_by     TEXT DEFAULT 'researcher',
                stage           TEXT DEFAULT 'title_abstract',
                created_at      TEXT,
                UNIQUE(protocol_id, doi, stage)
            )
        """)
        conn.execute("""
            INSERT INTO article_screenings
                (id, owner_id, protocol_id, article_id, doi, decision, reason, screened_by, stage, created_at)
            SELECT id, owner_id, protocol_id, article_id, doi, decision, reason, screened_by,
                   COALESCE(stage, 'title_abstract'), created_at
            FROM _article_screenings_old
        """)
        conn.execute("DROP TABLE _article_screenings_old")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_screenings_proto ON article_screenings(protocol_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_screenings_doi   ON article_screenings(doi)")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    # Migración de calidad editorial (SJR/quartile) en revistas
    j_cols = {r[1] for r in conn.execute("PRAGMA table_info(journals)").fetchall()}
    for col, ddl in (("sjr", "REAL"), ("quartile", "TEXT")):
        if col not in j_cols:
            try:
                conn.execute(f"ALTER TABLE journals ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
    # Migraciones incrementales (base existente sin columnas nuevas)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()}
    for col, ddl in (
        ("cited_by", "INTEGER DEFAULT 0"),
        ("openalex_id", "TEXT"),
        ("referenced_ids", "TEXT"),
        ("anchor_ids", "TEXT"),
        ("cites_anchor", "TEXT"),
        ("pdf_url", "TEXT"),
        ("oa_status", "TEXT"),
        ("s2_paper_id", "TEXT"),
        ("s2_cited_by", "INTEGER DEFAULT 0"),
        ("s2_references", "TEXT"),
    ):
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_anchor ON articles(anchor_ids)")
    except sqlite3.OperationalError:
        pass
    # Migración: norm_kw en keywords_flat para autocompletado acentuado (DB-4)
    kf_cols = {r[1] for r in conn.execute("PRAGMA table_info(keywords_flat)").fetchall()}
    if "norm_kw" not in kf_cols:
        try:
            conn.execute("ALTER TABLE keywords_flat ADD COLUMN norm_kw TEXT")
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_keywords_flat_norm ON keywords_flat(norm_kw)")
        has_nulls = conn.execute("SELECT 1 FROM keywords_flat WHERE norm_kw IS NULL LIMIT 1").fetchone()
        if has_nulls:
            rows = conn.execute("SELECT kw FROM keywords_flat WHERE norm_kw IS NULL").fetchall()
            for r in rows:
                conn.execute("UPDATE keywords_flat SET norm_kw = ? WHERE kw = ?", (norm(r["kw"]), r["kw"]))
    except Exception:
        pass
    # FTS5 para autocompletado (opcional: si el binario de sqlite no lo incluye, no romper)
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS keywords_fts USING fts5(kw)")
    except sqlite3.OperationalError:
        pass
    # Tablas de texto completo, contextos de citación y protocolos de revisión (Fase 1 Epistémica)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS article_fulltext (
                doi           TEXT PRIMARY KEY,
                markdown_text TEXT NOT NULL,
                sections_json TEXT,
                word_count    INTEGER,
                page_count    INTEGER,
                extracted_at  TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS citation_contexts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                citing_doi   TEXT NOT NULL,
                cited_doi    TEXT NOT NULL,
                paragraph    TEXT NOT NULL,
                sentence     TEXT NOT NULL,
                sentiment    TEXT,
                section      TEXT,
                context_type TEXT,
                created_at   TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cit_ctx_citing ON citation_contexts(citing_doi)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cit_ctx_cited  ON citation_contexts(cited_doi)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cit_ctx_status ON citation_contexts(validation_status)")
    except sqlite3.OperationalError:
        pass
    # Migración: interpretación IA + validación humana en contextos existentes
    cc_cols = {r[1] for r in conn.execute("PRAGMA table_info(citation_contexts)").fetchall()}
    for col, ddl in (
        ("claim_text", "TEXT"),
        ("confidence", "TEXT"),
        ("validation_status", "TEXT DEFAULT 'pending'"),
        ("validated_by", "TEXT"),
        ("validated_at", "TEXT"),
    ):
        if col not in cc_cols:
            try:
                conn.execute(f"ALTER TABLE citation_contexts ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cit_ctx_status ON citation_contexts(validation_status)")
    except sqlite3.OperationalError:
        pass
    # Migración PRISMA: semillas y estado del protocolo en bases existentes
    rp_cols = {r[1] for r in conn.execute("PRAGMA table_info(review_protocols)").fetchall()}
    for col, ddl in (
        ("seed_dois", "TEXT"),
        ("status", "TEXT DEFAULT 'draft'"),
        ("updated_at", "TEXT"),
    ):
        if col not in rp_cols:
            try:
                conn.execute(f"ALTER TABLE review_protocols ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
    # Migración PRISMA Fase 2: tablas de screening y charting
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS article_screenings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                protocol_id     INTEGER NOT NULL,
                article_id      INTEGER,
                doi             TEXT,
                decision        TEXT NOT NULL DEFAULT 'pending',
                reason          TEXT,
                screened_by     TEXT DEFAULT 'researcher',
                stage           TEXT DEFAULT 'title_abstract',
                created_at      TEXT,
                UNIQUE(protocol_id, doi, stage)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_screenings_proto ON article_screenings(protocol_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_screenings_doi   ON article_screenings(doi)")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS charting_data (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                protocol_id     INTEGER NOT NULL,
                article_id      INTEGER,
                doi             TEXT,
                population      TEXT,
                concept         TEXT,
                context         TEXT,
                methodology     TEXT,
                key_findings    TEXT,
                limitations     TEXT,
                quality_score   REAL,
                notes           TEXT,
                created_at      TEXT,
                updated_at      TEXT,
                UNIQUE(protocol_id, doi)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_charting_proto ON charting_data(protocol_id)")
    except sqlite3.OperationalError:
        pass
    # Migración multiusuario: aislamiento con owner_id en tablas privadas
    for tbl in ("review_protocols", "article_screenings", "charting_data", "protocol_searches"):
        try:
            t_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
            if "owner_id" not in t_cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN owner_id TEXT DEFAULT 'default'")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_owner ON {tbl}(owner_id)")
        except sqlite3.OperationalError:
            pass
    # Migración PRISMA 2020: etapa del cribado (título/resumen vs texto completo). No destructiva:
    # los cribados existentes quedan en 'title_abstract' y su 'incluido' sigue siendo final.
    as_cols = {r[1] for r in conn.execute("PRAGMA table_info(article_screenings)").fetchall()}
    if "stage" not in as_cols:
        try:
            conn.execute("ALTER TABLE article_screenings ADD COLUMN stage TEXT DEFAULT 'title_abstract'")
        except sqlite3.OperationalError:
            pass
    _rebuild_screenings_unique_stage(conn)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_screenings_stage ON article_screenings(protocol_id, stage)")
    except sqlite3.OperationalError:
        pass
    _migrate_screening_links(conn)
    conn.commit()
