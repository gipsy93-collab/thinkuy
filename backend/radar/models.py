"""Modelos de datos tipados (Pydantic v2) para Thinkuy.

Define los contratos formales para Artículos, Protocolos PRISMA, Decisiones de Cribado,
Data Charting JBI PCC y Payloads de la API REST.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class Author(BaseModel):
    """Representación normalizada de un autor o coautor."""
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    family: Optional[str] = None
    given: Optional[str] = None
    orcid: Optional[str] = None
    affiliation: Optional[str] = None

    @classmethod
    def from_any(cls, val: Any) -> Author:
        if isinstance(val, Author):
            return val
        if isinstance(val, dict):
            return cls(**val)
        if isinstance(val, str):
            return cls(name=val.strip())
        return cls()


class Article(BaseModel):
    """Modelo canónico de un artículo indexado en el radar o devuelto por la sonda federada."""
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    doi: Optional[str] = None
    title: str
    title_alt: Optional[str] = None
    abstract: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    authors: List[Union[Dict[str, Any], str]] = Field(default_factory=list)
    journal_id: Optional[int] = None
    journal_title: Optional[str] = None
    issn: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    year: Optional[int] = None
    pub_date: Optional[str] = None
    lang: Optional[str] = None
    url: Optional[str] = None
    source: str = "unknown"
    source_id: Optional[str] = None
    access: str = "unknown"
    cited_by: int = 0
    openalex_id: Optional[str] = None
    referenced_ids: List[str] = Field(default_factory=list)
    anchor_ids: List[Any] = Field(default_factory=list)
    cites_anchor: List[Any] = Field(default_factory=list)
    pdf_url: Optional[str] = None
    oa_status: Optional[str] = None
    s2_paper_id: Optional[str] = None
    s2_cited_by: int = 0
    s2_references: List[Any] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # Campos computados / dinámicos opcionales
    display_keywords: Optional[List[str]] = None
    keyword_source: Optional[str] = None
    conversation: Optional[Dict[str, Any]] = None
    match_score: Optional[float] = None
    relevance_score: Optional[float] = None
    charting: Optional[Dict[str, Any]] = None

    @classmethod
    def from_row(cls, row: Any) -> Article:
        """Construye un Article a partir de un sqlite3.Row o diccionario."""
        d = dict(row)
        for k in ("keywords", "authors", "referenced_ids", "anchor_ids", "cites_anchor", "s2_references"):
            val = d.get(k)
            if isinstance(val, str):
                try:
                    d[k] = json.loads(val or "[]")
                except (json.JSONDecodeError, TypeError):
                    d[k] = []
            elif not isinstance(val, (list, tuple, set)):
                d[k] = []
        return cls(**d)

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a dict compatible con el formato interno esperado."""
        d = self.model_dump(exclude_none=False)
        d["referenced_works"] = self.referenced_ids
        return d


class ReviewProtocol(BaseModel):
    """Protocolo de revisión sistemática / scoping review (PRISMA-ScR / JBI)."""
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    title: str
    research_question: Optional[str] = None
    framework: str = "PICO"  # PICO o PCC
    inclusion_criteria: List[str] = Field(default_factory=list)
    exclusion_criteria: List[str] = Field(default_factory=list)
    target_disciplines: List[str] = Field(default_factory=list)
    date_from: Optional[int] = None
    date_to: Optional[int] = None
    seed_dois: List[str] = Field(default_factory=list)
    status: Literal["draft", "active", "completed", "archived"] = "draft"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ScreeningDecision(BaseModel):
    """Decisión de screening individual sobre un artículo."""
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    protocol_id: int
    article_id: Optional[int] = None
    doi: str
    decision: Literal["included", "excluded", "doubtful", "pending"]
    reason: Optional[str] = None
    screened_by: str = "researcher"
    created_at: Optional[str] = None


class ChartingData(BaseModel):
    """Matriz estructurada de extracción de datos JBI PCC (Población, Concepto, Contexto)."""
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    protocol_id: int
    article_id: Optional[int] = None
    doi: str
    population: Optional[str] = None
    concept: Optional[str] = None
    context: Optional[str] = None
    methodology: Optional[str] = None
    key_findings: Optional[str] = None
    limitations: Optional[str] = None
    quality_score: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------- Request Payloads
class LibrarianAssistRequest(BaseModel):
    """Payload para POST /api/librarian/assist."""
    model_config = ConfigDict(extra="ignore")

    inquiry: str = Field(..., min_length=1, description="Pregunta de investigación en lenguaje natural")
    source: Literal["live", "local"] = "live"
    limit: int = Field(50, ge=1, le=150)
    days: int = Field(3650, ge=1)
    field_id: Optional[str] = None


class ProtocolCreateRequest(BaseModel):
    """Payload para POST /api/review/protocol."""
    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=1)
    research_question: Optional[str] = None
    framework: str = "PICO"
    inclusion_criteria: List[str] = Field(default_factory=list)
    exclusion_criteria: List[str] = Field(default_factory=list)
    target_disciplines: List[str] = Field(default_factory=list)
    date_from: Optional[int] = None
    date_to: Optional[int] = None
    seed_dois: List[str] = Field(default_factory=list)
    status: Literal["draft", "active", "completed", "archived"] = "draft"


class ScreeningDecisionRequest(BaseModel):
    """Payload para POST /api/review/protocol/{protocol_id}/screen."""
    model_config = ConfigDict(extra="ignore")

    doi: str = Field(..., min_length=1)
    decision: Literal["included", "excluded", "doubtful", "pending"]
    reason: Optional[str] = None
    screened_by: str = "researcher"


class ChartingSaveRequest(BaseModel):
    """Payload para POST /api/review/protocol/{protocol_id}/chart."""
    model_config = ConfigDict(extra="ignore")

    doi: str = Field(..., min_length=1)
    population: Optional[str] = None
    concept: Optional[str] = None
    context: Optional[str] = None
    methodology: Optional[str] = None
    key_findings: Optional[str] = None
    limitations: Optional[str] = None
    quality_score: Optional[float] = None
    notes: Optional[str] = None


class BackfillAutoRequest(BaseModel):
    """Payload para POST /api/fulltext/backfill-auto."""
    model_config = ConfigDict(extra="ignore")

    protocol_id: Optional[int] = None
    limit: int = Field(10, ge=1, le=50)
