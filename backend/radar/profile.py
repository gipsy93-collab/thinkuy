"""Perfil de campo (FieldProfile) de Thinkuy: configuración por disciplina.

Cada perfil es un JSON en `config.PROFILES_DIR/<id>.json` que describe cómo se
descubre, cosecha, indexa y explica un campo de conocimiento. El perfil activo
se elige con la variable de entorno `THINKUY_FIELD`.

**Por defecto el perfil es `general` (neutro y multidisciplinar)**: la herramienta no debe
dar prioridad a ninguna disciplina. Un perfil de campo es una decisión explícita del
investigador, no un sesgo de fábrica. Un id sin archivo produce un perfil vacío, que
equivale a «sin filtro de campo».
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config

# ---------------------------------------------------------------- carga


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _default_profile(field_id: str) -> dict:
    return {
        "id": field_id,
        "name": "Campo de conocimiento",
        "languages": ["es", "pt", "en"],
        "collections": [],
        "discovery_terms": [],
        "seed_journals": [],
        "anchors": [],
        "cfps": [],
        "editorial_axes": [],
        "common_vocab": [],
        "token_equivalences": [],
        "word_variant_groups": [],
        "topics": [],
        "socratic_templates": {},
        "author_boost_terms": [],
        "author_fallback_tokens": [],
        "ubiquitous_terms": [],
        "thesaurus": [],
        "ui_texts": {"product": "Thinkuy", "field": "Campo de conocimiento"},
        "llm": {"enabled": False, "model": "", "api_base": ""},
    }


# ---------------------------------------------------------------- modelo


@dataclass
class FieldProfile:
    id: str
    name: str
    languages: list = field(default_factory=list)
    collections: list = field(default_factory=list)
    discovery_terms: list = field(default_factory=list)
    seed_journals: list = field(default_factory=list)
    anchors: list = field(default_factory=list)
    cfps: list = field(default_factory=list)
    editorial_axes: list = field(default_factory=list)
    common_vocab: list = field(default_factory=list)
    token_equivalences: list = field(default_factory=list)
    word_variant_groups: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    socratic_templates: dict = field(default_factory=dict)
    author_boost_terms: list = field(default_factory=list)
    author_fallback_tokens: list = field(default_factory=list)
    # Términos omnipresentes DEL CAMPO (p. ej. «comunicación» en el perfil de comunicación):
    # no sirven como descriptores de búsqueda porque saturan. Viven en el perfil, no en el
    # código, para que el modo neutro no descarte palabras de ninguna disciplina.
    ubiquitous_terms: list = field(default_factory=list)
    # Tesauro del campo (SKOS simplificado): vocabulario controlado con relaciones. Ver
    # `radar/thesaurus.py`. Se construye sobre vocabulario EXISTENTE (UNESCO, Latindex,
    # OpenAlex topics, Wikidata), nunca inventado desde cero.
    thesaurus: list = field(default_factory=list)
    ui_texts: dict = field(default_factory=dict)
    llm: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "FieldProfile":
        base = cls(
            id=str(data.get("id") or "generic"),
            name=str(data.get("name") or "Campo de conocimiento"),
        )
        for k, v in data.items():
            if k in cls.__dataclass_fields__ and k not in ("id", "name", "raw"):
                setattr(base, k, v)
        base.raw = data
        return base

    @property
    def product_name(self) -> str:
        return (self.ui_texts or {}).get("product") or "Thinkuy"

    @property
    def field_label(self) -> str:
        return (self.ui_texts or {}).get("field") or self.name

    def anchor_keys(self) -> list[str]:
        return [a.get("key") for a in (self.anchors or []) if a.get("key")]

    def first_cfp(self) -> dict | None:
        return self.cfps[0] if self.cfps else None


# ---------------------------------------------------------------- carga pública

def load_profile(field_id: str | None = None) -> FieldProfile:
    field_id = (field_id or config.THINKUY_FIELD).strip().lower()
    path = config.PROFILES_DIR / f"{field_id}.json"
    data = _default_profile(field_id)
    if path.exists():
        loaded = _load_json(path)
        data.update(loaded)
        data["id"] = field_id
    # Sincronizar vocabulario morfológico extra (grupos de variantes del campo)
    try:
        from . import normalize
        normalize.EXTRA_VARIANT_GROUPS = [
            frozenset(g) for g in data.get("word_variant_groups") or []
        ]
    except Exception:
        pass
    return FieldProfile.from_dict(data)


# Singleton del perfil activo (cargado una vez; controlado por THINKUY_FIELD)
field_profile = load_profile()


def reload(field_id: str | None = None) -> FieldProfile:
    """Recarga el perfil activo en runtime y refresca los módulos dependientes.

    Permite servir varios campos desde el mismo proceso (usado por /api/field/set).
    Los módulos que cachean constantes del perfil a nivel de módulo se actualizan aquí.
    """
    global field_profile
    field_profile = load_profile(field_id)
    try:
        from . import matching, socratic
        matching.configure(field_profile.common_vocab, field_profile.token_equivalences)
        socratic.configure(field_profile.socratic_templates)
    except Exception:
        pass
    try:
        from .harvester import scielo
        scielo.configure(field_profile.collections, field_profile.discovery_terms)
    except Exception:
        pass
    return field_profile


def available_fields() -> list[str]:
    """Perfiles disponibles en PROFILES_DIR (sin extensión)."""
    if not config.PROFILES_DIR.exists():
        return []
    return sorted(p.stem for p in config.PROFILES_DIR.glob("*.json") if not p.stem.endswith("_seed"))