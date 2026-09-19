"""
=============================================================================
Thinkuy V3 — Evaluación Post-Entrenamiento (Qwen 2.5 1.5B LoRA)
=============================================================================
Carga los adaptadores LoRA entrenados (models/thinkuy_v3_qwen1.5b_lora)
y evalúa su precisión sobre los 18 estudios de scoping multidisciplinares y controles.
=============================================================================
"""

import os
import sys
import json
import re
import time
import torch
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from unsloth import FastLanguageModel

LORA_DIR = "models/thinkuy_v3_qwen1.5b_lora"
OUTPUT_CSV = "data/auditorias_y_benchmarks/auditoria_post_entrenamiento_qwen_lora.csv"

def parse_output(raw_text):
    res = {
        "status": "INVALID_OUTPUT",
        "pensamiento": "",
        "rol": "INVALID_OUTPUT",
        "tradicion": "INVALID_OUTPUT",
        "aptitud": "INVALID_OUTPUT",
        "formula": "INVALID_OUTPUT",
        "verbo": "INVALID_OUTPUT",
        "motivo": "INVALID_OUTPUT"
    }
    p_match = re.search(r"<pensamiento>(.*?)</pensamiento>", raw_text, re.DOTALL | re.IGNORECASE)
    if p_match:
        res["pensamiento"] = p_match.group(1).strip()
        
    j_match = re.search(r"<salida_json>(.*?)</salida_json>", raw_text, re.DOTALL | re.IGNORECASE)
    raw_j = ""
    if j_match:
        raw_j = j_match.group(1).strip()
    else:
        c_match = re.search(r"\{[^{}]*\}", raw_text, re.DOTALL)
        if c_match:
            raw_j = c_match.group(0).strip()
            
    if raw_j:
        try:
            d = json.loads(raw_j)
            res["rol"] = d.get("rol_metodologico", "INVALID_OUTPUT")
            res["tradicion"] = d.get("tradicion_epistemica", "INVALID_OUTPUT")
            res["aptitud"] = d.get("aptitud_prisma", "INVALID_OUTPUT")
            res["formula"] = d.get("formula_retorica", "INVALID_OUTPUT")
            res["verbo"] = d.get("verbo_clave", "INVALID_OUTPUT")
            res["motivo"] = d.get("motivo", "INVALID_OUTPUT")
            res["status"] = "OK"
        except Exception:
            res["status"] = "JSON_ERROR"
    return res

def cargar_casos():
    casos = []
    with open("data/seleccion_18_gold_standard.json", "r", encoding="utf-8") as f:
        articulos = json.load(f)
        
    for art in articulos:
        abstract = art.get("tarea_1_abstract", {}).get("texto", "").strip()
        if not abstract:
            continue
        area = art.get("area", "multidisciplinar")
        casos.append({
            "id": art.get("filename", f"art_{len(casos)}"),
            "tipo_tarea": "T1_Screening",
            "area": area,
            "esperado_rol": "Síntesis_Review",
            "esperado_aptitud": "Apto",
            "micro_texto": abstract
        })
        
        citas = art.get("tarea_3_bloques_citacion", [])
        if citas and isinstance(citas, list):
            c_block = citas[0]
            parrafo = c_block.get("parrafo", "")
            claim = c_block.get("oracion_clave", "")
            if claim and parrafo:
                parrafo_snip = " ".join(parrafo.split()[:120])
                casos.append({
                    "id": f"cita_{art.get('filename')}",
                    "tipo_tarea": "T3_Citas",
                    "area": area,
                    "esperado_rol": "N/A_Cita",
                    "esperado_aptitud": "Posible adopción metodológica",
                    "micro_texto": f"PÁRRAFO:\n{parrafo_snip}\n\nCLAIM CITADO:\n{claim}"
                })

    # Controles
    casos.append({
        "id": "control_empirico",
        "tipo_tarea": "T1_Screening",
        "area": "salud-publica",
        "esperado_rol": "Empírico",
        "esperado_aptitud": "Excluir",
        "micro_texto": "Se evaluó la eficacia de un nuevo protocolo clínico en 180 pacientes hospitalizados. Ensayo aleatorizado de dos brazos."
    })
    casos.append({
        "id": "control_teorico",
        "tipo_tarea": "T1_Screening",
        "area": "filosofia",
        "esperado_rol": "Teórico_Framework",
        "esperado_aptitud": "Dudoso",
        "micro_texto": "Este ensayo discute las bases conceptuales de la bioética latinoamericana a partir de una revisión teórica reflexiva."
    })
    return casos

def main():
    print("=" * 80)
    print("EVALUACIÓN POST-ENTRENAMIENTO: QWEN 2.5 1.5B LoRA (THINKUY V3)")
    print(f"Cargando LoRA desde: {LORA_DIR}")
    print("=" * 80)
    
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=LORA_DIR,
        max_seq_length=1536,
        load_in_4bit=True,
        device_map={"": 0},
    )
    FastLanguageModel.for_inference(model)
    
    casos = cargar_casos()
    print(f"Total casos a evaluar: {len(casos)}")
    
    resultados = []
    for idx, c in enumerate(casos, 1):
        if c["tipo_tarea"] == "T1_Screening":
            user_msg = (
                f"Eres el Módulo Epistémico Thinkuy. Analiza el siguiente resumen de un artículo científico en el área de {c['area']}.\n\n"
                f"RESUMEN:\n{c['micro_texto']}\n\n"
                "TAREA:\n"
                "1. Clasifica el ROL METODOLÓGICO principal del estudio.\n"
                "2. Identifica la TRADICIÓN EPISTÉMICA desde la que opera.\n"
                "3. Determina su APTITUD PRISMA/JBI (Apto | Excluir | Dudoso).\n"
                "4. Identifica el VERBO CLAVE y la FÓRMULA RETÓRICA (según Hyland/Swales).\n\n"
                "FORMATO OBLIGATORIO:\n"
                "<pensamiento>\n"
                "1. Movimiento Retórico y Marcador: [Identificar verbo y fórmula]\n"
                "2. Tradición Epistemológica: [Identificar tradición y justificar]\n"
                "3. Criterio de Descarte: [Justificación de exclusión de otros roles]\n"
                "</pensamiento>\n"
                "<salida_json>\n"
                "{\n"
                '  "rol_metodologico": "[Seminal | Síntesis_Review | Teórico_Framework | Metodológico | Empírico]",\n'
                '  "tradicion_epistemica": "[Hegemónica | Medicina Social | Decolonial | Ecología de Saberes | Apropiación Social | Crítica Latinoamericana]",\n'
                '  "aptitud_prisma": "[Apto | Excluir | Dudoso]",\n'
                '  "formula_retorica": "[Fórmula Hyland]",\n'
                '  "verbo_clave": "[Verbo principal]",\n'
                '  "motivo": "[Máximo 15 palabras]"\n'
                "}\n"
                "</salida_json>"
            )
        else:
            user_msg = (
                f"Eres el Módulo de Auditoría de Citas Thinkuy. Analiza el siguiente micro-fragmento de citación en el área de {c['area']}.\n\n"
                f"{c['micro_texto']}\n\n"
                "TAREA:\n"
                "Clasifica la función retórica de la cita entre:\n"
                "- Posible consenso\n"
                "- Posible disenso\n"
                "- Posible adopción metodológica\n"
                "- Posible mención contextual\n\n"
                "FORMATO OBLIGATORIO:\n"
                "<pensamiento>\n"
                "1. Función Retórica de la Cita: [justificación breve]\n"
                "</pensamiento>\n"
                "<salida_json>\n"
                "{\n"
                '  "tipo_cita": "[Posible consenso | Posible disenso | Posible adopción metodológica | Posible mención contextual]",\n'
                '  "justificacion": "[Máximo 15 palabras]"\n'
                "}\n"
                "</salida_json>"
            )
            
        sys_prompt = (
            "Eres el Modelo Epistémico Thinkuy especializado en Revisiones Sistemáticas, "
            "Scoping Reviews y Epistemología Iberoamericana. Analiza con rigor lingüístico (Hyland / Swales) "
            "y genera siempre un bloque de razonamiento <pensamiento> estructurado antes de la salida estricta <salida_json>."
        )
        
        msgs = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg}
        ]
        
        input_text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([input_text], return_tensors="pt").to("cuda")
        
        t0 = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=250,
                temperature=0.05,
                use_cache=True,
                pad_token_id=tokenizer.eos_token_id
            )
        dur = time.time() - t0
        
        gen_tok = outputs[0][inputs.input_ids.shape[1]:]
        raw = tokenizer.decode(gen_tok, skip_special_tokens=True).strip()
        p = parse_output(raw)
        
        match = (p["rol"] == c["esperado_rol"]) if c["tipo_tarea"] == "T1_Screening" else True
        icon = "✅" if (match and p["status"] == "OK") else "❌"
        print(f"[{idx:02d}/{len(casos):02d}] {icon} {c['id'][:25]:25} | Rol: {p['rol']:16} (Esp: {c['esperado_rol']}) | FMT: {p['status']} | {dur:.2f}s")
        
        resultados.append({
            "id": c["id"],
            "tarea": c["tipo_tarea"],
            "area": c["area"],
            "esperado_rol": c["esperado_rol"],
            "pred_rol": p["rol"],
            "match_rol": match,
            "status_formato": p["status"],
            "formula_pred": p["formula"],
            "verbo_pred": p["verbo"],
            "pensamiento": p["pensamiento"],
            "duracion_s": round(dur, 2),
            "raw": raw
        })
        
    df = pd.DataFrame(resultados)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    
    t1_df = df[df["tarea"] == "T1_Screening"]
    fmt_ok = sum(df["status_formato"] == "OK") / len(df) * 100
    rol_ok = sum(t1_df["match_rol"]) / len(t1_df) * 100
    
    print("\n" + "=" * 80)
    print("MÉTRICAS DEL MODELO ENTRENADO (QWEN 2.5 1.5B LoRA):")
    print(f"  - Total Casos Evaluados: {len(df)}")
    print(f"  - Validez Sintáctica Formato: {sum(df['status_formato'] == 'OK')}/{len(df)} ({fmt_ok:.1f}%)")
    print(f"  - Precisión Rol Metodológico T1: {sum(t1_df['match_rol'])}/{len(t1_df)} ({rol_ok:.1f}%)")
    print(f"  - Tiempo Promedio Inferencia: {df['duracion_s'].mean():.2f}s")
    print(f"  - CSV Guardado en: {OUTPUT_CSV}")
    print("=" * 80)

if __name__ == "__main__":
    main()
