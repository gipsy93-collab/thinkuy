"""
=============================================================================
Thinkuy V3 - Test de Inferencia Local con Protocolo Hyland/Swales
=============================================================================
Envía 3 pruebas de inferencia (T1: Epistemología + PRISMA, T2: Extracción PCC JBI,
T3: Auditoría de Citas) a LM Studio Local (http://127.0.0.1:1234/v1).
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
DATASET_PATH = "data/thinkuy_v3_gold_standard_chatml.jsonl"

def consultar_lm_studio(messages, max_tokens=1024, temperature=0.1):
    payload = {
        "model": "google/gemma-4-e2b", # o cualquier modelo activo en LM Studio
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
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

def parse_cot_and_json(raw_text):
    pensamiento = ""
    json_obj = None
    
    t_match = re.search(r"<pensamiento>(.*?)</pensamiento>", raw_text, re.DOTALL | re.IGNORECASE)
    if t_match:
        pensamiento = t_match.group(1).strip()
        
    j_match = re.search(r"<salida_json>(.*?)</salida_json>", raw_text, re.DOTALL | re.IGNORECASE)
    candidate_json = j_match.group(1).strip() if j_match else raw_text.strip()
    
    clean_json = re.sub(r"^```(?:json)?\s*", "", candidate_json, flags=re.IGNORECASE)
    clean_json = re.sub(r"\s*```$", "", clean_json).strip()
    
    obj_match = re.search(r"(\{.*\})", clean_json, re.DOTALL)
    if obj_match:
        try:
            json_obj = json.loads(obj_match.group(1))
        except Exception:
            pass
            
    return pensamiento, json_obj

def main():
    print("=" * 80)
    print("THINKUY V3 — TEST DE INFERENCIA LOCAL (PROTOCOLO HYLAND / SWALES / PRISMA)")
    print(f"Endpoint: {LM_STUDIO_URL}")
    print("=" * 80)
    
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        instancias = [json.loads(line) for line in f if line.strip()]
        
    print(f"Dataset cargado: {len(instancias)} instancias totales.")
    
    # Seleccionar 3 pruebas representativas: T1 (Abstract), T2 (Metodología), T3 (Cita)
    test_cases = []
    
    # Caso 1: T1 (Abstract en educación inclusiva)
    for inst in instancias:
        if "Módulo Epistémico Thinkuy" in inst["messages"][1]["content"] and "educación inclusiva" in inst["messages"][1]["content"]:
            test_cases.append({"tarea": "T1: Clasificación & PRISMA", "instancia": inst})
            break
            
    # Caso 2: T2 (Metodología PCC JBI)
    for inst in instancias:
        if "Módulo de Extracción JBI" in inst["messages"][1]["content"]:
            test_cases.append({"tarea": "T2: Matriz PCC JBI", "instancia": inst})
            break
            
    # Caso 3: T3 (Cita con Marcador Hyland)
    for inst in instancias:
        if "Módulo de Auditoría de Citas" in inst["messages"][1]["content"] and "Chen et al." in inst["messages"][1]["content"]:
            test_cases.append({"tarea": "T3: Auditoría de Citas (Consenso Chen 2022)", "instancia": inst})
            break

    if len(test_cases) < 3:
        test_cases = [{"tarea": f"Caso {i+1}", "instancia": instancias[i*25]} for i in range(3)]

    for idx, tc in enumerate(test_cases, 1):
        nombre_tarea = tc["tarea"]
        inst = tc["instancia"]
        sys_msg = inst["messages"][0]["content"]
        user_prompt = inst["messages"][1]["content"]
        gold_resp = inst["messages"][2]["content"]
        
        print(f"\n[{idx}/3] Ejecutando Inferencia: {nombre_tarea}...")
        
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_prompt}
        ]
        
        raw_output, latencia, err = consultar_lm_studio(messages, max_tokens=1024)
        
        if err:
            print(f"  ❌ Error de conexión: {err}")
            continue
            
        pensamiento, json_obj = parse_cot_and_json(raw_output)
        
        print(f"  ⚡ Latencia GPU: {latencia:.2f}s")
        print(f"  🧠 <pensamiento> Generado en Local:")
        if pensamiento:
            for line in pensamiento.split("\n"):
                print(f"     {line}")
        else:
            print("     [Sin pensamiento explícito]")
            
        print(f"  📊 <salida_json> Parseado:")
        if json_obj:
            print("     " + json.dumps(json_obj, ensure_ascii=False, indent=2).replace("\n", "\n     "))
            print("  ✅ Estado: RESPUESTA VÁLIDA Y ESTRUCTURADA")
        else:
            print("     ❌ Error: No se pudo parsear JSON")
            print(f"     Raw: {raw_output[:250]}...")
            
        print("-" * 80)

if __name__ == "__main__":
    main()
