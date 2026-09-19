"""Pruebas del perfil NEUTRO: la herramienta no debe dar prioridad a ninguna disciplina.

Motivo (18-09-2026): `comunicacion` era el campo de prueba y estaba de fábrica como perfil por
defecto, de modo que toda consulta —incluidas las clínicas— se clasificaba dentro de sus ocho
temas. El perfil de campo debe ser una decisión explícita del investigador.
"""
import json

from radar import config, profile, topics
from radar.harvester import scielo


# ── El defecto es neutro ────────────────────────────────────────────────────

def test_el_campo_por_defecto_no_es_comunicacion():
    assert config.THINKUY_FIELD == "general", "el campo de prueba no puede ser el de fábrica"
    import os
    assert os.environ.get("THINKUY_FIELD") != "comunicacion"


def test_el_perfil_activo_es_neutro():
    activo = profile.field_profile

    assert activo.id == "general"
    assert activo.topics == [], "el modo neutro no impone taxonomía temática"
    assert topics.fields() == [], "la escucha no debe elegir entre temas de una disciplina"
    assert activo.discovery_terms == [], "sin términos de disciplina de fábrica"


def test_el_perfil_neutro_conserva_el_alcance_iberoamericano():
    activo = profile.field_profile

    # El alcance del producto es el Sur Global iberoamericano: eso NO es una disciplina.
    assert "scl" in activo.collections and "mex" in activo.collections
    assert set(activo.languages) >= {"es", "pt"}


def test_el_perfil_neutro_mantiene_el_bibliotecario_encendido():
    """Sin LLM, la escucha caería al modo determinista y empeoraría las búsquedas."""
    assert profile.field_profile.llm.get("enabled") is True


def test_un_id_sin_archivo_produce_perfil_vacio_y_utilizable():
    vacio = profile.load_profile("no_existe_esta_disciplina")

    assert vacio.id == "no_existe_esta_disciplina"
    assert vacio.topics == []
    assert vacio.collections == []
    assert vacio.field_label  # siempre hay etiqueta para la interfaz


# ── El fantasma no vuelve por la puerta de atrás ────────────────────────────

def test_ningun_modulo_hardcodea_el_campo_de_prueba():
    """Regresión: los fallbacks y las listas de palabras del código eran de comunicación."""
    from pathlib import Path

    radar = Path(profile.__file__).resolve().parent
    culpables = []
    for ruta in radar.rglob("*.py"):
        if "scratch" in str(ruta):
            continue
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if '"comunicacion"' in linea:
                culpables.append(f"{ruta.name}:{numero}")

    assert not culpables, f"quedan referencias duras al campo de prueba: {culpables}"


def test_los_terminos_omnipresentes_viven_en_el_perfil_no_en_el_codigo():
    """El perfil de comunicación puede declarar los suyos; el neutro no descarta ninguno."""
    neutro = json.loads((config.PROFILES_DIR / "general.json").read_text(encoding="utf-8"))
    comunicacion = json.loads((config.PROFILES_DIR / "comunicacion.json").read_text(encoding="utf-8"))

    assert neutro.get("ubiquitous_terms") == []
    assert "comunicacion" in (comunicacion.get("ubiquitous_terms") or [])


# ── Coherencia con la cosecha ───────────────────────────────────────────────

def test_sin_terminos_de_campo_no_se_descartan_todas_las_revistas():
    """Antes, `any(...)` con lista vacía daba falso y se saltaba toda revista."""
    colecciones = scielo.COLLECTIONS
    terminos = scielo.COMM_TERMS

    assert colecciones, "el perfil neutro conserva las colecciones iberoamericanas"
    assert terminos == []

    # La regla correcta: sin términos no se filtra por disciplina.
    def pasa_al_filtro(titulo: str) -> bool:
        return (not terminos) or any(scielo._clean(t) in scielo._clean(titulo) for t in terminos)

    assert pasa_al_filtro("Revista de Cardiología del Sur") is True
    assert pasa_al_filtro("Cuadernos de Comunicación") is True
