"""
Script de Evaluación Rigurosa y Cero-Fallbacks:
Google Gemma 4 E2B frente a la Referencia Canónica de Duque & Cervantes (2019).
Conexión directa vía LM Studio API (http://127.0.0.1:1234/v1/chat/completions).
"""

import sys
import os
import json
import time
import re
import urllib.request
import pandas as pd
from tqdm import tqdm

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

INPUT_CSV = "data/auditorias_y_benchmarks/resultados_pruebas_modelos_333.csv"
OUTPUT_CSV = "data/auditorias_y_benchmarks/resultados_gemma4_e2b_duque333.csv"
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL_ID = "google/gemma-4-e2b"

SYSTEM_PROMPT = """Eres un metodólogo y cienciometrista experto. Tu labor es clasificar el artículo científico sobre Responsabilidad Social Universitaria (RSU) a partir de su abstract en una de las tres perspectivas canónicas de Duque & Cervantes (2019):
- P1_MEDICION_ESCALAS: Enfoque empírico cuantitativo, diseño o aplicación de escalas psicométricas, cuestionarios, análisis factorial (SEM) o baremos de medición propios.
- P2_ESTRATEGICO_STAKEHOLDERS: Enfoque de gobernanza institucional, políticas de dirección, modelos organizacionales, gestión estratégica o memorias de sostenibilidad frente a stakeholders.
- P3_CONEXION_SOCIAL_EXTENSION: Enfoque en ética civil, formación ciudadana, justicia social, derechos humanos, programas de aprendizaje-servicio o impacto comunitario directo.

Instrucción de formato:
Analiza el abstract cuidadosamente y emite ÚNICAMENTE un objeto JSON válido con esta estructura:
{
  "perspectiva": "P1_MEDICION_ESCALAS" o "P2_ESTRATEGICO_STAKEHOLDERS" o "P3_CONEXION_SOCIAL_EXTENSION",
  "justificacion": "explicación concisa de 15 a 25 palabras de la decisión metodológica",
  "claim_central": "tesis o aporte central del manuscrito"
}"""

def parse_gemma_response(content_str):
    """
    Parsea de forma estricta la salida de Gemma 4.
    REGLA DE ORO DE RIGOR: CERO FALLBACKS.
    Si la perspectiva no es explícita y válida, se marca como INVALID_OUTPUT (FALLO).
    """
    clean = re.sub(r"^```(?:json)?\s*", "", content_str.strip(), flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    clean = clean.strip()
    
    persp = "INVALID_OUTPUT"
    justificacion = ""
    claim = ""
    is_valid_json = False

    try:
        data = json.loads(clean)
        raw_p = str(data.get("perspectiva", "")).strip()
        justificacion = str(data.get("justificacion", "")).strip()
        claim = str(data.get("claim_central", "")).strip()
        is_valid_json = True
    except Exception:
        # Fallback de regex solo para extraer la clave si el JSON tuvo caracteres sueltos
        m_p = re.search(r'["\']perspectiva["\']\s*:\s*["\'](.*?)["\']', content_str, re.IGNORECASE)
        raw_p = m_p.group(1).strip() if m_p else ""
        m_j = re.search(r'["\']justificacion["\']\s*:\s*["\'](.*?)["\']', content_str, re.IGNORECASE)
        justificacion = m_j.group(1).strip() if m_j else ""
        m_c = re.search(r'["\']claim_central["\']\s*:\s*["\'](.*?)["\']', content_str, re.IGNORECASE)
        claim = m_c.group(1).strip() if m_c else ""

    # VALIDACIÓN ESTRICTA: Sin asignaciones automáticas ni trampas
    if raw_p == "P1_MEDICION_ESCALAS" or raw_p == "P1":
        persp = "P1_MEDICION_ESCALAS"
    elif raw_p == "P2_ESTRATEGICO_STAKEHOLDERS" or raw_p == "P2":
        persp = "P2_ESTRATEGICO_STAKEHOLDERS"
    elif raw_p == "P3_CONEXION_SOCIAL_EXTENSION" or raw_p == "P3":
        persp = "P3_CONEXION_SOCIAL_EXTENSION"
    else:
        # Penalización directa si la salida no corresponde a la taxonomía
        persp = "INVALID_OUTPUT"

    return {
        "perspectiva": persp,
        "justificacion": justificacion,
        "claim": claim,
        "is_valid_json": is_valid_json
    }

def call_gemma(title, abstract, timeout=45):
    user_msg = f"Título: {title}\nAbstract: {abstract}"
    payload = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.1,
        "max_tokens": 800
    }
    
    req = urllib.request.Request(
        LM_STUDIO_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data["choices"][0]["message"]
            thinking = choice.get("reasoning_content", "")
            content = choice.get("content", "")
            latency = round(time.time() - t0, 2)
            return thinking, content, latency, True
    except Exception as e:
        latency = round(time.time() - t0, 2)
        return "", f"ERROR: {str(e)}", latency, False

def main():
    print("=" * 85)
    print("🔬 AUDITORÍA RIGUROSA ZERO-FALLBACK: GOOGLE GEMMA 4 E2B")
    print(f"Endpoint: {LM_STUDIO_URL} | Modelo: {MODEL_ID}")
    print(f"Dataset de evaluación: {INPUT_CSV} (333 abstracts)")
    print("=" * 85)

    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    total = len(df)

    gemma_persp = []
    gemma_thinking = []
    gemma_justificacion = []
    gemma_claim = []
    gemma_latencia = []
    gemma_raw = []
    gemma_acierto = []

    hits = 0
    invalid_format = 0

    pbar = tqdm(total=total, desc="Gemma 4 E2B Inference", unit="art")

    for idx, row in df.iterrows():
        title = str(row.get("title", "")).strip()
        abstract = str(row.get("abstract", "")).strip()
        if not abstract or abstract.lower() == "nan":
            abstract = title
        
        gold = str(row.get("referencia_canonica_perspectiva", "")).strip()

        thinking, content, lat, ok = call_gemma(title, abstract)
        parsed = parse_gemma_response(content)

        p_norm = parsed["perspectiva"]
        is_hit = (p_norm == gold and p_norm != "INVALID_OUTPUT")
        
        if is_hit:
            hits += 1
        if p_norm == "INVALID_OUTPUT":
            invalid_format += 1

        acierto_str = "ACIERTO" if is_hit else "FALLO"

        gemma_persp.append(p_norm)
        gemma_thinking.append(thinking)
        gemma_justificacion.append(parsed["justificacion"])
        gemma_claim.append(parsed["claim"])
        gemma_latencia.append(lat)
        gemma_raw.append(content)
        gemma_acierto.append(acierto_str)

        pbar.update(1)
        pbar.set_postfix({
            "id": row.get("id", idx + 1),
            "persp": p_norm.split("_")[0],
            "hits": f"{hits}/{idx+1}",
            "acc": f"{hits/(idx+1)*100:.1f}%",
            "inv": invalid_format
        })

        # Guardado incremental de seguridad cada 15 artículos
        if (idx + 1) % 15 == 0 or (idx + 1) == total:
            temp_df = df.copy()
            curr_len = len(gemma_persp)
            temp_df = temp_df.iloc[:curr_len].copy()
            temp_df["gemma4_perspectiva"] = gemma_persp
            temp_df["gemma4_acierto"] = gemma_acierto
            temp_df["gemma4_thinking"] = gemma_thinking
            temp_df["gemma4_justificacion"] = gemma_justificacion
            temp_df["gemma4_claim"] = gemma_claim
            temp_df["gemma4_latencia_seg"] = gemma_latencia
            temp_df["gemma4_raw"] = gemma_raw
            temp_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    pbar.close()

    print("\n" + "=" * 85)
    print("🏁 EVALUACIÓN COMPLETADA CON ÉXITO")
    print(f"- Total artículos evaluados: {total}")
    print(f"- Aciertos estrictos frente a Duque (2019): {hits}/{total} ({hits/total*100:.2f}%)")
    print(f"- Errores de formato / Salidas no taxonómicas: {invalid_format}/{total} ({invalid_format/total*100:.2f}%)")
    print(f"- Archivo definitivo guardado en: {OUTPUT_CSV}")
    print("=" * 85)

if __name__ == "__main__":
    main()
