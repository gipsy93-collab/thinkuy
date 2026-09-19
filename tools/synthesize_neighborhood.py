import os
import sys
import json
import time

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath("."))

from backend.radar import librarian

NEIGHBORHOOD_SYSTEM = (
    "Eres el Metodólogo Epistemológico de Thinkuy (Scoping Review & Mapeo de Controversias). "
    "Recibes una bandeja estructurada de CITAS DE DISENSO/REFUTACIÓN reales extraídas de la literatura científica. "
    "Tu labor es trazar el MAPEO EPISTÉMICO / VECINDARIOS DE AUTORES:\n"
    "1. Agrupa las citas en FRENTES TEMÁTICOS DE TENSIÓN (ejes de debate).\n"
    "2. Para cada frente, explicita el choque dialéctico: quién sostiene qué postulado inicial, "
    "quién lo refuta, cuestiona o matiza, y cuál es el punto de discordia (teórico, metodológico o empírico).\n"
    "3. Concluye con un resumen de los vacíos epistémicos o acuerdos emergentes.\n"
    "REGLA DE ORO: Basa tu análisis EXCLUSIVAMENTE en los autores, años y fragmentos literales provistos en la bandeja. "
    "No inventes citas externas ni relaciones que no figuren en los datos."
)

def run_neighborhood_synthesis():
    data_file = "data/refutations_rpp_5_volumes.json"
    if not os.path.exists(data_file):
        print(f"[ERROR] No se encontró {data_file}")
        return

    with open(data_file, "r", encoding="utf-8") as f:
        refutations = json.load(f)

    print("=" * 85)
    print("THINKUY — SÍNTESIS DE VECINDARIO EPISTÉMICO Y MAPEO DE CONTROVERSIAS")
    print(f"Alimentando a Ministral 3B con {len(refutations)} relaciones de disenso estructuradas...")
    print("=" * 85)

    # Construir la bandeja estructurada
    tray = []
    for item in refutations:
        tray.append({
            "num": item["number"],
            "articulo_origen": item["source_article"],
            "autor_citado": f"{item['cited_author']} ({item.get('cited_year','')})",
            "oracion_literal": item["sentence"],
            "claim_especifico": item.get("claim")
        })

    user_prompt = (
        "Bandeja de Evidencia Estructurada (Disensos detectados en manuscritos de RPP):\n"
        + json.dumps(tray, ensure_ascii=False, indent=2)
        + "\n\nPor favor, genera el informe de Mapeo Epistémico y Vecindarios de Autores en español académico."
    )

    t0 = time.time()
    try:
        model_name = librarian._classify_model()
        report = librarian._chat(
            system=NEIGHBORHOOD_SYSTEM,
            user=user_prompt,
            temperature=0.2,
            max_tokens=1500,
            timeout=120,
            model=model_name
        )
        elapsed = round(time.time() - t0, 2)
    except Exception as e:
        print(f"[ERROR] Falló la llamada a Ministral 3B: {e}")
        return

    print(f"\n[ÉXITO] Síntesis generada por Ministral 3B en {elapsed}s:\n")
    print("-" * 85)
    print(report)
    print("-" * 85)

    # Guardar reporte
    out_file = "data/neighborhood_synthesis_report.md"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("# Thinkuy — Mapeo Epistémico y Vecindarios de Autores\n")
        f.write(f"*Generado con Ministral 3B en {elapsed}s a partir de 10 controversias de RPP*\n\n")
        f.write(report)
    print(f"\n[EXPORTACIÓN] Informe guardado en: {out_file}")

if __name__ == "__main__":
    run_neighborhood_synthesis()
