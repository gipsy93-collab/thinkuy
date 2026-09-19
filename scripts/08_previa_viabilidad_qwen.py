"""
=============================================================================
Thinkuy V3 — Previa de Viabilidad y Comportamiento Base (Qwen 2.5 1.5B)
=============================================================================
Evalúa el modelo virgen (sin LoRA / fine-tuning) contra:
1. Muestra del dataset de entrenamiento (Gold Standard ChatML).
2. Casos reales de revisiones y scoping multidisciplinares descargadas.
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

OUTPUT_CSV = "data/auditorias_y_benchmarks/auditoria_previa_qwen_1.5b.csv"
MODEL_NAME = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
MAX_SEQ_LENGTH = 1024

def parse_thinkuy_output(raw_text):
    """Parsea el bloque de pensamiento y el bloque JSON con rigor anti-sycophancy."""
    res = {
        "status_formato": "INVALID_OUTPUT",
        "pensamiento": "",
        "rol_metodologico": "INVALID_OUTPUT",
        "tradicion_epistemica": "INVALID_OUTPUT",
        "aptitud_prisma": "INVALID_OUTPUT",
        "formula_retorica": "INVALID_OUTPUT",
        "verbo_clave": "INVALID_OUTPUT",
        "motivo": "INVALID_OUTPUT",
        "raw_json": ""
    }
    
    # 1. Extraer <pensamiento>
    p_match = re.search(r"<pensamiento>(.*?)</pensamiento>", raw_text, re.DOTALL | re.IGNORECASE)
    if p_match:
        res["pensamiento"] = p_match.group(1).strip()
    
    # 2. Extraer <salida_json>
    j_match = re.search(r"<salida_json>(.*?)</salida_json>", raw_text, re.DOTALL | re.IGNORECASE)
    raw_json_str = ""
    if j_match:
        raw_json_str = j_match.group(1).strip()
    else:
        # Fallback de búsqueda de objeto JSON si no hay tags
        curly_match = re.search(r"\{[^{}]*\}", raw_text, re.DOTALL)
        if curly_match:
            raw_json_str = curly_match.group(0).strip()
            
    res["raw_json"] = raw_json_str
    
    if raw_json_str:
        try:
            data = json.loads(raw_json_str)
            res["rol_metodologico"] = data.get("rol_metodologico", "INVALID_OUTPUT")
            res["tradicion_epistemica"] = data.get("tradicion_epistemica", "INVALID_OUTPUT")
            res["aptitud_prisma"] = data.get("aptitud_prisma", "INVALID_OUTPUT")
            res["formula_retorica"] = data.get("formula_retorica", "INVALID_OUTPUT")
            res["verbo_clave"] = data.get("verbo_clave", "INVALID_OUTPUT")
            res["motivo"] = data.get("motivo", "INVALID_OUTPUT")
            res["status_formato"] = "OK"
        except Exception as e:
            res["status_formato"] = f"JSON_DECODE_ERROR: {str(e)[:40]}"
            
    return res

def cargar_casos_evaluacion():
    casos = []
    
    # 1. Cargar del dataset ChatML
    chatml_file = "data/thinkuy_v3_gold_standard_chatml.jsonl"
    if os.path.exists(chatml_file):
        with open(chatml_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 8: # Primeros 8 casos del dataset de entrenamiento
                    break
                row = json.loads(line)
                msgs = row["messages"]
                sys_prompt = msgs[0]["content"]
                usr_prompt = msgs[1]["content"]
                esperado = parse_thinkuy_output(msgs[2]["content"])
                
                casos.append({
                    "origen": "Dataset_ChatML_GoldStandard",
                    "id": f"chatml_{i+1}",
                    "area": "variada",
                    "esperado_rol": esperado["rol_metodologico"],
                    "esperado_aptitud": esperado["aptitud_prisma"],
                    "system_prompt": sys_prompt,
                    "user_prompt": usr_prompt
                })

    # 2. Cargar revisiones multidisciplinares reales de seleccion_18_gold_standard.json
    multidisciplinar_file = "data/seleccion_18_gold_standard.json"
    if os.path.exists(multidisciplinar_file):
        with open(multidisciplinar_file, "r", encoding="utf-8") as f:
            articulos = json.load(f)
            
        sys_prompt_def = (
            "Eres el Modelo Epistémico Thinkuy especializado en Revisiones Sistemáticas, "
            "Scoping Reviews y Epistemología Iberoamericana. Analiza con rigor lingüístico (Hyland / Swales) "
            "y genera siempre un bloque de razonamiento <pensamiento> estructurado antes de la salida estricta <salida_json>."
        )
        
        # Tomar hasta 6 artículos de diferentes áreas temáticas
        for idx, art in enumerate(articulos[:6]):
            abstract = art.get("tarea_1_abstract", {}).get("texto", "")
            area = art.get("area", "multidisciplinar")
            tipo = art.get("tipo_revision", "sistematica")
            
            user_prompt = (
                f"Eres el Módulo Epistémico Thinkuy. Analiza el siguiente resumen de un artículo científico en el área de {area}.\n\n"
                f"RESUMEN:\n{abstract}\n\n"
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
            
            casos.append({
                "origen": "Scoping_Multidisciplinar_Real",
                "id": f"scoping_{art.get('filename', f'art_{idx}')}",
                "area": area,
                "esperado_rol": "Síntesis_Review",
                "esperado_aptitud": "Apto",
                "system_prompt": sys_prompt_def,
                "user_prompt": user_prompt
            })
            
    # 3. Controles Negativos (Empíricos y Teóricos puros para contrastar si sobre-generaliza a Review)
    controles = [
        {
            "id": "control_negativo_empirico",
            "area": "ciencias-salud",
            "esperado_rol": "Empírico",
            "esperado_aptitud": "Excluir",
            "abstract": (
                "Se evaluó la eficacia de un nuevo protocolo farmacológico antiarrítmico en una muestra de 180 pacientes hospitalizados. "
                "Se realizó un ensayo clínico controlado aleatorizado de dos brazos durante 12 semanas. "
                "Los registros electrocardiográficos demostraron una reducción estadísticamente significativa (p < 0.005) de episodios de fibrilación. "
                "Se concluye que el fármaco es seguro en dosis terapéuticas controladas."
            )
        },
        {
            "id": "control_negativo_teorico",
            "area": "ciencias-sociales",
            "esperado_rol": "Teórico_Framework",
            "esperado_aptitud": "Dudoso",
            "abstract": (
                "Este ensayo reflexivo propone una reconceptualización de la soberanía alimentaria desde la perspectiva de la ecología política latinoamericana. "
                "Se analiza el marco categorial de la dependencia y la desposesión comunitaria, argumentando que las categorías hegemónicas invisibilizan las prácticas campesinas. "
                "No se recolectaron datos cuantitativos, sino una discusión crítica sobre las bases ontológicas del desarrollo rural."
            )
        }
    ]
    
    for c in controles:
        u_p = (
            f"Eres el Módulo Epistémico Thinkuy. Analiza el siguiente resumen de un artículo científico en el área de {c['area']}.\n\n"
            f"RESUMEN:\n{c['abstract']}\n\n"
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
        casos.append({
            "origen": "Control_Contrastivo",
            "id": c["id"],
            "area": c["area"],
            "esperado_rol": c["esperado_rol"],
            "esperado_aptitud": c["esperado_aptitud"],
            "system_prompt": sys_prompt_def,
            "user_prompt": u_p
        })
        
    return casos

def main():
    print("=" * 80)
    print("THINKUY V3 — PREVIA DE VIABILIDAD Y DIAGNÓSTICO BASE DE QWEN 2.5 1.5B")
    print(f"Modelo: {MODEL_NAME}")
    print(f"Dispositivo: GPU {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print("=" * 80)
    
    # 1. Cargar Modelo y Tokenizer
    print("\n[1/3] Cargando modelo base Qwen 2.5 1.5B (4-bit)...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME,
        max_seq_length=MAX_SEQ_LENGTH,
        load_in_4bit=True,
        device_map={"": 0},
        dtype=None,
    )
    FastLanguageModel.for_inference(model)
    
    # 2. Cargar Casos
    casos = cargar_casos_evaluacion()
    print(f"\n[2/3] Casos preparados para la previa: {len(casos)}")
    print(f"  - Dataset ChatML Gold Standard: {sum(1 for c in casos if c['origen'] == 'Dataset_ChatML_GoldStandard')}")
    print(f"  - Scoping Multidisciplinares Reales: {sum(1 for c in casos if c['origen'] == 'Scoping_Multidisciplinar_Real')}")
    print(f"  - Controles Negativos Contrastivos: {sum(1 for c in casos if c['origen'] == 'Control_Contrastivo')}")
    
    # 3. Ejecutar Inferencia
    print("\n[3/3] Ejecutando evaluación base (sin entrenamiento)...")
    resultados = []
    
    for idx, c in enumerate(casos, 1):
        prompt_msgs = [
            {"role": "system", "content": c["system_prompt"]},
            {"role": "user", "content": c["user_prompt"]}
        ]
        
        input_text = tokenizer.apply_chat_template(prompt_msgs, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([input_text], return_tensors="pt").to("cuda")
        
        t0 = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=400,
                temperature=0.1,
                top_p=0.9,
                use_cache=True,
                pad_token_id=tokenizer.eos_token_id
            )
        elapsed = time.time() - t0
        
        # Decodificar solo la respuesta del asistente
        gen_tokens = outputs[0][inputs.input_ids.shape[1]:]
        raw_pred = tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()
        
        parsed = parse_thinkuy_output(raw_pred)
        
        # Comparaciones estrictas
        match_rol = (parsed["rol_metodologico"] == c["esperado_rol"])
        match_aptitud = (parsed["aptitud_prisma"] == c["esperado_aptitud"])
        
        row_res = {
            "num": idx,
            "origen": c["origen"],
            "id": c["id"],
            "area": c["area"],
            "esperado_rol": c["esperado_rol"],
            "pred_rol": parsed["rol_metodologico"],
            "match_rol": match_rol,
            "esperado_aptitud": c["esperado_aptitud"],
            "pred_aptitud": parsed["aptitud_prisma"],
            "match_aptitud": match_aptitud,
            "status_formato": parsed["status_formato"],
            "tradicion_pred": parsed["tradicion_epistemica"],
            "formula_pred": parsed["formula_retorica"],
            "verbo_pred": parsed["verbo_clave"],
            "pensamiento_snippet": parsed["pensamiento"][:120] if parsed["pensamiento"] else "N/A",
            "tiempo_s": round(elapsed, 2),
            "raw_output": raw_pred
        }
        resultados.append(row_res)
        
        status_sym = "✅" if (match_rol and match_aptitud and parsed["status_formato"] == "OK") else ("⚠️" if match_rol else "❌")
        print(f"[{idx:02d}/{len(casos):02d}] {status_sym} {c['id'][:25]:25} | Rol: {parsed['rol_metodologico']} (Esp: {c['esperado_rol']}) | FMT: {parsed['status_formato']} | {elapsed:.2f}s")
        
    # Guardar CSV
    df = pd.DataFrame(resultados)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[OK] Resultados guardados en: {OUTPUT_CSV}")
    
    # Reporte Estadístico Riguroso
    total = len(df)
    valid_format = sum(df["status_formato"] == "OK")
    aciertos_rol = sum(df["match_rol"])
    aciertos_aptitud = sum(df["match_aptitud"])
    acierto_pleno = sum((df["match_rol"]) & (df["match_aptitud"]) & (df["status_formato"] == "OK"))
    
    print("\n" + "=" * 80)
    print("MÉTRICAS CRUDAS DEL BASELINE QWEN 2.5 1.5B (SIN ENTRENAR):")
    print(f"  - Total Casos Evaluados: {total}")
    print(f"  - Validez Sintáctica Formato: {valid_format}/{total} ({valid_format/total*100:.1f}%)")
    print(f"  - Precisión Rol Metodológico: {aciertos_rol}/{total} ({aciertos_rol/total*100:.1f}%)")
    print(f"  - Precisión Aptitud PRISMA: {aciertos_aptitud}/{total} ({aciertos_aptitud/total*100:.1f}%)")
    print(f"  - Acierto Pleno (Rol + Aptitud + Formato): {acierto_pleno}/{total} ({acierto_pleno/total*100:.1f}%)")
    print("=" * 80)
    
    # Desglose por origen
    print("\nDesglose por Tipo de Muestra:")
    for orig in df["origen"].unique():
        sub = df[df["origen"] == orig]
        acc_rol = sum(sub["match_rol"])
        acc_fmt = sum(sub["status_formato"] == "OK")
        print(f"  * {orig:30}: Rol {acc_rol}/{len(sub)} ({acc_rol/len(sub)*100:.0f}%) | Formato OK {acc_fmt}/{len(sub)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
