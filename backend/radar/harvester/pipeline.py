"""Orquestador de cosecha: semilla -> descubrimiento SciELO -> Crossref -> SciELO -> Redalyc."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

from .. import config, db, profile, quality
from . import core, crossref, europepmc, latindex, openalex, redalyc, scielo, semanticscholar, unpaywall
from .journals_seed import SEED_JOURNALS

log = logging.getLogger("radar.pipeline")


def _new_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": config.USER_AGENT},
        follow_redirects=True,
        timeout=45.0,
    )


def run_pipeline(sources: list[str] | None = None,
                 days: int | None = None,
                 max_articles: int | None = None,
                 collections: list[str] | None = None,
                 http: httpx.Client | None = None) -> dict:
    sources = [s.strip().lower() for s in (sources or ["seed", "scielo", "latindex", "latindex_articles", "crossref", "openalex", "redalyc", "enrich"])]
    days = days or config.DEFAULT_DAYS
    limit = max_articles or config.MAX_ARTICLES_PER_RUN
    today = date.today()
    date_from = (today - timedelta(days=days)).isoformat()
    date_to = today.isoformat()

    conn = db.connect()
    db.init_db(conn)
    close_http = http is None
    http = http or _new_client()

    report: dict = {"date_from": date_from, "date_to": date_to, "sources": {}, "journals": 0, "articles": 0, "new": 0}

    try:
        # 1) Red semilla curada del perfil
        if "seed" in sources:
            n = 0
            for j in SEED_JOURNALS:
                db.upsert_journal(conn, {**j, "source": "seed", "auto_discovered": False})
                n += 1
            report["sources"]["seed"] = {"status": "ok", "journals_seeded": n}
            log.info("Semilla: %d revistas", n)

        journals = db.all_journals(conn)

        # 2) Descubrimiento automático de revistas del campo en SciELO
        if "scielo" in sources:
            try:
                discovered = scielo.discover_journals(http, collections=collections)
                for j in discovered:
                    db.upsert_journal(conn, j)
                report["sources"]["scielo_discovery"] = {"status": "ok", "journals_found": len(discovered)}
                journals = db.all_journals(conn)
                log.info("Descubrimiento SciELO: %d revistas del campo", len(discovered))
            except Exception as e:
                report["sources"]["scielo_discovery"] = {"status": "error", "detail": str(e)}
                log.warning("Descubrimiento SciELO falló: %s", e)

        budget = max(20, limit // max(len(journals), 1))

        # 2.5) Latindex Catálogo 2.0: descubre revistas del campo (solo en línea
        # y calificadas). Aporta ISSN para que Crossref/OpenAlex cosechen artículos.
        if "latindex" in sources:
            try:
                lat_found = latindex.discover_journals(http)
                n_lat = 0
                for j in lat_found:
                    db.upsert_journal(conn, j)
                    n_lat += 1
                db.log_harvest(conn, "latindex", "ok", 0, 0,
                               f"revistas_cat2={n_lat}")
                report["sources"]["latindex"] = {"status": "ok",
                                                 "journals_found": n_lat}
                journals = db.all_journals(conn)
                log.info("Latindex Catálogo 2.0: %d revistas del campo", n_lat)
            except Exception as e:
                report["sources"]["latindex"] = {"status": "error", "detail": str(e)}
                log.warning("Latindex: %s", e)

        # 2.6) Latindex Descubridor de Artículos: cosecha artículos de revistas
        # certificadas en el Catálogo 2.0 (calidad contrastada). Complementa y
        # enriquece el catálogo con enlaces a texto completo en OJS.
        if "latindex_articles" in sources:
            try:
                lat_arts = latindex.discover_articles(
                    http, max_articles=max(60, min(600, limit // 2)))
                n_lat_arts = n_lat_new = 0
                for a in lat_arts:
                    if a.doi:
                        status, _ = db.upsert_article(conn, a.db_row())
                        n_lat_arts += 1
                        if status == "new":
                            n_lat_new += 1
                    elif a.source_id:
                        exists = conn.execute(
                            "SELECT 1 FROM articles WHERE source = 'latindex' AND source_id = ?",
                            (a.source_id,),
                        ).fetchone()
                        if exists:
                            continue
                        status, _ = db.upsert_article(conn, a.db_row())
                        n_lat_arts += 1
                        if status == "new":
                            n_lat_new += 1
                db.log_harvest(conn, "latindex_articles", "ok",
                               n_lat_arts, n_lat_new)
                report["sources"]["latindex_articles"] = {"status": "ok",
                                                          "found": n_lat_arts,
                                                          "new": n_lat_new}
                log.info("Latindex Descubridor: %d artículos (%d nuevos)",
                         n_lat_arts, n_lat_new)
            except Exception as e:
                report["sources"]["latindex_articles"] = {"status": "error",
                                                          "detail": str(e)}
                log.warning("Latindex artículos: %s", e)

        # 3) Crossref por ISSN (impreso + online)
        if "crossref" in sources:
            found = new = 0
            errors = 0
            for j in journals:
                issns = scielo._valid_issns([x for x in (j.get("issn_print"), j.get("issn_online")) if x])
                for issn in issns:
                    try:
                        arts = crossref.harvest_by_issn(http, issn, date_from,
                                                        max_articles=min(budget, 60))
                        for a in arts:
                            status, _ = db.upsert_article(conn, a.db_row())
                            found += 1
                            if status == "new":
                                new += 1
                    except Exception as e:
                        errors += 1
                        log.warning("Crossref %s: %s", issn, e)
            db.log_harvest(conn, "crossref", "ok", found, new,
                           f"revistas={len(journals)} errores={errors}")
            report["sources"]["crossref"] = {"status": "ok", "found": found, "new": new, "errors": errors}
            log.info("Crossref: %d artículos (%d nuevos)", found, new)

        # 4) OpenAlex por ISSN (antes que SciELO: si hay DOI duplicado,
        #    gana el registro rico de SciELO con keywords/abstract por idioma)
        if "openalex" in sources:
            found = new = 0
            errors = 0
            issn_set: set[str] = set()
            for j in journals:
                for x in (j.get("issn_print"), j.get("issn_online")):
                    if x:
                        issn_set.add(x)
            batches = [sorted(issn_set)[i:i + 8] for i in range(0, len(issn_set), 8)]
            for batch in batches:
                try:
                    arts = openalex.harvest_issns(http, batch, date_from,
                                                  max_articles=min(budget * 2, 150))
                    for a in arts:
                        if not a.doi:
                            continue
                        status, _ = db.upsert_article(conn, a.db_row())
                        found += 1
                        if status == "new":
                            new += 1
                except Exception as e:
                    errors += 1
                    log.warning("OpenAlex lote: %s", e)
            db.log_harvest(conn, "openalex", "ok", found, new,
                           f"revistas={len(journals)} lotes={len(batches)} errores={errors}")
            report["sources"]["openalex"] = {"status": "ok", "found": found, "new": new, "errors": errors}
            log.info("OpenAlex: %d artículos (%d nuevos)", found, new)

        # 5) SciELO por revista (ISSN + colección), solo artículos de investigación
        if "scielo" in sources:
            found = new = 0
            errors = 0
            sci_journals = [
                j for j in journals
                if j.get("collection") and scielo._valid_issns([x for x in (j.get("issn_print"), j.get("issn_online")) if x])
            ]
            for j in sci_journals:
                issn = scielo._valid_issns([x for x in (j.get("issn_print"), j.get("issn_online")) if x])[0]
                try:
                    arts = scielo.harvest_journal(http, j["collection"], issn,
                                                  date_from, date_to,
                                                  max_articles=min(budget, 15))
                    for a in arts:
                        # Dedupe para artículos sin DOI: (source, source_id) ya existe
                        if a.source_id:
                            exists = conn.execute(
                                "SELECT 1 FROM articles WHERE source = 'scielo' AND source_id = ?",
                                (a.source_id,),
                            ).fetchone()
                            if exists:
                                continue
                        status, _ = db.upsert_article(conn, a.db_row())
                        found += 1
                        if status == "new":
                            new += 1
                except Exception as e:
                    errors += 1
                    log.warning("SciELO %s/%s: %s", j.get("collection"), issn, e)
            db.log_harvest(conn, "scielo", "ok", found, new,
                           f"revistas={len(sci_journals)} errores={errors}")
            report["sources"]["scielo"] = {"status": "ok", "found": found, "new": new, "errors": errors}
            log.info("SciELO: %d artículos (%d nuevos)", found, new)

        # 6) Redalyc vía OAI-PMH (UAEMex / Redalyc)
        if "redalyc" in sources:
            try:
                journal_issns = []
                for j in journals:
                    for i in (j.get("issn_print"), j.get("issn_online")):
                        if i and scielo._ISSN_RE.match(i.strip()):
                            journal_issns.append(i.strip().upper())
                arts = redalyc.harvest(http, date_from, max_articles=min(limit, 300), sets=journal_issns[:50])
                found = new = 0
                for a in arts:
                    if not a.doi and not a.source_id:
                        continue
                    if not a.doi and a.source_id:
                        exists = conn.execute(
                            "SELECT 1 FROM articles WHERE source = 'redalyc' AND source_id = ?",
                            (a.source_id,),
                        ).fetchone()
                        if exists:
                            continue
                    status, _ = db.upsert_article(conn, a.db_row())
                    found += 1
                    if status == "new":
                        new += 1
                db.log_harvest(conn, "redalyc", "ok", found, new, f"artículos={found} nuevos={new}")
                report["sources"]["redalyc"] = {"status": "ok", "found": found, "new": new}
            except Exception as e:
                db.log_harvest(conn, "redalyc", "error", 0, 0, str(e))
                report["sources"]["redalyc"] = {"status": "error", "detail": str(e)}
                log.warning("Redalyc: %s", e)

        # 7) CORE: búsqueda por ejes/keywords del campo (requiere CORE_API_KEY)
        if "core" in sources:
            if not core.available():
                report["sources"]["core"] = {"status": "no_key", "detail": "CORE_API_KEY no configurada"}
            else:
                try:
                    found = 0
                    queries = [profile.field_profile.editorial_axes[0]] if profile.field_profile.editorial_axes else []
                    for f in profile.field_profile.topics[:3]:
                        if f.get("keywords_es"):
                            queries.append(f["keywords_es"][0])
                    for q in queries:
                        for a in core.search(http, q, limit=20, date_from=date_from):
                            row = a.db_row()
                            if row.get("doi"):
                                status, _ = db.upsert_article(conn, row)
                                if status == "new":
                                    found += 1
                    db.log_harvest(conn, "core", "ok", found, found)
                    report["sources"]["core"] = {"status": "ok", "found": found}
                except Exception as e:
                    report["sources"]["core"] = {"status": "error", "detail": str(e)}
                    log.warning("CORE: %s", e)

        # 8) Europe PMC: búsqueda por keywords del campo + textos OA
        if "europepmc" in sources:
            try:
                found = 0
                queries = []
                for f in profile.field_profile.topics[:3]:
                    if f.get("keywords_es"):
                        queries.append(f["keywords_es"][0])
                for q in queries:
                    for a in europepmc.search(http, q, limit=30, date_from=date_from):
                        row = a.db_row()
                        if row.get("doi"):
                            status, _ = db.upsert_article(conn, row)
                            if status == "new":
                                found += 1
                db.log_harvest(conn, "europepmc", "ok", found, found)
                report["sources"]["europepmc"] = {"status": "ok", "found": found}
            except Exception as e:
                report["sources"]["europepmc"] = {"status": "error", "detail": str(e)}
                log.warning("Europe PMC: %s", e)

        # 9) Enriquecimiento: Unpaywall (OA/PDF) + Semantic Scholar (citas/referencias)
        if "enrich" in sources:
            try:
                enrich_report = {"unpaywall": 0, "semanticscholar": 0}
                rows = conn.execute(
                    "SELECT * FROM articles WHERE doi IS NOT NULL ORDER BY cited_by DESC LIMIT ?",
                    (min(120, limit),),
                ).fetchall()
                cands = [db._row_to_article(r) for r in rows]
                for a in unpaywall.enrich_articles(http, cands, limit=min(100, limit)):
                    db.upsert_article(conn, a)
                    enrich_report["unpaywall"] += 1
                for a in semanticscholar.enrich_articles(http, cands, limit=min(100, limit)):
                    db.upsert_article(conn, a)
                    enrich_report["semanticscholar"] += 1
                db.log_harvest(conn, "enrich", "ok",
                               enrich_report["unpaywall"] + enrich_report["semanticscholar"], 0)
                report["sources"]["enrich"] = {"status": "ok", **enrich_report}
                log.info("Enriquecimiento: %s", enrich_report)
            except Exception as e:
                report["sources"]["enrich"] = {"status": "error", "detail": str(e)}
                log.warning("Enriquecimiento falló: %s", e)

        st = db.stats(conn)
        report["journals"] = st["journals"]
        report["articles"] = st["articles"]
        report["by_source"] = st["by_source"]
        # Índices derivados: keywords (autocompletado) y autorías (emergentes)
        db.rebuild_keywords(conn)
        db.rebuild_author_stats(conn)
        report["anchor_signals"] = db.rebuild_anchor_signals(conn)
        # Calidad editorial: cuartil SJR de las revistas (si hay índice SJR local)
        try:
            report["quality_classified"] = quality.enrich_journals(conn)
        except Exception as e:
            report["quality_classified"] = 0
            log.warning("Calidad SJR: %s", e)
        return report
    finally:
        if close_http:
            http.close()
        conn.close()