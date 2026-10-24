import os
import sys
import re
import json
import time
import torch
import pandas as pd
from tqdm import tqdm
from unsloth import FastLanguageModel

# ==========================================
# 1. CONFIGURACIÓN DE RUTAS Y PARÁMETROS
# ==========================================
BASE_MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct"
LORA_ADAPTER_PATH = "models/thinkuy"
INPUT_CSV = "data/auditorias_y_benchmarks/resultados_pruebas_modelos_333.csv"
OUTPUT_CSV = "data/auditorias_y_benchmarks/resultados_thinkuy_v2_inferencia.csv"

MAX_SEQ_LENGTH = 2048  # Suficiente para abstracts largos + CoT
TEMPERATURE = 0.3      # Baja temperatura para razonamiento epistémico determinista (sin creatividad)
TOP_P = 0.9
REPETITION_PENALTY = 1.15  # Evita que el modelo se atasque en bucles
MAX_NEW_TOKENS = 350   # Espacio suficiente para checklist CoT + JSON

# ==========================================
# 2. CARGA DEL MODELO (Optimizado para 8GB VRAM)
# ==========================================
print("=" * 80)
print("🚀 THINKUY V2 — INFERENCIA MASIVA Y AUDITORÍA EPISTÉMICA")
print(f"Modelo base: {BASE_MODEL_NAME} | Adaptador LoRA: {LORA_ADAPTER_PATH}")
print(f"Dispositivo: {'CUDA (GPU ' + torch.cuda.get_device_name(0) + ')' if torch.cuda.is_available() else 'CPU'}")
print("=" * 80)

print("\n🔄 Cargando modelo y adaptador LoRA (4-bit)...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=LORA_ADAPTER_PATH,
    max_seq_length=MAX_SEQ_LENGTH,
    load_in_4bit=True,
    dtype=None,
)
FastLanguageModel.for_inference(model)
print("✅ Modelo thinkuy cargado exitosamente en VRAM.")

# ==========================================
# 3. FUNCIONES DE PROMPT Y PARSING
# ==========================================
def build_prompt(title_text, abstract_text):
    """Construye el prompt usando el Chat Template nativo de Qwen2.5"""
    content = (
        f"Analiza epistémicamente este artículo sobre Responsabilidad Social Universitaria (RSU) "
        f"y clasifícalo en P1, P2 o P3 según Duque & Cervantes (2019).\n\n"
        f"Título: {title_text}\n"
        f"Abstract: {abstract_text}"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Eres un asistente epistemológico y metodológico experto en revisiones sistemáticas, "
                "bibliometría y taxonomías de investigación. Tu tarea es analizar abstracts con rigor crítico "
                "siguiendo un checklist de tres preguntas antes de clasificar:\n"
                "1. ¿El estudio aplica empíricamente encuestas, cuestionarios o validación psicométrica de escalas propias (P1)?\n"
                "2. ¿El estudio propone o analiza modelos de gobernanza directiva, gestión institucional, políticas o stakeholders (P2)?\n"
                "3. ¿El estudio se centra en ética civil, derechos humanos, aprendizaje-servicio o compromiso comunitario (P3)?\n\n"
                "Responde con este formato estricto:\n"
                "<pensamiento>\n"
                "[Checklist de las 3 preguntas analizadas en orden y conclusión]\n"
                "</pensamiento>\n"
                "<salida_json>\n"
                "{\"perspectiva\": \"P1_MEDICION_ESCALAS|P2_ESTRATEGICO_STAKEHOLDERS|P3_CONEXION_SOCIAL_EXTENSION\", "
                "\"rol\": \"empirical|seminal|methodological|review_synthesis\", "
                "\"claim_central\": \"tesis o aporte central resumido\"}\n"
                "</salida_json>"
            )
        },
        {"role": "user", "content": content}
    ]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

def parse_output(raw_text):
    """Extrae de forma robusta el pensamiento y el JSON con limpieza anti-markdown."""
    pensamiento = ""
    salida_json_str = ""
    perspectiva = "DESCONOCIDA"
    rol = "empirical"
    claim_central = ""

    # Extraer pensamiento
    p_match = re.search(r"<pensamiento>(.*?)</pensamiento>", raw_text, re.DOTALL | re.IGNORECASE)
    if p_match:
        pensamiento = p_match.group(1).strip()
    elif "</think>" in raw_text:
        pensamiento = raw_text.split("</think>")[0].replace("<think>", "").strip()

    # Extraer bloque de salida JSON
    j_match = re.search(r"<salida_json>(.*?)</salida_json>", raw_text, re.DOTALL | re.IGNORECASE)
    if j_match:
        salida_json_str = j_match.group(1).strip()
    else:
        # Fallback: buscar el primer bloque json
        fb_match = re.search(r"(\{.*?\})", raw_text, re.DOTALL)
        if fb_match:
            salida_json_str = fb_match.group(1).strip()

    # Limpieza anti-markdown: remover ```json ... ``` y comillas problemáticas
    salida_clean = re.sub(r"^```(?:json)?\s*", "", salida_json_str, flags=re.IGNORECASE)
    salida_clean = re.sub(r"\s*```$", "", salida_clean)
    salida_clean = salida_clean.strip()

    try:
        data = json.loads(salida_clean)
        perspectiva = data.get("perspectiva", "")
        rol = data.get("rol", "")
        claim_central = data.get("claim_central", "")
    except Exception:
        # Extracción por regex si json.loads falla
        m_persp = re.search(r'["\']perspectiva["\']\s*:\s*["\'](.*?)["\']', raw_text, re.IGNORECASE)
        if m_persp:
            perspectiva = m_persp.group(1).strip()
        m_rol = re.search(r'["\']rol["\']\s*:\s*["\'](.*?)["\']', raw_text, re.IGNORECASE)
        if m_rol:
            rol = m_rol.group(1).strip()
        m_claim = re.search(r'["\']claim_central["\']\s*:\s*["\'](.*?)["\']', raw_text, re.IGNORECASE)
        if m_claim:
            claim_central = m_claim.group(1).strip()

    # Normalización de perspectiva
    persp_upper = perspectiva.upper()
    if "P1" in persp_upper or "MEDICION" in persp_upper or "ESCALAS" in persp_upper:
        persp_norm = "P1_MEDICION_ESCALAS"
    elif "P2" in persp_upper or "ESTRATEGICO" in persp_upper or "STAKEHOLDER" in persp_upper or "GESTION" in persp_upper:
        persp_norm = "P2_ESTRATEGICO_STAKEHOLDERS"
    elif "P3" in persp_upper or "SOCIAL" in persp_upper or "EXTENSION" in persp_upper or "ETICA" in persp_upper:
        persp_norm = "P3_CONEXION_SOCIAL_EXTENSION"
    else:
        persp_norm = "P2_ESTRATEGICO_STAKEHOLDERS"  # Default conservador

    return {
        "perspectiva": persp_norm,
        "rol": rol or "empirical",
        "pensamiento": pensamiento,
        "claim_central": claim_central,
        "raw": raw_text
    }

# ==========================================
# 4. EJECUCIÓN DEL LOTE DE INFERENCIA
# ==========================================
def main():
    if not os.path.exists(INPUT_CSV):
        print(f"❌ Error: Archivo de entrada no encontrado en '{INPUT_CSV}'.")
        return

    print(f"📖 Leyendo dataset desde: {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    total_records = len(df)
    print(f"📊 Total de abstracts a procesar: {total_records}")

    results_perspectiva = []
    results_rol = []
    results_pensamiento = []
    results_claim = []
    results_latencia = []
    results_raw = []

    print("\n⚡ Iniciando inferencia en lote (333 abstracts)...")
    progress_bar = tqdm(total=total_records, desc="Inferencia Thinkuy v2", unit="art")

    start_all = time.time()
    for idx, row in df.iterrows():
        title = str(row.get("title", "")).strip()
        abstract = str(row.get("abstract", "")).strip()
        if not abstract or abstract.lower() == "nan":
            abstract = title

        prompt_str = build_prompt(title, abstract)
        inputs = tokenizer([prompt_str], return_tensors="pt").to("cuda")

        t0 = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                use_cache=True,
                temperature=TEMPERATURE,
                top_p=TOP_P,
                repetition_penalty=REPETITION_PENALTY,
                pad_token_id=tokenizer.eos_token_id,
            )
        lat = round(time.time() - t0, 2)

        gen_tokens = outputs[0][inputs.input_ids.shape[1]:]
        raw_output = tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()

        parsed = parse_output(raw_output)

        results_perspectiva.append(parsed["perspectiva"])
        results_rol.append(parsed["rol"])
        results_pensamiento.append(parsed["pensamiento"])
        results_claim.append(parsed["claim_central"])
        results_latencia.append(lat)
        results_raw.append(parsed["raw"])

        progress_bar.update(1)
        progress_bar.set_postfix({
            "id": row.get("id", idx + 1),
            "persp": parsed["perspectiva"].split("_")[0],
            "lat": f"{lat}s"
        })

    progress_bar.close()
    elapsed_total = round(time.time() - start_all, 1)
    print(f"\n⏱️ Inferencia completada en {elapsed_total}s (promedio: {elapsed_total / total_records:.2f}s/artículo).")

    # Inyectar columnas nuevas de Thinkuy v2 en el DataFrame
    df["thinkuy_v2_perspectiva"] = results_perspectiva
    df["thinkuy_v2_rol"] = results_rol
    df["thinkuy_v2_pensamiento"] = results_pensamiento
    df["thinkuy_v2_claim_central"] = results_claim
    df["thinkuy_v2_latencia_seg"] = results_latencia
    df["thinkuy_v2_raw"] = results_raw

    # Evaluar acierto inmediato frente a la referencia canónica si existe la columna
    if "referencia_canonica_perspectiva" in df.columns:
        df["thinkuy_v2_acierto"] = df.apply(
            lambda r: "ACIERTO" if str(r["thinkuy_v2_perspectiva"]) == str(r["referencia_canonica_perspectiva"]) else "FALLO",
            axis=1
        )
        aciertos_v2 = (df["thinkuy_v2_acierto"] == "ACIERTO").sum()
        pct_v2 = aciertos_v2 / total_records * 100
        print(f"\n🎯 [AVANCE PRELIMINAR] Exactitud frente a Duque & Cervantes (2019):")
        print(f"   Aciertos: {aciertos_v2}/{total_records} ({pct_v2:.2f}%)")

    # Guardar CSV resultante
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n💾 Archivo de resultados guardado en: {OUTPUT_CSV}")
    print("=" * 80)

if __name__ == "__main__":
    main()
