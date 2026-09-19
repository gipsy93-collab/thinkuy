"""Propuesta asistida de campos PICC/PCC para el charting — el motor propone, el humano verifica.

**Qué hace y qué no.** Rellena Población, Concepto, Contexto, Metodología, Hallazgos y
Limitaciones a partir del **texto real** del resumen y el título. **No inventa**: cada valor
propuesto debe aparecer literalmente en la fuente; si no aparece, se descarta y se declara el
motivo. El investigador revisa, corrige y guarda.

**Por qué con guardián.** Se midió que un SLM fabrica resúmenes plausibles cuando la fuente no los
tiene (6 de 7 fichas de Redalyc, Hito 38). El mismo riesgo aplica aquí: un PCC inventado contamina
la matriz de extracción, que es el insumo del informe. Por eso:

1. **Primero lo determinista.** Un resumen estructurado trae sus propias etiquetas
   («Objetivo:», «Métodos:», «Resultados:», «Conclusión:», en ES/PT/EN). De ahí se extrae **verbatim**.
2. **Después el modelo, si está disponible**, con la instrucción de **copiar fragmentos literales**
   y devolver vacío cuando no los haya.
3. **Guardián de fidelidad en ambos casos**: se comprueba que el valor propuesto sea subcadena del
   texto fuente (normalizado). Si no, se descarta y se dice por qué.
4. **Sin resumen no hay propuesta**: se declara, no se rellena.
"""
from __future__ import annotations

import logging
import re

from .normalize import norm

log = logging.getLogger("radar.charting")

# Etiquetas de resumen estructurado por campo PICC. Orden importa: la primera que aparezca.
ETIQUETAS = {
    "population": [
        r"poblaci[oó]n", r"participantes", r"muestra", r"pacientes", r"amostra", r"participantes",
        r"population", r"participants", r"sample", r"patients",
    ],
    "concept": [
        r"objetiv[oa]s?", r"objetivo geral", r"finalidad", r"prop[oó]sito", r"aim", r"objective",
        r"purpose", r"conceito", r"concepto", r"concept",
    ],
    "context": [
        r"contexto", r"[aá]mbito", r"escenario", r"lugar", r"pa[ií]s", r"regi[oó]n", r"ciudad",
        r"context", r"setting", r"location", r"country",
    ],
    "methodology": [
        r"m[eé]todos?", r"metodolog[ií]a", r"dise[ñn]o", r"materiales y m[eé]todos",
        r"m[eé]todo", r"m[eé]todos", r"m[eé]todo", r"metodologia", r"delineamento",
        r"methods?", r"methodology", r"design", r"materials and methods",
    ],
    "key_findings": [
        r"resultados?", r"hallazgos", r"principais achados", r"resultados principais",
        r"results?", r"findings", r"main findings", r"resultados",
    ],
    "limitations": [
        r"limitaciones?", r"limita[çc][oõ]es", r"limitaciones del estudio", r"limitations?",
        r"limita[çc][oõ]es do estudo",
    ],
}

# Orden canónico en que se buscan las etiquetas dentro del resumen.
ORDEN = ["concept", "methodology", "key_findings", "population", "context", "limitations"]

CAMPOS = ("population", "concept", "context", "methodology", "key_findings", "limitations")


def _patron_etiqueta(campo: str) -> re.Pattern:
    alternativas = "|".join(f"(?:{e})" for e in ETIQUETAS[campo])
    return re.compile(rf"(?:^|[.;\n]\s*|\s)({alternativas})\s*[:\-–—]\s*", re.IGNORECASE)


def extraer_estructurado(texto: str) -> dict:
    """Extrae los campos de un resumen **etiquetado** (Objetivo:/Métodos:/Resultados:…).

    Devuelve solo lo que encuentra; lo que no, no se inventa.
    """
    if not texto or len(texto) < 40:
        return {}
    # Posiciones de todas las etiquetas presentes, para cortar por tramos.
    encontradas: list[tuple[int, int, str]] = []
    for campo in ORDEN:
        for m in _patron_etiqueta(campo).finditer(texto):
            encontradas.append((m.start(), m.end(), campo))
    if not encontradas:
        return {}
    encontradas.sort()

    salida: dict = {}
    for i, (_, fin, campo) in enumerate(encontradas):
        siguiente = encontradas[i + 1][0] if i + 1 < len(encontradas) else len(texto)
        fragmento = texto[fin:siguiente].strip(" .;\n\t")
        if len(fragmento) < 12:
            continue
        # La primera aparición gana: las etiquetas repetidas suelen ser ecos.
        salida.setdefault(campo, fragmento[:600])
    return salida


def _es_fiel(valor: str, fuente: str) -> bool:
    """¿El valor propuesto aparece literalmente en la fuente? (normalizando acentos y espacios)."""
    v, f = norm(valor), norm(fuente)
    if not v:
        return False
    if v in f:
        return True
    # Tolerancia para fragmentos recortados con puntos suspensivos o comillas.
    nucleo = v.strip(" .;:\"'")
    return len(nucleo) >= 20 and nucleo in f


def proponer_con_modelo(texto: str, titulo: str, http=None) -> dict:
    """Segunda pasada: pide al bibliotecario fragmentos **literales** del resumen.

    Devuelve {} si el modelo no está disponible o si no devuelve JSON utilizable. Todo lo que
    proponga pasa después por el guardián de fidelidad.
    """
    try:
        from . import librarian
    except Exception:
        return {}
    if not librarian.available():
        return {}

    esquema = (
        '{"population": "", "concept": "", "context": "", "methodology": "", '
        '"key_findings": "", "limitations": ""}'
    )
    sistema = (
        "Eres un asistente de extracción para una revisión sistemática (marco PCC de JBI). "
        "Recibes el título y el resumen de un artículo. Devuelves un JSON con seis campos. "
        "REGLA ABSOLUTA: cada valor debe ser un **fragmento literal copiado del resumen**, "
        "sin parafrasear ni completar con conocimiento externo. Si el resumen no contiene el "
        "dato, deja el campo como cadena vacía. Nunca inventes."
    )
    usuario = (
        f"Título: {titulo}\n\nResumen:\n{texto[:3500]}\n\n"
        f"Devuelve SOLO JSON con esta forma: {esquema}"
    )
    try:
        from .normalize import unescape
        crudo = librarian._chat(sistema, usuario, temperature=0.0, max_tokens=700, timeout=45.0)
        datos = librarian._extract_json(crudo) or {}
    except Exception as e:
        log.warning("el modelo no pudo proponer el PCC: %s", e)
        return {}
    return {c: str(datos.get(c) or "").strip() for c in CAMPOS if str(datos.get(c) or "").strip()}


def limpiar_escapes(texto: str) -> str:
    """Quita escapes literales que llegan desde algunas fuentes (``\\n`` de dos caracteres).

    Medido en las fichas del IP: un resumen traía ``'...Responsabilidad,\\\\nResponsabilidad Social...'``
    —una barra invertida y una 'n' como texto—, lo que rompía tanto la extracción como el guardián
    de fidelidad. Se normaliza a espacio, no se elimina contenido.
    """
    t = texto or ""
    t = t.replace("\\r\\n", " ").replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
    t = t.replace("\\/", "/").replace("\\\"", '"')
    return re.sub(r"\s+", " ", t).strip()


def proponer_pcc(titulo: str = "", resumen: str = "", palabras_clave=None,
                 usar_modelo: bool = True) -> dict:
    """Propuesta de campos PCC para una ficha, con guardián de fidelidad.

    Devuelve ``campos`` (solo lo verificado), ``descartados`` (con el motivo), ``fuente``
    (determinista o modelo) y ``declarado`` cuando no hay nada que proponer.
    """
    titulo = limpiar_escapes(titulo)
    resumen = limpiar_escapes(resumen)
    palabras = " ; ".join(limpiar_escapes(str(k)) for k in (palabras_clave or []) if str(k).strip())
    texto = f"{titulo}. {resumen} {palabras}".strip()

    if len(resumen) < 60:
        return {"campos": {}, "descartados": [], "fuente": "ninguna", "modelo_disponible": False,
                "declarado": ("sin resumen utilizable en la ficha: no se propone nada. "
                              "Traiga el resumen de la fuente (metaetiqueta o PDF declarado).")}

    # ¿Se puede usar el modelo? Se declara, para que el investigador sepa POR QUÉ no propone.
    modelo_disponible = False
    if usar_modelo:
        try:
            from . import librarian
            modelo_disponible = librarian.available()
        except Exception:
            modelo_disponible = False

    propuesta: dict = {}
    fuente = "determinista"
    propuesta.update(extraer_estructurado(resumen))

    if usar_modelo and modelo_disponible:
        del_modelo = proponer_con_modelo(resumen, titulo)
        if del_modelo:
            fuente = "determinista+modelo"
            for campo, valor in del_modelo.items():
                propuesta.setdefault(campo, limpiar_escapes(valor))

    # ── Guardián de fidelidad: fuera lo que no esté literalmente en la fuente ──
    verificados: dict = {}
    descartados: list[dict] = []
    for campo, valor in propuesta.items():
        if campo not in CAMPOS:
            continue
        if _es_fiel(valor, texto):
            verificados[campo] = valor
        else:
            descartados.append({"campo": campo, "valor": valor[:120],
                                "motivo": "el texto propuesto no aparece literalmente en la fuente"})

    if not verificados:
        if usar_modelo and not modelo_disponible:
            motivo = ("el bibliotecario local no está encendido, así que solo se intentó la "
                      "extracción determinista, y este resumen no está etiquetado "
                      "(«Objetivo:», «Métodos:»…). Encienda LM Studio con un modelo cargado para "
                      "que el motor proponga, o rellene a mano.")
        else:
            motivo = ("el motor no encontró fragmentos literales para el PCC. Revise el resumen o "
                      "rellene a mano; no se propone nada inventado.")
        return {"campos": {}, "descartados": descartados, "fuente": fuente,
                "modelo_disponible": modelo_disponible, "declarado": motivo}

    return {"campos": verificados, "descartados": descartados, "fuente": fuente,
            "modelo_disponible": modelo_disponible, "declarado": "",
            "cobertura": f"{len(verificados)}/6 campos"}
