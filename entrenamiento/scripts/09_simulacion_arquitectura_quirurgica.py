"""
=============================================================================
Thinkuy V3 — Simulación Realista de Arquitectura Quirúrgica (Qwen 2.5 1.5B)
=============================================================================
Simula el comportamiento del modelo operando bajo la arquitectura real de Thinkuy:
- El motor algorítmico extrae SOLO el micro-fragmento atómico (sin ruido de PDF).
- Micro-Tarea 1 (Screening): Solo el Abstract limpio (200-300 palabras).
- Micro-Tarea 3 (Auditoría de Citas): Solo el párrafo + claim literal.
- Incluye 2 ejemplos de calibración (Few-Shot) para simular el comportamiento post-entrenamiento.
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

OUTPUT_CSV = "data/auditorias_y_benchmarks/simulacion_arquitectura_quirurgica_qwen.csv"
MODEL_NAME = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"

SYSTEM_PROMPT = (
    "Eres el Modelo Epistémico Thinkuy especializado en Revisiones Sistemáticas, Scoping Reviews y Epistemología Iberoamericana. "
    "Tu tarea es analizar micro-fragmentos atómicos de artículos científicos procesados por el motor de Thinkuy.\n"
    "Debes estructurar tu respuesta SIEMPRE en dos bloques:\n"
    "1. <pensamiento>: Análisis en 3 pasos (Marcador retórico Swales/Hyland, Tradición epistémica, Criterio de descarte).\n"
    "2. <salida_json>: Objeto JSON estricto con los campos solicitados."
)

FEW_SHOT_EJEMPLOS = [
    {
        "role": "user",
        "content": (
            "Eres el Módulo Epistémico Thinkuy. Analiza el siguiente micro-fragmento atómico (RESUMEN) de ciencia-tecnologia.\n\n"
            "RESUMEN:\n"
            "Esta investigación examina el uso de plataformas virtuales en la educación superior inclusiva. "
            "Se desarrolló una revisión sistemática siguiendo directrices PRISMA en Web of Science y Scopus, analizando 35 estudios. "
            "Se concluye que las herramientas digitales reducen las brechas pedagógicas.\n\n"
            "TAREA:\n"
            "1. Clasifica el ROL METODOLÓGICO (Seminal | Síntesis_Review | Teórico_Framework | Metodológico | Empírico).\n"
            "2. Identifica la TRADICIÓN EPISTÉMICA (Hegemónica | Medicina Social | Decolonial | Ecología de Saberes | Apropiación Social | Crítica Latinoamericana).\n"
            "3. Determina su APTITUD PRISMA/JBI (Apto | Excluir | Dudoso).\n"
            "4. Identifica la FÓRMULA RETÓRICA y VERBO CLAVE.\n\n"
            "FORMATO:\n"
            "<pensamiento>\n"
            "1. Movimiento Retórico: [verbo y fórmula]\n"
            "2. Tradición Epistemológica: [tradición y motivo]\n"
            "3. Criterio de Descarte: [por qué no es otro rol]\n"
            "</pensamiento>\n"
            "<salida_json>\n"
            "{\n"
            '  "rol_metodologico": "Síntesis_Review",\n'
            '  "tradicion_epistemica": "Hegemónica",\n'
            '  "aptitud_prisma": "Apto",\n'
            '  "formula_retorica": "FORMULA_3_NEUTRALIDAD_SCOPING",\n'
            '  "verbo_clave": "examina",\n'
            '  "motivo": "Revisión documental PRISMA"\n'
            "}\n"
            "</salida_json>"
        )
    },
    {
        "role": "assistant",
        "content": (
            "<pensamiento>\n"
            "1. Movimiento Retórico: El resumen usa el marcador 'examina' bajo FORMULA_3_NEUTRALIDAD_SCOPING.\n"
            "2. Tradición Epistemológica: Se enmarca en tradición Hegemónica por su enfoque pedagógico-tecnológico estándar.\n"
            "3. Criterio de Descarte: No es Empírico porque no recolecta muestra primaria; sintetiza 35 estudios con protocolo PRISMA.\n"
            "</pensamiento>\n"
            "<salida_json>\n"
            "{\n"
            '  "rol_metodologico": "Síntesis_Review",\n'
            '  "tradicion_epistemica": "Hegemónica",\n'
            '  "aptitud_prisma": "Apto",\n'
            '  "formula_retorica": "FORMULA_3_NEUTRALIDAD_SCOPING",\n'
            '  "verbo_clave": "examina",\n'
            '  "motivo": "Revisión documental PRISMA"\n'
            "}\n"
            "</salida_json>"
        )
    }
]

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

def cargar_microfragmentos():
    casos = []
    
    # 1. Cargar estudios reales multidisciplinares (SOLO el micro-abstract limpio)
    with open("data/seleccion_18_gold_standard.json", "r", encoding="utf-8") as f:
        articulos = json.load(f)
        
    for art in articulos:
        abstract = art.get("tarea_1_abstract", {}).get("texto", "").strip()
        if not abstract:
            continue
            
        area = art.get("area", "multidisciplinar")
        casos.append({
            "id": art.get("filename", f"art_{len(casos)}"),
            "tipo_tarea": "T1_Screening_Abstract_Puro",
            "area": area,
            "esperado_rol": "Síntesis_Review",
            "esperado_aptitud": "Apto",
            "micro_texto": abstract
        })
        
        # Micro-Tarea 3: Auditoría de Citas (si tiene bloques de citación)
        citas = art.get("tarea_3_bloques_citacion", [])
        if citas and isinstance(citas, list):
            c_block = citas[0]
            parrafo = c_block.get("parrafo", "")
            claim = c_block.get("oracion_clave", "")
            if claim and parrafo:
                # Acortar párrafo para que sea un micro-fragmento quirúrgico real (<150 palabras)
                parrafo_snippet = " ".join(parrafo.split()[:120])
                casos.append({
                    "id": f"cita_{art.get('filename')}",
                    "tipo_tarea": "T3_Auditoria_Citas_Quirurgica",
                    "area": area,
                    "esperado_rol": "N/A_Cita",
                    "esperado_aptitud": "Posible adopción metodológica",
                    "micro_texto": f"PÁRRAFO:\n{parrafo_snippet}\n\nCLAIM CITADO:\n{claim}"
                })

    # Controles Negativos (Empíricos y Teóricos puros)
    casos.append({
        "id": "control_empirico_puro",
        "tipo_tarea": "T1_Screening_Abstract_Puro",
        "area": "salud-publica",
        "esperado_rol": "Empírico",
        "esperado_aptitud": "Excluir",
        "micro_texto": (
            "Se evaluó la prevalencia de hipertensión en 450 pacientes de zonas rurales mediante un diseño transversal. "
            "Se aplicaron cuestionarios y mediciones clínicas directas. Los resultados mostraron una prevalencia del 38%. "
            "Se concluye la urgencia de brigadas de atención primaria."
        )
    })
    casos.append({
        "id": "control_teorico_puro",
        "tipo_tarea": "T1_Screening_Abstract_Puro",
        "area": "filosofia-politica",
        "esperado_rol": "Teórico_Framework",
        "esperado_aptitud": "Dudoso",
        "micro_texto": (
            "Este artículo reflexiona sobre la noción de buen vivir desde la epistemología del sur. "
            "A través de un análisis conceptual de las obras de Boaventura de Sousa Santos, se discuten las limitaciones del desarrollo occidental. "
            "No se realiza trabajo empírico, sino una propuesta categorial de descolonización del saber."
        )
    })
    return casos

def main():
    print("=" * 80)
    print("SIMULACIÓN DE ARQUITECTURA QUIRÚRGICA THINKUY CON QWEN 2.5 1.5B")
    print("Micro-fragmentos atómicos limpios + Calibración de Comportamiento")
    print("=" * 80)
    
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME,
        max_seq_length=1536,
        load_in_4bit=True,
        device_map={"": 0},
    )
    FastLanguageModel.for_inference(model)
    
    casos = cargar_microfragmentos()
    print(f"\nTotal micro-fragmentos a evaluar: {len(casos)}")
    
    resultados = []
    
    for idx, c in enumerate(casos, 1):
        if c["tipo_tarea"] == "T1_Screening_Abstract_Puro":
            user_msg = (
                f"Eres el Módulo Epistémico Thinkuy. Analiza el siguiente micro-fragmento atómico (RESUMEN) en el área de {c['area']}.\n\n"
                f"RESUMEN:\n{c['micro_texto']}\n\n"
                "TAREA:\n"
                "1. Clasifica el ROL METODOLÓGICO (Seminal | Síntesis_Review | Teórico_Framework | Metodológico | Empírico).\n"
                "2. Identifica la TRADICIÓN EPISTÉMICA (Hegemónica | Medicina Social | Decolonial | Ecología de Saberes | Apropiación Social | Crítica Latinoamericana).\n"
                "3. Determina su APTITUD PRISMA/JBI (Apto | Excluir | Dudoso).\n"
                "4. Identifica la FÓRMULA RETÓRICA (según Hyland/Swales) y VERBO CLAVE.\n\n"
                "FORMATO OBLIGATORIO:\n"
                "<pensamiento>\n"
                "1. Movimiento Retórico: [verbo y fórmula]\n"
                "2. Tradición Epistemológica: [tradición y motivo]\n"
                "3. Criterio de Descarte: [por qué no es otro rol]\n"
                "</pensamiento>\n"
                "<salida_json>\n"
                "{\n"
                '  "rol_metodologico": "[Rol]",\n'
                '  "tradicion_epistemica": "[Tradición]",\n'
                '  "aptitud_prisma": "[Apto|Excluir|Dudoso]",\n'
                '  "formula_retorica": "[Fórmula]",\n'
                '  "verbo_clave": "[Verbo]",\n'
                '  "motivo": "[Máximo 15 palabras]"\n'
                "}\n"
                "</salida_json>"
            )
        else: # T3 Auditoría de Citas
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
            
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            FEW_SHOT_EJEMPLOS[0],
            FEW_SHOT_EJEMPLOS[1],
            {"role": "user", "content": user_msg}
        ]
        
        input_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([input_text], return_tensors="pt").to("cuda")
        
        t0 = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=300,
                temperature=0.05,
                use_cache=True,
                pad_token_id=tokenizer.eos_token_id
            )
        duracion = time.time() - t0
        
        gen_tokens = outputs[0][inputs.input_ids.shape[1]:]
        raw_pred = tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()
        parsed = parse_output(raw_pred)
        
        if c["tipo_tarea"] == "T1_Screening_Abstract_Puro":
            match = (parsed["rol"] == c["esperado_rol"])
            apt_match = (parsed["aptitud"] == c["esperado_aptitud"])
        else:
            match = True
            apt_match = True
            
        status_icon = "✅" if (match and parsed["status"] == "OK") else "❌"
        print(f"[{idx:02d}/{len(casos):02d}] {status_icon} {c['id'][:25]:25} | Tarea: {c['tipo_tarea'][:12]} | Pred: {parsed['rol']} (Esp: {c['esperado_rol']}) | {duracion:.2f}s")
        
        resultados.append({
            "id": c["id"],
            "tarea": c["tipo_tarea"],
            "area": c["area"],
            "esperado_rol": c["esperado_rol"],
            "pred_rol": parsed["rol"],
            "match_rol": match,
            "esperado_aptitud": c["esperado_aptitud"],
            "pred_aptitud": parsed["aptitud"],
            "match_aptitud": apt_match,
            "status_formato": parsed["status"],
            "formula_pred": parsed["formula"],
            "verbo_pred": parsed["verbo"],
            "pensamiento": parsed["pensamiento"],
            "duracion_s": round(duracion, 2),
            "raw_output": raw_pred
        })
        
    df = pd.DataFrame(resultados)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    
    t1_df = df[df["tarea"] == "T1_Screening_Abstract_Puro"]
    acc_rol = sum(t1_df["match_rol"]) / len(t1_df) * 100
    acc_fmt = sum(df["status_formato"] == "OK") / len(df) * 100
    
    print("\n" + "=" * 80)
    print("MÉTRICAS CON ARQUITECTURA QUIRÚRGICA DE THINKUY (MICRO-FRAGMENTOS):")
    print(f"  - Total Micro-Fragmentos Evaluados: {len(df)}")
    print(f"  - Validez Sintáctica Formato (JSON estricto): {sum(df['status_formato'] == 'OK')}/{len(df)} ({acc_fmt:.1f}%)")
    print(f"  - Precisión Rol Metodológico (T1 Screening): {sum(t1_df['match_rol'])}/{len(t1_df)} ({acc_rol:.1f}%)")
    print(f"  - Tiempo promedio de inferencia por micro-fragmento: {df['duracion_s'].mean():.2f} segundos")
    print(f"  - Resultados exportados a: {OUTPUT_CSV}")
    print("=" * 80)

if __name__ == "__main__":
    main()
