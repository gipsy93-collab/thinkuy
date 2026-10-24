"""
=============================================================================
Thinkuy V3 - Evaluación del Modelo Soberano 'thinkuy' (Qwen 1.5B LoRA)
sobre los 20 Casos Complejos de Duque 2019
=============================================================================
Carga los adaptadores LoRA de 'models/thinkuy' en modo inferencia (1.5 GB VRAM)
y prueba si con las reglas del protocolo Hyland/Swales el modelo supera su
sesgo previo y rescata los casos complejos.
=============================================================================
"""

import os
import sys
import json
import time
import re
import torch
import pandas as pd
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from unsloth import FastLanguageModel

MODEL_PATH = "models/thinkuy"
INPUT_CSV = "data/auditorias_y_benchmarks/resultados_pruebas_modelos_333.csv"
OUTPUT_CSV = "data/auditorias_y_benchmarks/evaluacion_thinkuy_lora_20_complejos.csv"

# 20 Casos Complejos Canónicos de Duque 2019
IDS_COMPLEJOS = [
    2, 3, 4, 5, 6, 8, 12, 14, 16, 18, 19, 32, 36, 50, 52, 82, 92, 114, 126, 146
]

STEERING_PROMPT = """Eres el Módulo Epistémico Thinkuy especializado en cienciometría de RSU (Duque & Cervantes, 2019).
Clasifica el artículo científico en su PERSPECTIVA CANÓNICA EXACTA aplicando la lógica sintáctica de Ken Hyland y John Swales:

TAXONOMÍA CANÓNICA:
1. P1_MEDICION_ESCALAS: Enfoque empírico cuantitativo, diseño o aplicación de escalas psicométricas, cuestionarios, análisis factorial (SEM/PLS).
2. P2_ESTRATEGICO_STAKEHOLDERS: Modelos de gestión directiva, gobernanza institucional, políticas, stakeholders, análisis bibliométricos.
3. P3_CONEXION_SOCIAL_EXTENSION: Intervención comunitaria directa, aprendizaje-servicio, formación ciudadana, ética cívica, justicia social.

FORMATO OBLIGATORIO:
<pensamiento>
1. Trampas: [Breve]
2. Checklist Hyland / Swales: [P1 vs P2 vs P3 en 1-2 líneas]
3. Conclusión: [P1_MEDICION_ESCALAS | P2_ESTRATEGICO_STAKEHOLDERS | P3_CONEXION_SOCIAL_EXTENSION]
</pensamiento>
<salida_json>
{
  "perspectiva": "P1_MEDICION_ESCALAS" | "P2_ESTRATEGICO_STAKEHOLDERS" | "P3_CONEXION_SOCIAL_EXTENSION",
  "claim_central": "[Máximo 20 palabras]"
}
</salida_json>"""

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
    print("EVALUACIÓN DEL MODELO SOBERANO 'thinkuy' (Qwen 1.5B LoRA V2)")
    print(f"Ruta: {MODEL_PATH} | Modo: FastLanguageModel.for_inference en GPU")
    print("=" * 80)
    
    # 1. Cargar modelo y tokenizer
    print("\n[1/3] Cargando pesos y adaptadores LoRA de 'thinkuy'...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_PATH,
        max_seq_length=1536,
        load_in_4bit=True,
        device_map={"": 0},
    )
    FastLanguageModel.for_inference(model)
    print(f"VRAM utilizada tras carga: {torch.cuda.memory_allocated(0)/1024**3:.2f} GB / {torch.cuda.get_device_properties(0).total_memory/1024**3:.2f} GB")
    
    # 2. Cargar casos complejos
    df = pd.read_csv(INPUT_CSV)
    df_complejos = df[df["id"].isin(IDS_COMPLEJOS)].copy()
    df_complejos["sort_key"] = df_complejos["id"].map(lambda x: IDS_COMPLEJOS.index(x) if x in IDS_COMPLEJOS else 999)
    df_complejos = df_complejos.sort_values("sort_key").reset_index(drop=True)
    
    print(f"\n[2/3] Evaluando {len(df_complejos)} casos complejos con el protocolo Hyland/Swales...\n")
    
    resultados = []
    aciertos = 0
    tiempos = []
    
    for idx, row in df_complejos.iterrows():
        art_id = row["id"]
        titulo = str(row["title"])[:55]
        abstract = str(row["abstract"])
        canonica = str(row["referencia_canonica_perspectiva"]).strip()
        
        user_content = f"Abstract a clasificar (ID {art_id}):\n\"{abstract}\""
        
        messages = [
            {"role": "system", "content": STEERING_PROMPT},
            {"role": "user", "content": user_content}
        ]
        
        prompt_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt_text, return_tensors="pt").to("cuda")
        
        t0 = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.1,
                use_cache=True,
                pad_token_id=tokenizer.eos_token_id
            )
        elapsed = time.time() - t0
        
        raw_resp = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        pensamiento, pred, claim = parse_strict_output(raw_resp)
        
        es_acierto = (pred == canonica)
        if es_acierto:
            aciertos += 1
            
        tiempos.append(elapsed)
        status_icon = "✅" if es_acierto else "❌"
        print(f"[{idx+1:02d}/{len(df_complejos)}] (ID {art_id:03d}) {status_icon} Real: {canonica:28s} | Pred: {pred:28s} | {elapsed:4.2f}s | {titulo}...")
        
        resultados.append({
            "num_muestra": idx + 1,
            "id_original": art_id,
            "title": row["title"],
            "canonica": canonica,
            "prediccion": pred,
            "acierto": 1 if es_acierto else 0,
            "latencia_seg": round(elapsed, 2),
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
    invalidas = dist_pred.get("INVALID_OUTPUT", 0)
    
    print("\n" + "=" * 80)
    print("REPORTE FINAL: MODELO 'thinkuy' (Qwen 1.5B LoRA V2) SOBRE CASOS COMPLEJOS")
    print("=" * 80)
    print(f"Total Casos Evaluados:         {total}")
    print(f"Aciertos Estrictos:            {aciertos}/{total} ({acc:.2f}%)")
    print(f"Respuestas Válidas Sintaxis:   {total - invalidas}/{total} ({(total-invalidas)/total*100:.1f}%)")
    print(f"Respuestas Inválidas:          {invalidas}/{total} ({invalidas/total*100:.1f}%)")
    print(f"Latencia Promedio por Caso:    {lat_prom:.2f}s (Ultra veloz en GPU)")
    print(f"VRAM Pico Consumida:           {torch.cuda.max_memory_allocated(0)/1024**3:.2f} GB")
    
    print("\nMatriz de Confusión (Filas: Real Canónica | Columnas: Predicha por 'thinkuy'):")
    ct = pd.crosstab(df_res["canonica"], df_res["prediccion"], margins=True)
    print(ct.to_string())
    print("=" * 80)
    print(f"Archivo persistido en: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
