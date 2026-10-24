"""
=============================================================================
Thinkuy - Script 07B: Evaluación Rigurosa Amplia con Pensamiento Sintético
=============================================================================
Solución al cuello de botella de truncamiento de tokens:
- max_tokens: 1536 (garantiza cierre íntegro de <pensamiento> y <salida_json>)
- Instrucción de síntesis: Checklist CoT de 3 líneas directas.
- Protocolo: Cero complacencia, Cero fallbacks.
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
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL_ID = "google/gemma-4-e2b"
INPUT_CSV = "data/auditorias_y_benchmarks/resultados_pruebas_modelos_333.csv"
OUTPUT_CSV = "data/auditorias_y_benchmarks/auditoria_amplia_gemma4_duque_test.csv"
SAMPLE_SIZE = 20

FEW_SHOT_PROMPT = """Eres un metodólogo y cienciometrista experto. Clasifica el artículo científico sobre RSU en una de las tres perspectivas de Duque & Cervantes (2019):
- P1_MEDICION_ESCALAS: Enfoque empírico cuantitativo, diseño o aplicación de escalas psicométricas, cuestionarios, análisis factorial (SEM).
- P2_ESTRATEGICO_STAKEHOLDERS: Enfoque directivo, gobernanza institucional, políticas de dirección, modelos organizacionales, gestión estratégica ante stakeholders.
- P3_CONEXION_SOCIAL_EXTENSION: Enfoque en ética civil, formación ciudadana, justicia social, derechos humanos, aprendizaje-servicio, impacto comunitario directo.

REGLA CRÍTICA: Mantén el bloque <pensamiento> muy breve y conciso (máximo 4 líneas) para emitir siempre el bloque <salida_json> completo.

<ejemplos_referencia>
<ejemplo id="1">
Abstract: "This paper aims to explain the shifting from Corporate Social University to University Social Responsibility, by presenting the conceptual framework of Social Responsibility and the university as a special type of organization which needs to adopt a social responsibility strategy just like the other organizations, in order to meet the expectations of the stakeholders... presents a general University Social Responsibility model in the context of globalization..." (Vasilescu et al., 2010)
<pensamiento>
1. Trampas: Menciona "model" y "civil society".
2. Checklist: No diseña escalas psicométricas (No P1). Propone modelo de gestión directiva y gobernanza ante stakeholders (Es P2). No es voluntariado directo (No P3).
3. Conclusión: P2_ESTRATEGICO_STAKEHOLDERS.
</pensamiento>
<salida_json>
{"perspectiva": "P2_ESTRATEGICO_STAKEHOLDERS", "claim_central": "Propone un modelo integrador de RSU universitaria para alinear instituciones con stakeholders."}
</salida_json>
</ejemplo>

<ejemplo id="2">
Abstract: "The principal aim of this paper is to identify the factors that define students' perceptions of university social responsibility (USR) in a Spanish university... a self-report study was conducted with a total sample of 400 undergraduate students. Structural equation modeling with PLS was used to test the students' overall perception..." (Vázquez et al., 2015)
<pensamiento>
1. Trampas: Menciona percepción estudiantil y gestión.
2. Checklist: Aplica muestreo empírico cuantitativo de 400 estudiantes y análisis factorial PLS-SEM (Es P1). No es directriz de gobernanza general.
3. Conclusión: P1_MEDICION_ESCALAS.
</pensamiento>
<salida_json>
{"perspectiva": "P1_MEDICION_ESCALAS", "claim_central": "Valida mediante PLS-SEM una estructura factorial de percepción de RSU en estudiantes universitarios."}
</salida_json>
</ejemplo>

<ejemplo id="3">
Abstract: "This article aims at consolidating the theoretical framework of University Social Responsibility (USR) based on the conceptual analysis of the ten most frequent fallacies. It critiques the reduction of USR to mere corporate marketing or philanthropic extension, defending a comprehensive ethical commitment to social justice..." (Vallaeys, 2018)
<pensamiento>
1. Trampas: Menciona "framework" y "management".
2. Checklist: No aplica escalas (No P1). Refuta la visión gerencial de mercado (No P2). Defiende la ética civil, la justicia social y formación ciudadana (Es P3).
3. Conclusión: P3_CONEXION_SOCIAL_EXTENSION.
</pensamiento>
<salida_json>
{"perspectiva": "P3_CONEXION_SOCIAL_EXTENSION", "claim_central": "Refuta las diez falacias de la RSU, fundamentando el deber ético universitario con la justicia social."}
</salida_json>
</ejemplo>
</ejemplos_referencia>

FORMATO OBLIGATORIO:
<pensamiento>
1. Trampas: [Breve]
2. Checklist: [P1 vs P2 vs P3 en 1-2 líneas]
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
    print("AUDITORÍA DE PRECISIÓN REAL (DUQUE 2019): GEMMA 4 E2B LOCAL")
    print(f"Muestra: {SAMPLE_SIZE} artículos | Tokens: 1536 | Servidor: {LM_STUDIO_URL}")
    print("=" * 80)
    
    df = pd.read_csv(INPUT_CSV)
    df_sample = df.head(SAMPLE_SIZE).copy()
    
    resultados = []
    aciertos = 0
    tiempos = []
    
    for idx, row in df_sample.iterrows():
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
        print(f"[{art_id:02d}/{SAMPLE_SIZE}] {status_icon} Real: {canonica:28s} | Pred: {pred:28s} | {latencia:4.1f}s | {titulo}...")
        
        resultados.append({
            "id": art_id,
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
    print("REPORTE ESTADÍSTICO FINAL (DATOS CRUDOS Y MATRIZ DE CONTINGENCIA)")
    print("=" * 80)
    print(f"Total evaluados:         {total}")
    print(f"Aciertos exactos:        {aciertos}/{total} ({acc:.2f}%)")
    print(f"Respuestas sintácticas:  {total - invalidas}/{total} ({(total-invalidas)/total*100:.1f}%)")
    print(f"Respuestas rotas/inválidas: {invalidas}/{total} ({invalidas/total*100:.1f}%)")
    print(f"Latencia promedio:       {lat_prom:.2f}s")
    
    print("\nMatriz de Confusión (Filas: Real | Columnas: Predicho):")
    ct = pd.crosstab(df_res["canonica"], df_res["prediccion"], margins=True)
    print(ct.to_string())
    print("=" * 80)

if __name__ == "__main__":
    main()
