"""Modelo de artículo del pipeline + utilidades de fuentes."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Article:
    title: str
    source: str
    doi: str | None = None
    title_alt: str | None = None
    abstract: str | None = None
    keywords: list = field(default_factory=list)
    authors: list = field(default_factory=list)
    journal_title: str | None = None
    issn: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    year: int | None = None
    pub_date: str | None = None
    lang: str | None = None
    url: str | None = None
    source_id: str | None = None
    access: str = "unknown"
    cited_by: int | None = None
    openalex_id: str | None = None
    referenced_ids: list = field(default_factory=list)
    anchor_ids: list = field(default_factory=list)
    cites_anchor: list = field(default_factory=list)
    pdf_url: str | None = None
    oa_status: str | None = None
    s2_paper_id: str | None = None
    s2_cited_by: int | None = None
    s2_reference_count: int | None = None
    s2_abstract: str | None = None
    s2_references: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def db_row(self) -> dict:
        return self.to_dict()


class SourceUnavailable(RuntimeError):
    """La fuente quedó inaccesible (p. ej. Redalyc con 503). Se registra y continúa."""