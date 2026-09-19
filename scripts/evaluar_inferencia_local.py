"""
=============================================================================
Thinkuy - Inferencia Local con LM Studio: Validación del Pipeline Thinkuy V3
=============================================================================
Evalúa la capacidad de razonamiento en 3 pasos (<pensamiento> + <salida_json>)
enviando tripletas de prueba (T1: Epistemología, T2: Extracción JBI, T3: Auditoría de Citas)
directamente al servidor local de LM Studio (http://127.0.0.1:1234/v1).
=============================================================================
"""

import os
import sys
import json
import time
import re
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL_ID = "google/gemma-4-e2b"
DATASET_PATH = "data/thinkuy_v3_gold_standard_chatml.jsonl"

def consultar_lm_studio(messages, max_tokens=1024, temperature=0.1):
    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    
    req = urllib.request.Request(
        LM_STUDIO_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - start_time
            content = data["choices"][0]["message"]["content"]
            return content, elapsed, None
    except Exception as e:
        return "", 0, str(e)

def parse_cot_and_json(raw_text):
    """Extrae el bloque <pensamiento> y el bloque <salida_json>."""
    pensamiento = ""
    json_obj = None
    
    thought_match = re.search(r"<pensamiento>(.*?)</pensamiento>", raw_text, re.DOTALL | re.IGNORECASE)
    if thought_match:
        pensamiento = thought_match.group(1).strip()
        
    json_match = re.search(r"<salida_json>(.*?)</salida_json>", raw_text, re.DOTALL | re.IGNORECASE)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Fallback de búsqueda de JSON sin tags
        json_str = raw_text.strip()
        
    # Limpiar markdown ticks si los hay
    clean_json = re.sub(r"^```(?:json)?\s*", "", json_str.strip(), flags=re.IGNORECASE)
    clean_json = re.sub(r"\s*```$", "", clean_json).strip()
    
    # Intentar parsear el primer objeto JSON {...}
    obj_match = re.search(r"(\{.*\})", clean_json, re.DOTALL)
    if obj_match:
        try:
            json_obj = json.loads(obj_match.group(1))
        except Exception:
            pass
            
    return pensamiento, json_obj

def main():
    print("=" * 75)
    print("THINKUY V3 — INFERENCIA LOCAL LM STUDIO (PRUEBA DE PROTOCOLO)")
    print(f"Servidor: {LM_STUDIO_URL} | Modelo: {MODEL_ID}")
    print("=" * 75)
    
    if not os.path.exists(DATASET_PATH):
        print(f"ERROR: No se encontró el dataset en {DATASET_PATH}")
        return

    # Leer ejemplos del dataset
    ejemplos = []
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                ejemplos.append(json.loads(line))
                
    print(f"Dataset cargado: {len(ejemplos)} ejemplos totales disponibles.")
    
    # Seleccionar 3 casos de prueba representativos (T1: Epistemología, T2: Extracción, T3: Auditoría)
    # Buscamos 1 de cada tarea
    casos_prueba = []
    for ej in ejemplos:
        user_msg = ej["messages"][1]["content"]
        if "T1_CLASIFICACION_EPISTEMICA" in user_msg or "rol_metodologico" in user_msg:
            if not any(c.get("tipo") == "T1_Epistemologia" for c in casos_prueba):
                casos_prueba.append({"tipo": "T1_Epistemologia", "data": ej})
        elif "T2_EXTRACCION_PCC_JBI" in user_msg or "poblacion" in user_msg:
            if not any(c.get("tipo") == "T2_Extraccion_PCC" for c in casos_prueba):
                casos_prueba.append({"tipo": "T2_Extraccion_PCC", "data": ej})
        elif "T3_AUDITORIA_CITAS" in user_msg or "autores_citados" in user_msg:
            if not any(c.get("tipo") == "T3_Auditoria_Citas" for c in casos_prueba):
                casos_prueba.append({"tipo": "T3_Auditoria_Citas", "data": ej})
        if len(casos_prueba) == 3:
            break

    if not casos_prueba:
        casos_prueba = [{"tipo": f"Ejemplo_{i+1}", "data": ejemplos[i]} for i in range(min(3, len(ejemplos)))]

    print(f"\nIniciando inferencia sobre {len(casos_prueba)} tareas clave de Thinkuy...\n")
    
    for idx, caso in enumerate(casos_prueba, 1):
        tipo = caso["tipo"]
        ej = caso["data"]
        system_msg = ej["messages"][0]["content"]
        user_prompt = ej["messages"][1]["content"]
        gold_response = ej["messages"][2]["content"]
        
        print(f"[{idx}/{len(casos_prueba)}] Evaluando Tarea: {tipo}...")
        
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt}
        ]
        
        raw_output, elapsed, error = consultar_lm_studio(messages)
        
        if error:
            print(f"  ❌ Error de conexión: {error}\n")
            continue
            
        pensamiento, json_salida = parse_cot_and_json(raw_output)
        
        print(f"  ⚡ Tiempo de respuesta: {elapsed:.2f}s")
        print(f"  🧠 <pensamiento> Generado:\n     " + pensamiento.replace("\n", "\n     ") if pensamiento else "     [Sin tag de pensamiento]")
        print(f"  📊 <salida_json> Parseado:")
        if json_salida:
            print("     " + json.dumps(json_salida, ensure_ascii=False, indent=2).replace("\n", "\n     "))
            print("  ✅ Estado: SALIDA VÁLIDA Y ESTRUCTURADA")
        else:
            print("     ❌ Salida inválida (No se pudo parsear JSON)")
            print(f"     Raw: {raw_output[:200]}...")
            
        print("-" * 75)

if __name__ == "__main__":
    main()
