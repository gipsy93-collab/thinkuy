# -*- coding: utf-8 -*-
"""Subpaquete SCIVIS — Auditoría Cibermétrica y Editorial 100% Verificada.

Re-exporta todas las funciones, constantes y clases públicas para preservar
compatibilidad total con cualquier módulo que importe `radar.scivis`.
"""
from __future__ import annotations

from .common import (
    CC_AUDIT_TTL_HOURS,
    CC_DOMAIN_RANKS_DB,
    CC_HISTORY_DIR,
    CC_INLINKS_DB,
    CC_PUBLIC_SUFFIXES,
    CC_RANKS_GZ,
    CC_RELEASE_ID,
    KNOWN_JOURNAL_DOMAINS,
    MEGA_HUB_DOMAINS,
    WEB_TWINS_RELEASE,
    norm,
    edit_distance,
    unescape,
    log,
    _get_db_conn,
    _clean_domain,
    _split_url_scope,
    _url_matches_scope,
    _journal_identity_from_url,
    _n_es,
    _otras_citas_frase,
    _is_portal_host,
    _is_public_suffix,
    _domain_candidates,
    _cc_total_domains,
    _get_proximity_radius,
    _iter_history_releases,
)

from .commoncrawl import (
    get_latest_common_crawl_collection,
    query_common_crawl_domain_real,
    get_common_crawl_harmonic_centrality,
    get_cc_history_trajectory,
    get_real_referrers,
)

from .links import (
    build_conversational_web_graph_analysis,
    build_web_proximity_radar,
    compute_web_twins,
    discover_transmedia_channels,
    audit_in_out_links,
)

from .resolution import (
    _resolve_journal_domain_openalex,
    _detect_shared_host,
    _probe_url_for_journal_meta,
    resolve_journal_domain_and_meta,
)

from .editorial import (
    get_local_catalog_metrics,
    get_dominant_and_emerging_topics,
    find_editors_and_reviewers,
    get_competitor_benchmarking,
    audit_journal_ecosystem,
    get_scivis_ranking,
)
