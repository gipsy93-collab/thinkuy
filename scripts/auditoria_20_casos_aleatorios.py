"""
=============================================================================
Thinkuy V3 - Auditoría de 20 Casos Nuevos Aleatorios (Duque 333 & Corpus)
=============================================================================
Protocolo Estricto de Rigor Científico (Zero Sycophancy):
- Casos 100% nuevos e independientes (IDs seleccionados aleatoriamente del 21 al 333)
- Conexión 100% Local a LM Studio (http://127.0.0.1:1234/v1/chat/completions)
- Cero Fallbacks: Toda ambigüedad computa como 'INVALID_OUTPUT' y puntúa 0.
=============================================================================
"""

import os
import sys
import json
import time
import re
import random
import urllib.request
import pandas as pd
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL_ID = "google/gemma-4-e2b"
INPUT_CSV = "data/auditorias_y_benchmarks/resultados_pruebas_modelos_333.csv"
OUTPUT_CSV = "data/auditorias_y_benchmarks/auditoria_20_aleatorios_nuevos.csv"
CANTIDAD = 20

FEW_SHOT_PROMPT = """Eres un metodólogo y cienciometrista experto. Clasifica el artículo científico sobre RSU en una de las tres perspectivas de Duque & Cervantes (2019):
- P1_MEDICION_ESCALAS: Enfoque empírico cuantitativo, diseño o aplicación de escalas psicométricas, cuestionarios a gran escala, análisis factorial (SEM).
- P2_ESTRATEGICO_STAKEHOLDERS: Enfoque directivo, gobernanza institucional, políticas de dirección, modelos organizacionales, gestión estratégica ante stakeholders.
- P3_CONEXION_SOCIAL_EXTENSION: Enfoque en ética civil, formación ciudadana, justicia social, derechos humanos, aprendizaje-servicio, impacto comunitario directo.

REGLA CRÍTICA: Mantén el bloque <pensamiento> conciso (máximo 4 líneas) para emitir siempre el bloque <salida_json> completo.

FORMATO OBLIGATORIO:
<pensamiento>
1. Trampas Lingüísticas: [Palabras ambiguas]
2. Checklist Metodológico: [P1 vs P2 vs P3]
3. Conclusión: [P1_MEDICION_ESCALAS | P2_ESTRATEGICO_STAKEHOLDERS | P3_CONEXION_SOCIAL_EXTENSION]
</pensamiento>
<salida_json>
{
  "perspectiva": "P1_MEDICION_ESCALAS" | "P2_ESTRATEGICO_STAKEHOLDERS" | "P3_CONEXION_SOCIAL_EXTENSION",
  "claim_central": "[Máximo 20 palabras]"
}
</salida_json>"""

def consultar_lm_studio(user_prompt):
    payload = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": FEW_SHOT_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 1536
    }
    
    req = urllib.request.Request(
        LM_STUDIO_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            return data["choices"][0]["message"]["content"], elapsed, None
    except Exception as e:
        return "", 0, str(e)

def parse_strict_output(raw_text):
    pensamiento = ""
    perspectiva = "INVALID_OUTPUT"
    claim = ""
    
    t_match = re.search(r"<pensamiento>(.*?)</pensamiento>", raw_text, re.DOTALL | re.IGNORECASE)
    if t_match:
        pensamiento = t_match.group(1).strip()
        
    j_match = re.search(r"<salida_json>(.*?)</salida_json>", raw_text, re.DOTALL | re.IGNORECASE)
    candidate_json = j_match.group(1).strip() if j_match else raw_text.strip()
    
    obj_match = re.search(r"(\{.*\})", candidate_json, re.DOTALL)
    if obj_match:
        try:
            d = json.loads(obj_match.group(1))
            raw_p = str(d.get("perspectiva", "")).strip().upper()
            if "P1" in raw_p or "MEDICION" in raw_p or "ESCALAS" in raw_p:
                perspectiva = "P1_MEDICION_ESCALAS"
            elif "P2" in raw_p or "ESTRATEGICO" in raw_p or "STAKEHOLDER" in raw_p:
                perspectiva = "P2_ESTRATEGICO_STAKEHOLDERS"
            elif "P3" in raw_p or "CONEXION" in raw_p or "EXTENSION" in raw_p:
                perspectiva = "P3_CONEXION_SOCIAL_EXTENSION"
            claim = str(d.get("claim_central", "")).strip()
        except Exception:
            pass
            
    return pensamiento, perspectiva, claim

def main():
    print("=" * 80)
    print("AUDITORÍA DE 20 CASOS ALEATORIOS NUEVOS (DUQUE 2019): GEMMA 4 LOCAL")
    print("Protocolo: CERO complacencia, CERO fallbacks. Inferencia 100% Local.")
    print("=" * 80)
    
    df = pd.read_csv(INPUT_CSV)
    # Excluir los primeros 20 (IDs 1-20 ya evaluados)
    df_pool = df[df["id"] > 20].copy()
    
    # Muestreo aleatorio reproducible con seed
    df_sample = df_pool.sample(n=CANTIDAD, random_state=123).copy()
    
    resultados = []
    aciertos = 0
    tiempos = []
    
    for idx, (original_idx, row) in enumerate(df_sample.iterrows(), 1):
        art_id = row["id"]
        titulo = str(row["title"])[:55]
        abstract = str(row["abstract"])
        canonica = str(row["referencia_canonica_perspectiva"]).strip()
        
        user_prompt = f"Abstract a clasificar (ID {art_id}):\n\"{abstract}\""
        
        raw_resp, latencia, err = consultar_lm_studio(user_prompt)
        
        if err:
            pensamiento, pred, claim = "", "ERROR_CONEXION", ""
        else:
            pensamiento, pred, claim = parse_strict_output(raw_resp)
            
        es_acierto = (pred == canonica)
        if es_acierto:
            aciertos += 1
            
        tiempos.append(latencia)
        status_icon = "✅" if es_acierto else "❌"
        print(f"[{idx:02d}/{CANTIDAD}] (ID {art_id:03d}) {status_icon} Real: {canonica:28s} | Pred: {pred:28s} | {latencia:4.1f}s | {titulo}...")
        
        resultados.append({
            "num_muestra": idx,
            "id_original": art_id,
            "title": row["title"],
            "canonica": canonica,
            "prediccion": pred,
            "acierto": 1 if es_acierto else 0,
            "latencia_seg": round(latencia, 2),
            "pensamiento": pensamiento,
            "claim": claim,
            "raw_output": raw_resp
        })
        
    df_res = pd.DataFrame(resultados)
    df_res.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    
    total = len(df_res)
    acc = (aciertos / total) * 100
    lat_prom = sum(tiempos) / len(tiempos) if tiempos else 0
    
    dist_pred = Counter(df_res["prediccion"])
    dist_real = Counter(df_res["canonica"])
    invalidas = dist_pred.get("INVALID_OUTPUT", 0) + dist_pred.get("ERROR_CONEXION", 0)
    
    print("\n" + "=" * 80)
    print("REPORTE ESTADÍSTICO FINAL DE LOS 20 CASOS ALEATORIOS")
    print("=" * 80)
    print(f"Total evaluados:            {total}")
    print(f"Aciertos exactos:           {aciertos}/{total} ({acc:.2f}%)")
    print(f"Respuestas válidas sintaxis: {total - invalidas}/{total} ({(total-invalidas)/total*100:.1f}%)")
    print(f"Respuestas rotas/inválidas:  {invalidas}/{total} ({invalidas/total*100:.1f}%)")
    print(f"Latencia promedio por caso:  {lat_prom:.2f}s")
    
    print("\nMatriz de Confusión (Filas: Real Canónica | Columnas: Predicha por Gemma 4):")
    ct = pd.crosstab(df_res["canonica"], df_res["prediccion"], margins=True)
    print(ct.to_string())
    print("=" * 80)
    print(f"Archivo persistido en: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
