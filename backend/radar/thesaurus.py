"""Tesauro del campo: vocabulario controlado con relaciones, validado y con integridad.

**Decisión del IP (18-09-2026):** el tesauro se construye sobre **vocabulario ya existente**
(UNESCO, Latindex, OpenAlex topics, Wikidata), no inventado desde cero. Aquí vive la
**maquinaria**: el esquema, el validador y la expansión de consultas. El contenido del piloto
se carga en el perfil del campo elegido.

Esquema (SKOS simplificado) — una entrada por concepto::

    {
      "id": "miocarditis",
      "prefLabel": {"es": "miocarditis", "pt": "miocardite", "en": "myocarditis"},
      "altLabels": {"es": ["inflamación del miocardio"], "pt": [], "en": []},
      "broader": ["enfermedad cardiovascular"],
      "narrower": [],
      "related": ["insuficiencia cardíaca"],
      "note": "Alcance del término.",
      "source": "Wikidata Q186235 / DeCS"
    }

**Por qué validar y no confiar:** un tesauro sin integridad referencial introduce deriva
silenciosa en las búsquedas (`broader` que apunta a un id inexistente simplemente no expande
nada y nadie se entera). El validador lo declara. Y `source` es obligatorio en la práctica:
un término sin procedencia no es auditable.
"""
from __future__ import annotations

import logging

from .normalize import norm

log = logging.getLogger("radar.thesaurus")

IDIOMAS = ("es", "pt", "en")
RELACIONES = ("broader", "narrower", "related")


# ---------------------------------------------------------------- carga

def cargar(perfil=None) -> list[dict]:
    """Entradas del tesauro del perfil activo (lista vacía si el campo no tiene tesauro)."""
    if perfil is None:
        from . import profile as _profile
        perfil = _profile.field_profile
    entradas = getattr(perfil, "thesaurus", None) or []
    return [e for e in entradas if isinstance(e, dict)]


# ---------------------------------------------------------------- validación

def validar(entradas: list[dict]) -> dict:
    """Comprueba el esquema y la **integridad referencial** del tesauro.

    Devuelve ``{"problemas": [...], "resumen": {...}}``. No lanza: el tesauro roto se declara.
    """
    problemas: list[str] = []
    ids: list[str] = []
    for indice, entrada in enumerate(entradas or []):
        ident = str(entrada.get("id") or "").strip()
        if not ident:
            problemas.append(f"entrada {indice}: sin 'id'")
            continue
        ids.append(ident)
        etiquetas = entrada.get("prefLabel") or {}
        if not isinstance(etiquetas, dict) or not any(str(etiquetas.get(i) or "").strip() for i in IDIOMAS):
            problemas.append(f"«{ident}»: sin 'prefLabel' en ningún idioma")
        for relacion in RELACIONES:
            valores = entrada.get(relacion)
            if valores is None:
                continue
            if not isinstance(valores, list):
                problemas.append(f"«{ident}»: '{relacion}' debe ser una lista")
                continue
            for destino in valores:
                if not str(destino).strip():
                    problemas.append(f"«{ident}»: '{relacion}' contiene un valor vacío")
        if not str(entrada.get("source") or "").strip():
            problemas.append(f"«{ident}»: sin 'source' (no auditable)")

    repetidos = {i for i in ids if ids.count(i) > 1}
    for ident in sorted(repetidos):
        problemas.append(f"id duplicado: «{ident}»")

    conocidos = set(ids)
    for entrada in entradas or []:
        ident = str(entrada.get("id") or "").strip()
        for relacion in RELACIONES:
            for destino in (entrada.get(relacion) or []):
                if str(destino).strip() and str(destino).strip() not in conocidos:
                    problemas.append(f"«{ident}»: '{relacion}' apunta a «{destino}», que no existe")

    # Simetría: si A declara a B como más general, B debería declarar a A como más específico.
    por_id = {str(e.get("id") or "").strip(): e for e in (entradas or [])}
    for ident, entrada in por_id.items():
        for superior in (entrada.get("broader") or []):
            padre = por_id.get(str(superior).strip())
            if padre is None:
                continue
            if ident not in [str(x).strip() for x in (padre.get("narrower") or [])]:
                problemas.append(f"asimetría: «{ident}» dice que «{superior}» es más general, "
                                 f"pero «{superior}» no lo lista como más específico")

    return {
        "problemas": problemas,
        "resumen": {"entradas": len(por_id), "ids_unicos": len(conocidos),
                    "con_problemas": len(problemas), "valido": not problemas},
    }


# ---------------------------------------------------------------- consulta y expansión

def _indice(entradas: list[dict]) -> dict[str, dict]:
    """Índice normalizado (sin acentos) de etiquetas preferidas y alternativas -> entrada."""
    indice: dict[str, dict] = {}
    for entrada in entradas or []:
        ident = str(entrada.get("id") or "").strip()
        if not ident:
            continue
        candidatos = []
        etiquetas = entrada.get("prefLabel") or {}
        candidatos += [str(etiquetas.get(i) or "") for i in IDIOMAS]
        alternativas = entrada.get("altLabels") or {}
        for idioma in IDIOMAS:
            candidatos += [str(x) for x in (alternativas.get(idioma) or [])]
        candidatos.append(ident)
        for candidato in candidatos:
            clave = norm(candidato)
            if clave:
                indice.setdefault(clave, entrada)
    return indice


def buscar(termino: str, entradas: list[dict] | None = None) -> dict | None:
    """Entrada del tesauro que corresponde al término (insensible a acentos y mayúsculas)."""
    entradas = entradas if entradas is not None else cargar()
    return _indice(entradas).get(norm(termino))


def expandir(termino: str, entradas: list[dict] | None = None) -> dict:
    """Expande un término con su vocabulario controlado, para mejorar la búsqueda.

    Devuelve etiquetas preferidas y alternativas (ES/PT/EN) más los términos relacionados.
    Si el término no está en el tesauro, devuelve el término tal cual: **no se inventa** nada.
    """
    entradas = entradas if entradas is not None else cargar()
    entrada = buscar(termino, entradas)
    if not entrada:
        return {"encontrado": False, "termino": termino, "equivalentes": [], "relacionados": [],
                "mas_generales": [], "mas_especificos": [], "source": None}

    por_id = {str(e.get("id") or "").strip(): e for e in entradas}
    equivalentes: list[str] = []

    def _etiquetas(e: dict) -> list[str]:
        salida = []
        prefs = e.get("prefLabel") or {}
        salida += [str(prefs.get(i) or "") for i in IDIOMAS]
        alts = e.get("altLabels") or {}
        for idioma in IDIOMAS:
            salida += [str(x) for x in (alts.get(idioma) or [])]
        return [s for s in (x.strip() for x in salida) if s]

    equivalentes += _etiquetas(entrada)
    relacionados: list[str] = []
    mas_generales: list[str] = []
    mas_especificos: list[str] = []
    for ident in (entrada.get("related") or []):
        relacionados += _etiquetas(por_id.get(str(ident).strip(), {}))
    for ident in (entrada.get("broader") or []):
        mas_generales += _etiquetas(por_id.get(str(ident).strip(), {}))
    for ident in (entrada.get("narrower") or []):
        mas_especificos += _etiquetas(por_id.get(str(ident).strip(), {}))

    # El propio término no debe repetirse entre sus equivalentes.
    termino_norm = norm(termino)
    equivalentes = [e for e in dict.fromkeys(equivalentes) if norm(e) != termino_norm]

    return {
        "encontrado": True,
        "termino": termino,
        "id": entrada.get("id"),
        "equivalentes": equivalentes,
        "relacionados": list(dict.fromkeys(relacionados)),
        "mas_generales": list(dict.fromkeys(mas_generales)),
        "mas_especificos": list(dict.fromkeys(mas_especificos)),
        "note": entrada.get("note"),
        "source": entrada.get("source"),
    }


def expandir_consulta(terminos: list[str], entradas: list[dict] | None = None) -> dict:
    """Expande una lista de términos (los de una consulta) con el tesauro disponible.

    Devuelve los términos ampliados y las equivalencias **declaradas**, sin inventar nada.
    """
    entradas = entradas if entradas is not None else cargar()
    ampliados: list[str] = []
    equivalentes: dict[str, list[str]] = {}
    sin_cobertura: list[str] = []
    for termino in terminos or []:
        if not str(termino).strip():
            continue
        expansion = expandir(termino, entradas)
        if expansion["encontrado"]:
            equivalentes[str(termino)] = expansion["equivalentes"]
            ampliados.append(str(termino))
            ampliados += expansion["equivalentes"]
        else:
            sin_cobertura.append(str(termino))
            ampliados.append(str(termino))
    return {
        "ampliados": list(dict.fromkeys(a for a in ampliados if a)),
        "equivalentes": equivalentes,
        "sin_cobertura": sin_cobertura,
    }
