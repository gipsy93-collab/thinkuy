import os
import sys
import json
import time

# Configurar path para importar backend
sys.path.insert(0, os.path.abspath("."))

from backend.radar.harvester.live_probe import probe_topic
from backend.radar import librarian

def run_test():
    topic = "generative artificial intelligence higher education student assessment"
    print("=" * 75)
    print(f"THINKUY RADAR — SONDA EN VIVO & AUDITORÍA EPISTÉMICA CON MINISTRAL 3B")
    print(f"Tema de investigación: «{topic}»")
    print("=" * 75)

    print("\n[PASO 1] Lanzando Sonda Federada a OpenAlex Works API (Open Access)...")
    t0 = time.time()
    probe_res = probe_topic(query=topic, limit=6, federated=False, timeout=15.0)
    elapsed_probe = round(time.time() - t0, 2)

    if not probe_res or not probe_res.get("articles"):
        print("[ERROR] La sonda no devolvió artículos.")
        return

    articles = probe_res["articles"]
    total_matched = probe_res.get("total_matched", 0)
    journals = probe_res.get("core_journals", [])[:3]

    print(f"[EXITO] Sonda completada en {elapsed_probe}s.")
    print(f" - Obras totales indexadas en OpenAlex: {total_matched:,} documentos")
    print(f" - Revistas núcleo destacadas: {', '.join(journals)}")
    print(f" - Muestra recuperada para auditoría: {len(articles)} artículos en Acceso Abierto")

    print("\n[PASO 2] Clasificando posturas epistemológicas con Ministral 3B en LM Studio...")
    t1 = time.time()
    
    # Preparar payload para el clasificador de posturas de Thinkuy
    stances = librarian.classify_topic_stances_ai(articles, topic=topic, batch_size=len(articles))
    elapsed_ai = round(time.time() - t1, 2)
    print(f"[EXITO] Análisis epistemológico completado en {elapsed_ai}s (~{round(elapsed_ai/len(articles), 2)}s por artículo).\n")

    # Mapeo de colores/etiquetas en consola
    STANCE_LABELS = {
        "supporting": "POSIBLE CONSENSO / APOYO (+)",
        "contradicting": "POSIBLE DISENSO / ALERTA CRÍTICA (-)",
        "methodological": "ADOPCIÓN METODOLÓGICA (M)",
        "mixed": "MENCIÓN CONTEXTUAL / ESTADO DEL ARTE (~)",
    }

    print("-" * 75)
    print(f"{'#':<3} | {'POSTURA':<32} | {'TÍTULO Y RATIONALE'}")
    print("-" * 75)

    for i, (art, st_info) in enumerate(zip(articles, stances), 1):
        st = st_info.get("stance", "mixed")
        lbl = STANCE_LABELS.get(st, st.upper())
        title = art.get("title", "Sin título")
        year = art.get("year", "n.d.")
        doi = art.get("doi", "")
        rationale = st_info.get("rationale") or "Sin justificación"
        conf = st_info.get("confidence", "low")

        print(f"{i:<3} | {lbl:<32} | ({year}) {title[:65]}...")
        print(f"    | Justificación IA : {rationale}")
        print(f"    | Confianza: {conf} | DOI: {doi}")
        print("-" * 75)

if __name__ == "__main__":
    run_test()
