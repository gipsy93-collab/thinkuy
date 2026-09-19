#!/usr/bin/env python3
"""Mapeo Bibliométrico de Oportunidades Temáticas y Radar de Fronteras.

Herramienta de línea de comandos para editores y observatorios:
Analiza una revista científica vía OpenAlex y ORCID para:
1. Identificar Topics canónicos de la publicación.
2. Calcular la velocidad de publicación (RGR) y clasificar temas (Consolidados, Emergentes, Vacíos).
3. Recuperar investigadores activos con ORCID verificado e institución declarada.

Uso:
    python tools/mapeobiblio.py 1134-3478
    python tools/mapeobiblio.py "Multimed"
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

# Ajustar PYTHONPATH para importar radar
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from radar.editorial_radar import run_editorial_bibliometric_mapping

# Asegurar codificación UTF-8 en consola
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "1134-3478"
    print(f"🔍 Ejecutando Mapeo Bibliométrico para: '{target}'...\n")

    res = run_editorial_bibliometric_mapping(target, max_topics=5, authors_per_topic=3)

    if not res.get("found"):
        print(f"❌ Error: {res.get('error')}")
        sys.exit(1)

    print(f"📖 Revista: {res['journal_title']} (ISSN: {res['issn']})")
    print(f"   Producción global: {res['total_works']:,} obras | Citas globales: {res['total_citations']:,}")
    print("=" * 65)

    print("\n🏷️  TEMAS CONSOLIDADOS (Núcleo tradicional):")
    if not res["consolidated_topics"]:
        print("   (Sin temas consolidados destacados)")
    for t in res["consolidated_topics"]:
        print(f"   • [{t['name']}] (ID: {t['topic_id']})")
        print(f"     Subcampo: {t['subfield']} | Velocidad: {t['velocity']}x | Obras en revista: {t['journal_works']}")

    print("\n🚀 TEMAS EMERGENTES (Fronteras y Tendencias Recientes):")
    if not res["emerging_topics"]:
        print("   (No se detectaron temas con velocidad > 1.4 en el muestreo)")
    for t in res["emerging_topics"]:
        print(f"   • [{t['name']}] (ID: {t['topic_id']})")
        print(f"     Aceleración: {t['velocity']}x | Recientes 24-25: {t['vr_count']:,} | Base 21-23: {t['vb_count']:,}")
        print(f"     Interpretación: {t['interpretation']}")

    print("\n🔍 VACÍOS EDITORIALES / NICHOS IDENTIFICADOS:")
    if not res["gap_topics"]:
        print("   (Sin vacíos de nicho específicos detectados)")
    for t in res["gap_topics"]:
        print(f"   • [{t['name']}] (ID: {t['topic_id']})")
        print(f"     Volumen reciente: {t['vr_count']:,} obras | Obras en revista: {t['journal_works']}")

    print("\n🎯 CANDIDATOS CON ORCID VERIFICADO (Comité Editorial / Revisores Pares):")
    for i, a in enumerate(res["suggested_reviewers"], 1):
        print(f"   {i}. {a['name']}")
        print(f"      🔗 ORCID: {a['orcid_url']}")
        print(f"      🏛️  Afiliación: {a['affiliation']} ({a['country']})")
        print(f"      📚 Especialidad: {a.get('specialty_topic')} | Citas: {a['cited_by_count']:,} | H-Index: {a['h_index']}")
        print()

    print("=" * 65)
    print("💡 ACCIÓN PARA EL EDITOR:")
    print("Los temas mapeados pueden integrarse al Radar de Monitoreo continuo de la revista.")


if __name__ == "__main__":
    main()
