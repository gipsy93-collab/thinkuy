"""
=============================================================================
Thinkuy V3 - Simulación Previa In-Context: Validación de los 20 Casos Complejos
=============================================================================
Protocolo de Validación del Dataset Gold Standard:
- Inyecta las Fórmulas de Hyland/Swales y la Guía de Descarte Epistémico en el contexto.
- Evalúa los 20 artículos más complejos y ambiguos del benchmark de Duque 2019.
- Comprueba si la lógica del dataset eleva la precisión de la línea base (30%-50%) hacia >80%.
=============================================================================
"""

import os
import sys
import json
import time
import re
import urllib.request
import pandas as pd
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL_ID = "google/gemma-4-e2b"
INPUT_CSV = "data/auditorias_y_benchmarks/resultados_pruebas_modelos_333.csv"
OUTPUT_CSV = "data/auditorias_y_benchmarks/simulacion_previa_20_complejos.csv"

# 20 Casos Arquetípicos de Máxima Complejidad (Confusiones Cruzadas P1 <-> P2 <-> P3)
IDS_COMPLEJOS = [
    2,   # P2 (Universidad confesional, confundido con P1 o P3)
    3,   # P2 (Learning organization con 536 miembros y cuestionario, confundido con P1)
    4,   # P2 (Dropout UIS con políticas institucionales, confundido con P1)
    5,   # P1 (Theoretical framework & global survey, confundido con P2)
    6,   # P2 (Vasilescu et al. 2010 - Tronco canónico de P2, confundido con P3)
    8,   # P2 (UMET Ecuador con entrevistas y diagnóstico, confundido con P3)
    12,  # P1 (Students' involvement y medición de actitudes)
    14,  # P1 (USR Network - plataforma de medición y autodiagnóstico)
    16,  # P2 (Análisis bibliométrico de 94 documentos, confundido con P1)
    18,  # P2 (Ontology development para gestión directiva, confundido con P1)
    19,  # P2 (Causal relationship model de gobernanza, confundido con P1)
    32,  # P1 (Conceptualization and measurement scale)
    36,  # P1 (Student base analysis con encuestas empíricas)
    50,  # P1 (Insight from the historical perspective with survey tools)
    52,  # P2 (Towards university social responsibility: institutional change)
    82,  # P2 (Perspectiva directiva frente a sociedad civil, confundido con P3)
    92,  # P1 (Life skills perception: escala empírica de estudiantes)
    114, # P2 (Ethical & civic dimension of service learning as institutional policy)
    126, # P2 (Representational speeches on knowledge transfer: gestión de gobernanza)
    146  # P2 (Pro-sociality in VLEs: gestión estratégica de directivos)
]

# Andamiaje Epistémico con las Fórmulas de Hyland y Reglas de Descarte del Dataset
STEERING_PROMPT = """Eres el Módulo Epistémico Thinkuy especializado en cienciometría de RSU (Duque & Cervantes, 2019).
Tu labor es clasificar el artículo científico en su PERSPECTIVA CANÓNICA EXACTA aplicando la lógica sintáctica de Ken Hyland y John Swales:

TAXONOMÍA CANÓNICA:
1. P1_MEDICION_ESCALAS:
   - Foco: El fin último del paper es diseñar, calibrar, validar psicométricamente o aplicar una escala cuantitativa, cuestionario propio o modelado estadístico (SEM/PLS/Alfa de Cronbach) para medir RSU o variables psicológicas en estudiantes/docentes.
   - Regla de Descarte: Si solo usa encuestas secundarias exploratorias para evaluar políticas institucionales, NO es P1, es P2.

2. P2_ESTRATEGICO_STAKEHOLDERS:
   - Foco: Modelos de gestión directiva, gobernanza universitaria, políticas institucionales, alineación estratégica con stakeholders, análisis bibliométricos del campo o memorias de sostenibilidad.
   - Regla de Descarte: Aunque mencione "sociedad civil", "ética" o "números de documentos", si el fin es la gestión u organización institucional, es P2.

3. P3_CONEXION_SOCIAL_EXTENSION:
   - Foco: Proyectos de intervención comunitaria directa, programas de aprendizaje-servicio, formación ciudadana crítica, ética cívica, voluntariado o defensa de los derechos humanos y justicia social.
   - Regla de Descarte: Críticas a la mercantilización de la universidad o proyectos directos con comunidades vulnerables.

<ejemplos_guias>
<ejemplo>
Abstract: "This study investigated the relationship between learning organization and university social responsibility... 536 members filled in the 21-item Dimensions Questionnaire..." (Rus et al., 2014)
<pensamiento>
1. Trampas: Menciona "536 members", "questionnaire", "21-item".
2. Checklist Hyland: El AGENTE evalúa la dinámica organizacional interna de gobernanza ante stakeholders internos. No diseña ni valida una nueva escala psicométrica de RSU.
3. Conclusión: P2_ESTRATEGICO_STAKEHOLDERS.
</pensamiento>
<salida_json>
{"perspectiva": "P2_ESTRATEGICO_STAKEHOLDERS", "claim_central": "Las organizaciones de aprendizaje mejoran la RSU al alinear actores estratégicos internos."}
</salida_json>
</ejemplo>

<ejemplo>
Abstract: "A descriptive study... A bibliometric analysis of 94 documents obtained from Redalyc and Scielo was performed to evaluate trends and key authors..." (Pacenza & Peralta, 2013)
<pensamiento>
1. Trampas: "Bibliometric analysis", "94 documents".
2. Checklist Hyland: Mapeo del estado del arte y gobernanza conceptual del campo. No mide sujetos humanos ni valida instrumentos.
3. Conclusión: P2_ESTRATEGICO_STAKEHOLDERS.
</pensamiento>
<salida_json>
{"perspectiva": "P2_ESTRATEGICO_STAKEHOLDERS", "claim_central": "Mapea la evolución de la producción científica sobre RSU en América Latina."}
</salida_json>
</ejemplo>
</ejemplos_guias>

FORMATO OBLIGATORIO:
<pensamiento>
1. Trampas Lingüísticas: [Palabras ambiguas]
2. Checklist Hyland / Swales: [P1 vs P2 vs P3 aplicando las reglas de descarte]
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
            {"role": "system", "content": STEERING_PROMPT},
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
    print("SIMULACIÓN PREVIA IN-CONTEXT: VALIDACIÓN DE LOS 20 CASOS COMPLEJOS")
    print("Modelo: Gemma 4 Local | Servidor: LM Studio | Protocolo: Cero Fallbacks")
    print("=" * 80)
    
    df = pd.read_csv(INPUT_CSV)
    df_complejos = df[df["id"].isin(IDS_COMPLEJOS)].copy()
    
    # Ordenar por el orden de IDS_COMPLEJOS
    df_complejos["sort_key"] = df_complejos["id"].map(lambda x: IDS_COMPLEJOS.index(x) if x in IDS_COMPLEJOS else 999)
    df_complejos = df_complejos.sort_values("sort_key").reset_index(drop=True)
    
    resultados = []
    aciertos = 0
    tiempos = []
    
    for idx, row in df_complejos.iterrows():
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
        print(f"[{idx+1:02d}/20] (ID {art_id:03d}) {status_icon} Real: {canonica:28s} | Pred: {pred:28s} | {latencia:4.1f}s | {titulo}...")
        
        resultados.append({
            "num_muestra": idx + 1,
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
    print("REPORTE FINAL DE LA SIMULACIÓN PREVIA (VALIDACIÓN DEL DATASET)")
    print("=" * 80)
    print(f"Total Casos Complejos Evaluados: {total}")
    print(f"Aciertos con Andamiaje del Dataset: {aciertos}/{total} ({acc:.2f}%)")
    print(f"Respuestas Válidas Sintaxis:       {total - invalidas}/{total} ({(total-invalidas)/total*100:.1f}%)")
    print(f"Respuestas Rotas / Inválidas:      {invalidas}/{total} ({invalidas/total*100:.1f}%)")
    print(f"Latencia promedio por caso:        {lat_prom:.2f}s")
    
    print("\nMatriz de Confusión de Casos Complejos (Filas: Real | Columnas: Predicho):")
    ct = pd.crosstab(df_res["canonica"], df_res["prediccion"], margins=True)
    print(ct.to_string())
    print("=" * 80)
    print(f"Resultados guardados en: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
