"""Lista semilla de revistas del campo (desde el perfil de campo activo).

El MVP arranca con esta red curada (~70 revistas) y se AUTO-EXPANDE en cada
cosecha con el descubrimiento de revistas en SciELO (por área temática del perfil)
y con nuevos ISSN detectados vía Crossref. La meta de 300+ revistas se alcanza
de forma incremental. Fuentes de referencia: SciELO, Redalyc, Latindex, MIAR, DOAJ.
"""
from ..profile import field_profile

SEED_JOURNALS: list[dict] = list(field_profile.seed_journals or [])