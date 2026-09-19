"""PATRÓN DORADO: material de evaluación con niveles de complejidad y su cálculo de métricas.

Existen **tres capas**, porque medir «la herramienta» de una sola vez sería inmanejable:

  * **Capa A — Recuperación.** Consultas de investigador, con línea base manual (Scopus/WoS).
  * **Capa B — Extracción de metadatos.** Fichas reales contra su verdad de origen.
  * **Capa C — Juicio discursivo.** Ya existe: `control_36` + `control_protocolo_12` con κ.

Este script cubre A y B: genera el material, lo **congela con SHA-256** y, una vez anotado,
calcula las métricas. Nada se puntúa «a ojo» y **toda salida rota o vacía cuenta como fallo
estricto** (sin fallbacks complacientes).

USO:
    python tools/patron_dorado.py --generar      # crea las hojas de anotación
    python tools/patron_dorado.py --evaluar      # calcula métricas sobre lo anotado
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))

DESTINO = RAIZ / "data" / "gold_standard"

# ══════════════════════════════════════════════════════════════════════════════
# CAPA A — CONSULTAS, POR NIVEL DE COMPLEJIDAD
# ══════════════════════════════════════════════════════════════════════════════

NIVELES_A = {
    "N1": ("Monoconcepto explícito", "Un solo concepto, bien definido. Mide precisión básica."),
    "N2": ("Multiconcepto con sinónimos", "Varios conceptos que deben coexistir; exige vocabulario controlado."),
    "N3": ("Pregunta larga en lenguaje natural", "Como pregunta un investigador. Mide que NO devuelva cero y que declare la consulta usada."),
    "N4": ("Interdisciplinar o translengua", "El mismo concepto en ES/PT/EN, o un cruce de disciplinas. Mide cobertura iberoamericana."),
    "N5": ("Fuera de alcance (control de relevancia)",
           "Consulta legítima pero fuera del alcance del corpus. **Medido: el motor NO devuelve vacío** "
           "—encuentra coincidencias laxas por relevancia (3 a 273 obras en las 8 pruebas)—, así que lo "
           "que se mide NO es el vacío sino la HONESTIDAD: precisión@10 ≈ 0 y la herramienta debe "
           "**declarar** que los resultados no responden a la consulta en vez de presentarlos como "
           "«vinculados a X». Si los presenta como vinculados, FALLA."),
}

CONSULTAS_A = [
    # ── N1: monoconcepto (8) ────────────────────────────────────────────────
    ("N1", "es", "altmetría"),
    ("N1", "es", "bibliometría"),
    ("N1", "es", "desinformación"),
    ("N1", "es", "acceso abierto"),
    ("N1", "pt", "altmetria"),
    ("N1", "pt", "bibliometria"),
    ("N1", "pt", "desinformação"),
    ("N1", "pt", "acesso aberto"),
    # ── N2: multiconcepto con sinónimos (8) ─────────────────────────────────
    ("N2", "es", "altmetría en revistas iberoamericanas"),
    ("N2", "es", "desinformación y redes sociales en elecciones"),
    ("N2", "es", "ciencia abierta y datos abiertos en América Latina"),
    ("N2", "es", "revisión por pares e integridad científica"),
    ("N2", "pt", "comunicação científica e divulgação em Portugal"),
    ("N2", "pt", "acesso aberto diamante em revistas de humanidades"),
    ("N2", "pt", "bibliometria da produção científica brasileira"),
    ("N2", "es", "métricas alternativas para evaluar el impacto social"),
    # ── N3: pregunta larga en lenguaje natural (8) ──────────────────────────
    ("N3", "es", "¿Qué instrumentos o escalas se utilizan para valorar a un paciente con "
                 "antecedentes de cáncer de riñón y miocarditis, y evaluar su percepción del "
                 "manejo de la salud?"),
    ("N3", "es", "¿Cómo se mide el impacto social de la investigación en ciencias sociales "
                 "latinoamericanas y qué indicadores alternativos existen?"),
    ("N3", "pt", "Quais são os critérios de avaliação da produção científica brasileira em "
                 "ciências humanas e como eles afetam a publicação em acesso aberto?"),
    ("N3", "es", "¿De qué manera la desinformación en redes sociales influye en la decisión "
                 "de voto de los jóvenes durante las elecciones presidenciales?"),
    ("N3", "pt", "Como a revisão por pares por pares abertos tem sido avaliada na América "
                 "Latina e quais são os desafios relatados pelos editores?"),
    ("N3", "es", "¿Qué políticas de ciencia abierta existen en Iberoamérica y cómo se "
                 "relacionan con los repositorios institucionales?"),
    ("N3", "pt", "De que forma a divulgação científica em redes sociais contribui para o "
                 "letramento científico do público não especializado?"),
    ("N3", "es", "¿Qué evidencia hay sobre el sesgo de género en la evaluación por pares de "
                 "las revistas académicas iberoamericanas?"),
    # ── N4: translengua / interdisciplinar (8) ──────────────────────────────
    ("N4", "es", "ciencia abierta"),
    ("N4", "pt", "ciência aberta"),
    ("N4", "en", "open science"),
    ("N4", "es", "comunicación científica"),
    ("N4", "pt", "comunicação científica"),
    ("N4", "en", "science communication"),
    ("N4", "es", "bibliometría y medicina: análisis de la producción cardiológica"),
    ("N4", "es", "inteligencia artificial y acceso abierto a la literatura científica"),
    # ── N5: fuera de alcance — control de relevancia ────────────────────────
    # Medido el 18-09-2026: las 8 devuelven resultados (3 a 273 obras). Por eso el control no
    # mide «vacío» sino que la herramienta DECLARE que no cubre la consulta y que los primeros
    # resultados no sean pertinentes (precisión@10 ≈ 0). Si los presenta como vinculados, falla.
    ("N5", "es", "altmetría de la investigación en espeleología recreativa iberoamericana"),
    ("N5", "es", "bibliometría de la producción científica sobre cría de yaks en el altiplano boliviano"),
    ("N5", "pt", "métricas altmétricas da pesquisa em genealogia de felinos domésticos na Amazônia"),
    ("N5", "es", "ciencia abierta aplicada a la arqueología subacuática en el río Magdalena"),
    ("N5", "pt", "avaliação por pares de estudos sobre pistas de pouso de dirigíveis no Brasil"),
    ("N5", "es", "acceso abierto en revistas de numismática fenicia iberoamericana"),
    ("N5", "pt", "comunicação científica sobre criação de alpacas em bibliotecas escolares brasileiras"),
    ("N5", "es", "impacto altmétrico de la investigación en telegrafía óptica andina"),
]

# ══════════════════════════════════════════════════════════════════════════════
# CAPA B — FICHAS PARA EXTRACCIÓN DE METADATOS
# ══════════════════════════════════════════════════════════════════════════════

NIVELES_B = {
    "B1": ("Metaetiquetas completas (SciELO)", "citation_abstract presente. Esperado: todo correcto sin modelo."),
    "B2": ("Dublin Core (OJS)", "Resumen en DC.Description. Esperado: resumen 100 % verbatim."),
    "B3": ("Sin metadatos (PDF o JS)", "Solo PDF declarado o página dependiente de JavaScript."),
    "B4": ("Página caída o muro (control)", "Debe declarar el vacío. Ninguna invención: tasa de invención = 0."),
}

PAGINAS_B = [
    # Se completan desde `data/demo/verificacion_cadena_resumen.json`, que ya midió de dónde
    # sale el resumen de cada ficha. Clasificar por lo medido, no por lo supuesto.
    ("B4", "http://old.scielo.br/scielo.php?script=sci_arttext&pid=S1414-81452017000200203"),
]

# Clasificación de una ficha en su nivel B según la cadena determinista ya medida.
NIVEL_POR_FUENTE = {
    "citation_abstract": "B1",   # SciELO y OJS con metaetiqueta completa
    "dc_description": "B2",      # OJS con Dublin Core
    "pdf_abstract": "B3",        # solo PDF declarado
    "meta_description": "B3",    # descripción de ficha, sin resumen formal
    "none": "B3",                # sin resumen en la ficha
}


def paginas_desde_verificacion() -> list[tuple[str, str]]:
    """Lee las fichas ya verificadas y las clasifica por el nivel medido."""
    ruta = RAIZ / "data" / "demo" / "verificacion_cadena_resumen.json"
    if not ruta.exists():
        return list(PAGINAS_B)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    paginas = []
    for fila in datos.get("paginas", []):
        url = (fila.get("url") or "").replace("&amp;", "&").strip()
        if not url:
            continue
        if not fila.get("ficha_descargada"):
            nivel = "B4"  # muro o ficha no descargada: control de vacío declarado
        else:
            nivel = NIVEL_POR_FUENTE.get(fila.get("fuente") or "none", "B3")
        paginas.append((nivel, url))
    # Añadir el muro de SciELO, que es el caso B4 mejor documentado.
    paginas.append(("B4", "http://old.scielo.br/scielo.php?script=sci_arttext&pid=S1414-81452017000200203"))
    vistos = set()
    unicas = []
    for nivel, url in paginas:
        clave = url.replace("&amp;", "&").rstrip("/").lower()
        if clave not in vistos:
            vistos.add(clave)
            unicas.append((nivel, url))
    return unicas


def _huella(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def generar() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)

    # ── Capa A: hoja de anotación ───────────────────────────────────────────
    lineas = ["nivel\tidioma\tconsulta\tconsulta_usada_por_la_herramienta\t"
              "resulto_cero(SI/NO)\tse_relajo(SI/NO)\t"
              "linea_base_total\tlinea_base_dois_relevantes\tnotas"]
    for nivel, idioma, consulta in CONSULTAS_A:
        lineas.append(f"{nivel}\t{idioma}\t{consulta}\t\t\t\t\t\t")
    ruta_a = DESTINO / "A_consultas.tsv"
    ruta_a.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    # ── Capa B: hoja de anotación ───────────────────────────────────────────
    paginas = paginas_desde_verificacion()
    lineas_b = ["nivel\turl\tverdad_titulo\tverdad_autores\tverdad_anio\tverdad_revista\t"
                "verdad_doi\tverdad_resumen_verbatim\ttiene_resumen_real(SI/NO)\tnotas"]
    for nivel, url in paginas:
        lineas_b.append(f"{nivel}\t{url}\t\t\t\t\t\t\t\t")
    ruta_b = DESTINO / "B_fichas.tsv"
    ruta_b.write_text("\n".join(lineas_b) + "\n", encoding="utf-8")

    # ── Protocolo y congelación ─────────────────────────────────────────────
    protocolo = {
        "capas": {
            "A_recuperacion": {
                "niveles": NIVELES_A,
                "consultas": len(CONSULTAS_A),
                "metricas": ["precisión@10", "recall@k contra línea base manual",
                             "tasa de cero resultados (N1–N4: cuanto menor, mejor)",
                             "tasa de relajación declarada",
                             "**N5 (fuera de alcance): precisión@10 ≈ 0 Y que la herramienta DECLARE "
                             "que no cubre la consulta. Presentarlos como «vinculados» es un FALLO.**"],
                "anota": "el investigador, con búsqueda propia en Scopus/WoS/Google Scholar",
                "hallazgo_previo": "Medido el 18-09-2026: las 8 consultas N5 devuelven resultados "
                                   "(3–273 obras). El motor no devuelve vacío ante consultas fuera de "
                                   "alcance: encuentra coincidencias laxas. Por eso el control mide "
                                   "honestidad, no vacío.",
            },
            "B_extraccion": {
                "niveles": NIVELES_B,
                "fichas": len(paginas),
                "metricas": ["exactitud por campo", "fidelidad verbatim (tools/auditar_fidelidad.py)",
                             "tasa de invención (debe ser 0)"],
                "anota": "el investigador leyendo la ficha o el PDF original",
            },
            "C_discursivo": {
                "existe": ["data/dataset_v4/control_36.tsv", "data/dataset_v4/control_protocolo_12.tsv"],
                "metrica": "κ de Cohen por eje (umbral pre-registrado 0,60)",
            },
        },
        "reglas": [
            "Las hojas se anotan A CIEGAS: no se consulta la salida de la herramienta antes de escribir la verdad.",
            "Toda salida vacía, rota o fuera de taxonomía cuenta como FALLO ESTRICTO (0 puntos).",
            "Los umbrales son pre-registrados: no se ajustan después de ver los resultados.",
            "El material se congela con SHA-256 antes de la primera anotación.",
        ],
        "huellas": {"A_consultas.tsv": _huella("\n".join(lineas)),
                    "B_fichas.tsv": _huella("\n".join(lineas_b))},
    }
    (DESTINO / "protocolo.json").write_text(
        json.dumps(protocolo, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 92)
    print("MATERIAL DEL PATRÓN DORADO GENERADO")
    print("=" * 92)
    print(f"  Capa A: {len(CONSULTAS_A)} consultas")
    for nivel, (nombre, _) in NIVELES_A.items():
        print(f"    {nivel}: {sum(1 for c in CONSULTAS_A if c[0] == nivel):>2} · {nombre}")
    print(f"  Capa B: {len(paginas)} fichas reales, clasificadas por lo que midió la verificación")
    print(f"  Hojas  : {ruta_a.name}, {ruta_b.name}")
    print(f"  Huellas: {protocolo['huellas']}")
    print("\n  Siguiente paso del investigador: anotar A_consultas.tsv con su búsqueda propia.")


# ══════════════════════════════════════════════════════════════════════════════
# EVALUACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def evaluar() -> None:
    """Calcula métricas sobre las hojas anotadas. Sin datos, declara que falta."""
    hoja = DESTINO / "A_consultas.tsv"
    if not hoja.exists():
        print("No existe la hoja A_consultas.tsv. Ejecuta --generar primero.")
        return

    filas = [l.split("\t") for l in hoja.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    anotadas = [f for f in filas if len(f) > 7 and f[5].strip()]
    print("=" * 92)
    print("EVALUACIÓN DEL PATRÓN DORADO — CAPA A")
    print("=" * 92)
    print(f"  consultas totales : {len(filas)}")
    print(f"  consultas anotadas: {len(anotadas)}")
    if not anotadas:
        print("\n  Aún no hay anotaciones humanas. El material está listo; falta la línea base.")
        print("  Hasta entonces no se reporta ninguna métrica: inventarlas sería el error que")
        print("  el protocolo del proyecto prohíbe.")
        return

    from collections import Counter
    por_nivel = Counter(f[0] for f in anotadas)
    ceros = sum(1 for f in anotadas if f[4].strip().upper().startswith("S"))
    relajadas = sum(1 for f in anotadas if f[5].strip().upper().startswith("S"))
    print(f"  por nivel        : {dict(por_nivel)}")
    print(f"  cero resultados  : {ceros} ({100 * ceros / len(anotadas):.1f} %)")
    print(f"  con relajación   : {relajadas} ({100 * relajadas / len(anotadas):.1f} %)")
    print("\n  (precisión@10 y recall requieren los DOIs de la línea base, todavía vacíos)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generar", action="store_true")
    ap.add_argument("--evaluar", action="store_true")
    args = ap.parse_args()
    if args.evaluar:
        evaluar()
    else:
        generar()


if __name__ == "__main__":
    main()
