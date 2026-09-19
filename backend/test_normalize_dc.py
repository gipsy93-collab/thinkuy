"""Pruebas de la evaluación del texto Dublin Core (solo espaciado y conteo).

Documentan la conclusión medida el 18-09-2026: el pegote del OAI de Redalyc **no se repara
por reglas** (modificaría texto limpio) y **no se detecta con fidelidad** por señales de
superficie, de modo que el módulo no emite veredicto y el texto citable se obtiene del PDF.
"""
import pytest

from radar import normalize

# Texto limpio realista: compuestos con guion, marcas, URL, claves con mayúsculas internas,
# nombres en otros alfabetos y abreviaturas. Ninguna palabra debe cambiar.
LIMPIO = [
    "El enfoque food-energy-water nexus y el diseño co-design en la investigación-acción.",
    "TikTok, YouTube y DataStream alimentan el proyecto BioClima junto a MyPlate.",
    "Identificadores como https://id.caicyt.gov.ar/ark:/s18535925/sha9tchra y ORCID 0000-0002-1825-0097.",
    "Objectives and multiple organisational objectives, including increasing community trust.",
    "Tariq et al. (2024) y Wadi Allaqi Biosphere Reserve; Italia, Países Bajos y España & UK.",
    "La investigadora publicó en 2021 sobre el uso de códigos QR y de ADN ambiental.",
]


# ── Seguridad: no debe alterar palabras ─────────────────────────────────────

@pytest.mark.parametrize("texto", LIMPIO)
def test_normalizar_espacios_no_altera_palabras(texto):
    """La única intervención permitida: espacios. Ni guiones, ni mayúsculas, ni puntuación."""
    assert normalize.normalizar_espacios(texto).split() == normalize.unescape(texto).split()


def test_normalizar_espacios_si_limpia_espacios_y_entidades():
    assert normalize.normalizar_espacios("  Texto   con  espacios &amp; entidad ") == \
        "Texto con espacios & entidad"
    assert normalize.normalizar_espacios(None) == ""


# ── Diagnóstico: conteo de señales ──────────────────────────────────────────

def test_conteo_de_pegotes_en_texto_danado_real():
    """Frase tomada del OAI de Redalyc (artículo 10633204)."""
    danado = "La región delSoconusco, Chiapas, y la oncocercosis. Otro caso en la ciudad deTijuana."

    assert normalize.senales_pegotes(danado) == 2


def test_conteo_de_glifos_en_texto_danado_real():
    """Señales que sí disparan en texto dañado real (y dos que NO, lo que refuerza la decisión).

    Disparan: 'cafetalerq' (q sin u) y 'demogr6jico' (dígito en palabra).
    NO disparan: 'geográjka' (la j va tras vocal) ni 'wna' — el detector es incompleto,
    que es una razón más para no emitir veredicto con él.
    """
    danado = "La economía cafetalerq de la región y una wna geográjka de demogr6jico interés."

    senales = normalize.senales_glifos(danado)

    assert len(senales) == 2


def test_texto_limpio_no_tiene_conteos_altos():
    texto = "La economía cafetalera de la región del Soconusco, Chiapas, ha sido determinante."

    evaluado = normalize.evaluar_texto_dc(texto)

    assert evaluado["pegotes"] == 0
    assert evaluado["glifos"] == []


# ── La razón por la que NO hay veredicto automático ─────────────────────────

def test_las_senales_disparan_en_texto_limpio_y_por_eso_no_hay_veredicto():
    """Regresión de la decisión: si alguien reintroduce un veredicto `citable`, esto falla.

    'objectives' contiene 'bj' (j tras consonante) y 'BioClima' tiene mayúscula interior:
    ambas señales disparan en texto correcto, así que no pueden usarse como filtro.
    """
    limpio_con_falsas_senales = "Los objectives del proyecto BioClima y MyPlate son claros."

    assert normalize.senales_glifos(limpio_con_falsas_senales), \
        "las señales deben disparar aquí: es la prueba de que no discriminan"

    evaluado = normalize.evaluar_texto_dc(limpio_con_falsas_senales)
    assert "citable" not in evaluado, "no debe haber veredicto automático"
    assert "texto" in evaluado and "pegotes" in evaluado and "glifos" in evaluado


def test_el_texto_devuelto_es_el_normalizado():
    evaluado = normalize.evaluar_texto_dc("  Dos   espacios  ")

    assert evaluado["texto"] == "Dos espacios"
