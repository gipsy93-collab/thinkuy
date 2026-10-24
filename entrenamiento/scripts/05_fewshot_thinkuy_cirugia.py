"""
=============================================================================
Thinkuy - Script 05: Cirugía Epistémica Few-Shot con 10 Arquetipos de Fallo
=============================================================================
Este script implementa Few-Shot In-Context Steering inyectando 10 casos
arquetípicos de fallo epistemológico contrastivo antes de solicitar al modelo
que clasifique nuevos resúmenes de RSU.

Protocolo Estricto:
- ZERO SILENT FALLBACKS: Si el modelo no genera una salida JSON válida, se
  registra como 'INVALID_OUTPUT' y se cuenta como fallo estricto (0).
- Registro íntegro del razonamiento CoT (<pensamiento>) y tokens crudos.
=============================================================================
"""

import os
import sys
import json
import re
import time
import argparse
import csv
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 10 Ejemplos Arquetípicos Curados de Cirugía Epistémica
FEW_SHOT_EXEMPLARS = """
<ejemplos_referencia>
<ejemplo id="1" tipo="P2_CONFUNDIDO_CON_P3_O_P1">
Abstract: "This paper aims to explain the shifting from Corporate Social University to University Social Responsibility, by presenting the conceptual framework of Social Responsibility and the university as a special type of organization which needs to adopt a social responsibility strategy just like the other organizations, in order to meet the expectations of the stakeholders... presents a general University Social Responsibility model in the context of globalization..." (Vasilescu et al., 2010)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: Palabras como "model", "framework" y "civil society" podrían tentar hacia P1 (instrumento) o P3 (extensión).
2. CHECKLIST P1 (Medición/Escalas): ¿Diseña, calibra o valida psicométricamente una escala cuantitativa? NO.
3. CHECKLIST P2 (Estratégico/Gobernanza): ¿Propone políticas institucionales, modelos de gestión organizacional o alineación con grupos de interés? SÍ. Es el modelo troncal de gobernanza y gestión de RSU ante los stakeholders.
4. CHECKLIST P3 (Conexión/Extensión): ¿Es un proyecto directo de intervención pedagógica, aprendizaje-servicio o ética cívica comunitaria? NO.
CONCLUSIÓN: Perspectiva 2 (P2_ESTRATEGICO_STAKEHOLDERS).
</pensamiento>
<salida_json>
{"perspectiva": "P2_ESTRATEGICO_STAKEHOLDERS", "rol": "seminal", "claim_central": "Propone un modelo integrador de RSU universitaria para alinear instituciones con demandas de la sociedad civil contemporánea."}
</salida_json>
</ejemplo>

<ejemplo id="2" tipo="P2_CONFUNDIDO_CON_P1_POR_ENCUESTAS_ORGANIZACIONALES">
Abstract: "This study investigated the relationship between learning organization and university social responsibility. This relationship was studied in three groups of internal stakeholders: students, staff with leadership, monitoring, evaluation and control roles, and staff involved in study programs. 536 members of two public Romanian universities filled in the 21-item Dimensions of the Learning Organization Questionnaire..." (Rus et al., 2014)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: Menciona "536 members", "questionnaire" y "21-item".
2. CHECKLIST P1: ¿El objetivo del artículo es validar una nueva escala psicométrica de RSU? NO. Aplica cuestionarios para evaluar la dinámica organizacional interna.
3. CHECKLIST P2: ¿Examina la relación entre cultura organizacional, gobernanza y stakeholders internos? SÍ. Analiza la organización del aprendizaje institucional como soporte estratégico.
4. CHECKLIST P3: ¿Se centra en acción comunitaria externa? NO.
CONCLUSIÓN: Perspectiva 2 (P2_ESTRATEGICO_STAKEHOLDERS).
</pensamiento>
<salida_json>
{"perspectiva": "P2_ESTRATEGICO_STAKEHOLDERS", "rol": "empirical", "claim_central": "Las organizaciones de aprendizaje en universidades mejoran su RSU al integrar prácticas colaborativas con actores estratégicos internos."}
</salida_json>
</ejemplo>

<ejemplo id="3" tipo="P2_CONFUNDIDO_CON_P1_POR_ANALISIS_BIBLIOMETRICO">
Abstract: "A descriptive study is presented which goal was to know about University Social Responsibility's scientific production. A bibliometric analysis of 94 documents obtained from Redalyc and Scielo was performed to evaluate trends, key authors, and geographical distribution..." (Pacenza & Peralta, 2013)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: "Bibliometric analysis", "94 documents", "descriptive study".
2. CHECKLIST P1: ¿Evalúa o mide a sujetos de prueba con escalas de autodiagnóstico de RSU? NO. Analiza literatura científica.
3. CHECKLIST P2: ¿Es un estado del arte o síntesis sobre la evolución del campo y su gobernanza conceptual? SÍ. Corresponde al marco directivo y mapeo del conocimiento.
4. CHECKLIST P3: ¿Es una intervención cívico-pedagógica? NO.
CONCLUSIÓN: Perspectiva 2 (P2_ESTRATEGICO_STAKEHOLDERS).
</pensamiento>
<salida_json>
{"perspectiva": "P2_ESTRATEGICO_STAKEHOLDERS", "rol": "review_synthesis", "claim_central": "Analiza la producción científica sobre RSU en América Latina identificando su crecimiento y concentración autoral."}
</salida_json>
</ejemplo>

<ejemplo id="4" tipo="P3_CONFUNDIDO_CON_P1_POR_EVIDENCIA_EMPIRICA">
Abstract: "This paper provides empirical evidence on university social responsibility efforts and how it impacted community. The objectives are to investigate the direct engagement of students in community development projects and their ethical awareness..." (Shaari et al., 2018)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: Menciona "empirical evidence" y "objectives to investigate".
2. CHECKLIST P1: ¿El foco es el refinamiento psicométrico o matemático de un instrumento de medida? NO.
3. CHECKLIST P2: ¿El eje es la reputación o competitividad institucional directiva? NO.
4. CHECKLIST P3: ¿El núcleo ontológico es la transformación comunitaria, el impacto social directo y la conciencia ética del estudiante? SÍ. Es extensión universitaria y compromiso social.
CONCLUSIÓN: Perspectiva 3 (P3_CONEXION_SOCIAL_EXTENSION).
</pensamiento>
<salida_json>
{"perspectiva": "P3_CONEXION_SOCIAL_EXTENSION", "rol": "empirical", "claim_central": "Demuestra el impacto transformador de las iniciativas de voluntariado y extensión universitaria en el bienestar comunitario directo."}
</salida_json>
</ejemplo>

<ejemplo id="5" tipo="P3_CONFUNDIDO_CON_P2_POR_ENSAYO_CRITICO_TEORICO">
Abstract: "This article aims at consolidating the theoretical framework of University Social Responsibility (USR) based on the conceptual analysis of the ten most frequent fallacies. It critiques the reduction of USR to mere corporate marketing or philanthropic extension, defending a comprehensive ethical commitment to social justice..." (Vallaeys, 2018)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: "Theoretical framework", "conceptual analysis".
2. CHECKLIST P1: ¿Diseña o valida escalas cuantitativas? NO.
3. CHECKLIST P2: ¿Defiende la RSU como ventaja competitiva gerencial de mercado? NO, precisamente refuta esa visión reduccionista.
4. CHECKLIST P3: ¿Defiende la ética civil, la justicia social, los impactos epistemológicos/sociales y la formación ciudadana crítica? SÍ.
CONCLUSIÓN: Perspectiva 3 (P3_CONEXION_SOCIAL_EXTENSION).
</pensamiento>
<salida_json>
{"perspectiva": "P3_CONEXION_SOCIAL_EXTENSION", "rol": "seminal", "claim_central": "Refuta las diez falacias que reducen la RSU a mercadotecnia, fundamentando el deber ético universitario con la justicia social."}
</salida_json>
</ejemplo>

<ejemplo id="6" tipo="P1_CONFUNDIDO_CON_P2_POR_TEMAS_DE_SERVICIOS_Y_MARKETING">
Abstract: "The principal aim of this paper is to identify the factors that define students' perceptions of university social responsibility (USR) in a Spanish university, and analyse the impact on satisfaction. A self-report study was conducted with 400 undergraduate students. Structural equation modeling (PLS-SEM) was used to test the factorial structure of six dimensions..." (Vázquez et al., 2015)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: Menciona "quality of service", "marketing in university settings" y "management".
2. CHECKLIST P1: ¿Aplica modelado psicométrico riguroso, análisis factorial o validación cuantitativa de escalas con SEM? SÍ. Es investigación cuantitativa basada en ecuaciones estructurales y escalas de percepción.
3. CHECKLIST P2: ¿Es meramente un informe descriptivo de políticas? NO, el corazón metodológico es la validación psicométrica.
4. CHECKLIST P3: ¿Es aprendizaje-servicio o acción comunitaria directa? NO.
CONCLUSIÓN: Perspectiva 1 (P1_MEDICION_ESCALAS).
</pensamiento>
<salida_json>
{"perspectiva": "P1_MEDICION_ESCALAS", "rol": "empirical", "claim_central": "Valida mediante PLS-SEM una escala de seis dimensiones para medir la percepción de la RSU y su efecto en la satisfacción estudiantil."}
</salida_json>
</ejemplo>

<ejemplo id="7" tipo="P1_CONFUNDIDO_CON_P2_POR_STAKEHOLDERS_EN_TITULO">
Abstract: "The University Social Responsibility (RSU) is one of the management models that is being applied in universities. The research aimed to determine the perception of stakeholders through an instrument of 44 Likert items with Cronbach alpha 0.94, applied to 280 administrative and faculty members..." (Aguirre, 2019)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: "Management models", "stakeholders".
2. CHECKLIST P1: ¿Desarrolla, valida o aplica formalmente un instrumento cuantitativo con métricas de confiabilidad (alfa de Cronbach, Likert, análisis estadístico)? SÍ.
3. CHECKLIST P2: Aunque evalúa stakeholders, el aporte primordial es la medición psicométrica cuantitativa.
4. CHECKLIST P3: No es intervención comunitaria.
CONCLUSIÓN: Perspectiva 1 (P1_MEDICION_ESCALAS).
</pensamiento>
<salida_json>
{"perspectiva": "P1_MEDICION_ESCALAS", "rol": "methodological", "claim_central": "Evalúa las propiedades psicométricas de un instrumento de 44 ítems para medir la percepción de RSU en grupos de interés."}
</salida_json>
</ejemplo>

<ejemplo id="8" tipo="P3_CONFUNDIDO_CON_P2_POR_ENSAYO_DE_TRANSFORMACION">
Abstract: "The present essay contributes with a reflection on the role universities must take as agents of transformation and consolidation of democracy, ethical citizenship and social justice in Latin America. It proposes pedagogical frameworks for civic engagement..." (Gasca-Pliego & Olvera-Garcia, 2011)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: "Reflection", "institutional role".
2. CHECKLIST P1: ¿Psicometría o encuestas? NO.
3. CHECKLIST P2: ¿Gobernanza corporativa o rankings? NO.
4. CHECKLIST P3: ¿Se fundamenta en ética civil, formación ciudadana, justicia social y compromiso democrático transformador? SÍ.
CONCLUSIÓN: Perspectiva 3 (P3_CONEXION_SOCIAL_EXTENSION).
</pensamiento>
<salida_json>
{"perspectiva": "P3_CONEXION_SOCIAL_EXTENSION", "rol": "theoretical_framework", "claim_central": "Fundamenta la misión universitaria en la consolidación de la ciudadanía ética, la democracia y la justicia social."}
</salida_json>
</ejemplo>

<ejemplo id="9" tipo="P2_CONFUNDIDO_CON_P3_POR_TERMINOS_DE_SOCIEDAD">
Abstract: "The objective of this article was to critically analyze the University-Society relationship from the concept of University Social Responsibility, evaluating institutional governance policies, accountability mechanisms and public mission in regional universities..." (Pástor & Guarton, 2019)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: "University-Society relationship", "transformation of society".
2. CHECKLIST P1: ¿Validación psicométrica? NO.
3. CHECKLIST P2: ¿Analiza la relación Universidad-Sociedad desde la gobernanza institucional, rendición de cuentas y políticas directivas? SÍ. Es gestión estratégica de la institución.
4. CHECKLIST P3: ¿Describe programas específicos de extensión pedagógica o servicio comunitario en campo? NO, es análisis de políticas institucionales.
CONCLUSIÓN: Perspectiva 2 (P2_ESTRATEGICO_STAKEHOLDERS).
</pensamiento>
<salida_json>
{"perspectiva": "P2_ESTRATEGICO_STAKEHOLDERS", "rol": "theoretical_framework", "claim_central": "Analiza críticamente las políticas de gobernanza y rendición de cuentas en el vínculo estratégico entre universidad y sociedad."}
</salida_json>
</ejemplo>

<ejemplo id="10" tipo="P2_CONFUNDIDO_CON_P3_POR_VALORES_CONFESIONALES">
Abstract: "University Social Responsibility (USR) involves responding to demands of audiences and forming individuals. The purpose is to describe USR in a confessional institution towards a strategic management model, integrating organizational values and institutional governance pillars..." (de Rodríguez & Gallego, 2018)
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: "Forming individuals", "biblical principles", "positive impacts".
2. CHECKLIST P1: ¿Validación psicométrica? NO.
3. CHECKLIST P2: ¿El objetivo es estructurar un modelo de gestión y gobernanza organizacional adaptado a la identidad de la institución? SÍ.
4. CHECKLIST P3: ¿Es una intervención pedagógica comunitaria en terreno? NO.
CONCLUSIÓN: Perspectiva 2 (P2_ESTRATEGICO_STAKEHOLDERS).
</pensamiento>
<salida_json>
{"perspectiva": "P2_ESTRATEGICO_STAKEHOLDERS", "rol": "empirical", "claim_central": "Estructura un modelo de gestión de RSU que articula la identidad confesional con la gobernanza y rendición de cuentas a sus públicos."}
</salida_json>
</ejemplo>
</ejemplos_referencia>
"""

SYSTEM_PROMPT = """Eres el clasificador epistemológico Thinkuy, especializado en la taxonomía canónica de Responsabilidad Social Universitaria (RSU) de Duque & Cervantes (2019):
- P1_MEDICION_ESCALAS: Investigación empírica cuantitativa, psicometría, diseño/validación de escalas, encuestas estructuradas, modelos de ecuaciones estructurales (SEM).
- P2_ESTRATEGICO_STAKEHOLDERS: Enfoque directivo y organizacional: modelos de gestión, gobernanza universitaria, políticas institucionales, competitividad, revisiones del campo, estados del arte y relación estratégica con stakeholders.
- P3_CONEXION_SOCIAL_EXTENSION: Centrado en ética civil, formación ciudadana, justicia social, aprendizaje-servicio, voluntariado y proyectos directos de compromiso comunitario.

Instrucción Metodológica:
Antes de responder, debes analizar el abstract contrastándolo con los 10 ejemplos de referencia. Detecta las trampas lingüísticas (ej. palabras como 'survey' en análisis organizacional que NO son psicometría P1, o 'sociedad civil' en gobernanza institucional que NO son extensión comunitaria P3).

Estructura de respuesta OBLIGATORIA:
<pensamiento>
1. TRAMPAS LINGÜÍSTICAS: ...
2. CHECKLIST P1: ...
3. CHECKLIST P2: ...
4. CHECKLIST P3: ...
CONCLUSIÓN: ...
</pensamiento>
<salida_json>
{"perspectiva": "P1_MEDICION_ESCALAS" | "P2_ESTRATEGICO_STAKEHOLDERS" | "P3_CONEXION_SOCIAL_EXTENSION", "rol": "seminal" | "review_synthesis" | "theoretical_framework" | "methodological" | "empirical", "claim_central": "..."}
</salida_json>
"""

def parse_strict_json(raw_text):
    """
    Parsea de forma estricta el JSON sin fallbacks silenciosos.
    Si está roto o ausente, retorna 'INVALID_OUTPUT'.
    """
    if "<salida_json>" in raw_text and "</salida_json>" in raw_text:
        json_str = raw_text.split("<salida_json>")[1].split("</salida_json>")[0].strip()
    else:
        # Búsqueda secundaria de bloque json
        match = re.search(r'\{[\s\S]*?"perspectiva"[\s\S]*?\}', raw_text)
        if match:
            json_str = match.group(0).strip()
        else:
            return "INVALID_OUTPUT", "INVALID_OUTPUT", "", "Formato no contiene <salida_json>"

    try:
        data = json.loads(json_str)
        perspectiva = data.get("perspectiva", "").strip()
        rol = data.get("rol", "").strip()
        claim = data.get("claim_central", "").strip()
        
        valid_perspectivas = {"P1_MEDICION_ESCALAS", "P2_ESTRATEGICO_STAKEHOLDERS", "P3_CONEXION_SOCIAL_EXTENSION"}
        if perspectiva not in valid_perspectivas:
            return "INVALID_OUTPUT", rol, claim, f"Perspectiva '{perspectiva}' fuera de taxonomía"
            
        return perspectiva, rol, claim, "OK"
    except Exception as e:
        return "INVALID_OUTPUT", "INVALID_OUTPUT", "", f"Error parseando JSON: {str(e)}"

def extract_thinking(raw_text):
    if "<pensamiento>" in raw_text and "</pensamiento>" in raw_text:
        return raw_text.split("<pensamiento>")[1].split("</pensamiento>")[0].strip()
    return ""

def run_evaluation_api(csv_input, csv_output, limit=None, base_url="http://127.0.0.1:1234/v1", model_name="google/gemma-4-e2b"):
    """Ejecuta inferencia a través de la API OpenAI local (LM Studio)."""
    import urllib.request
    
    with open(csv_input, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]
        
    print(f"🔬 Ejecutando evaluación Few-Shot en {len(rows)} registros vía {base_url}...")
    
    results = []
    correct_count = 0
    valid_format_count = 0
    
    for idx, row in enumerate(rows):
        id_reg = row.get("id", idx + 1)
        title = row.get("title", "")
        abstract = str(row.get("abstract", ""))
        gold = str(row.get("referencia_canonica_perspectiva", "")).strip()
        
        user_content = f"""{FEW_SHOT_EXEMPLARS}

---
AHORA ANALIZA ESTE CASO (ID: {id_reg}):
Título: "{title}"
Abstract: "{abstract}"

Aplica el análisis riguroso y responde estrictamente con <pensamiento> y <salida_json>.
"""
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.1,
            "max_tokens": 1024
        }
        
        t0 = time.time()
        try:
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                raw_out = resp_data["choices"][0]["message"]["content"]
        except Exception as e:
            raw_out = f"ERROR_API: {str(e)}"
            
        latency = round(time.time() - t0, 2)
        perspectiva, rol, claim, status = parse_strict_json(raw_out)
        thinking = extract_thinking(raw_out)
        
        is_acierto = "ACIERTO" if (perspectiva == gold and perspectiva != "INVALID_OUTPUT") else "FALLO"
        if is_acierto == "ACIERTO":
            correct_count += 1
        if perspectiva != "INVALID_OUTPUT":
            valid_format_count += 1
            
        print(f"[{idx+1}/{len(rows)}] ID {id_reg} | Gold: {gold:28s} | Pred: {perspectiva:28s} | {is_acierto} ({latency}s)")
        
        row_dict = dict(row)
        row_dict["fewshot_perspectiva"] = perspectiva
        row_dict["fewshot_rol"] = rol
        row_dict["fewshot_claim"] = claim
        row_dict["fewshot_acierto"] = is_acierto
        row_dict["fewshot_thinking"] = thinking
        row_dict["fewshot_latencia_seg"] = latency
        row_dict["fewshot_raw"] = raw_out
        results.append(row_dict)
        
    if results:
        fieldnames = list(results[0].keys())
        with open(csv_output, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
    
    total = len(rows)
    acc = (correct_count / total) * 100 if total > 0 else 0
    form_acc = (valid_format_count / total) * 100 if total > 0 else 0
    print("\n" + "=" * 80)
    print(f"📊 RESUMEN FINAL RIGUROSO (SIN FALLBACKS):")
    print(f"  Total Evaluados     : {total}")
    print(f"  Formato Válido      : {valid_format_count}/{total} ({form_acc:.2f}%)")
    print(f"  Aciertos Estrictos  : {correct_count}/{total} ({acc:.2f}%)")
    print(f"  Archivo Guardado    : {csv_output}")
    print("=" * 80)

def run_evaluation_unsloth(csv_input, csv_output, model_name="Qwen/Qwen2.5-1.5B-Instruct", limit=None):
    """Ejecuta inferencia utilizando FastLanguageModel de Unsloth en GPU."""
    import torch
    from unsloth import FastLanguageModel
    
    print(f"🔄 Cargando modelo {model_name} con Unsloth 4-bit...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=4096,
        load_in_4bit=True,
        flash_attention=False
    )
    FastLanguageModel.for_inference(model)
    
    with open(csv_input, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]
        
    print(f"🔬 Evaluando {len(rows)} casos con Unsloth...")
    results = []
    correct_count = 0
    valid_format_count = 0
    
    for idx, row in enumerate(rows):
        id_reg = row.get("id", idx + 1)
        title = row.get("title", "")
        abstract = str(row.get("abstract", ""))
        gold = str(row.get("referencia_canonica_perspectiva", "")).strip()
        
        user_content = f"""{FEW_SHOT_EXEMPLARS}

---
AHORA ANALIZA ESTE CASO (ID: {id_reg}):
Título: "{title}"
Abstract: "{abstract}"

Aplica el análisis riguroso y responde estrictamente con <pensamiento> y <salida_json>.
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]
        
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
        
        t0 = time.time()
        outputs = model.generate(
            **inputs,
            max_new_tokens=600,
            temperature=0.1,
            do_sample=False
        )
        latency = round(time.time() - t0, 2)
        
        raw_out = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        perspectiva, rol, claim, status = parse_strict_json(raw_out)
        thinking = extract_thinking(raw_out)
        
        is_acierto = "ACIERTO" if (perspectiva == gold and perspectiva != "INVALID_OUTPUT") else "FALLO"
        if is_acierto == "ACIERTO":
            correct_count += 1
        if perspectiva != "INVALID_OUTPUT":
            valid_format_count += 1
            
        print(f"[{idx+1}/{len(rows)}] ID {id_reg} | Gold: {gold:28s} | Pred: {perspectiva:28s} | {is_acierto} ({latency}s)")
        
        row_dict = dict(row)
        row_dict["fewshot_perspectiva"] = perspectiva
        row_dict["fewshot_rol"] = rol
        row_dict["fewshot_claim"] = claim
        row_dict["fewshot_acierto"] = is_acierto
        row_dict["fewshot_thinking"] = thinking
        row_dict["fewshot_latencia_seg"] = latency
        row_dict["fewshot_raw"] = raw_out
        results.append(row_dict)
        
    if results:
        fieldnames = list(results[0].keys())
        with open(csv_output, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
    
    total = len(rows)
    acc = (correct_count / total) * 100 if total > 0 else 0
    form_acc = (valid_format_count / total) * 100 if total > 0 else 0
    print("\n" + "=" * 80)
    print(f"📊 RESUMEN FINAL RIGUROSO (UNSLOTH):")
    print(f"  Total Evaluados     : {total}")
    print(f"  Formato Válido      : {valid_format_count}/{total} ({form_acc:.2f}%)")
    print(f"  Aciertos Estrictos  : {correct_count}/{total} ({acc:.2f}%)")
    print(f"  Archivo Guardado    : {csv_output}")
    print("=" * 80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cirugía Epistémica Few-Shot Thinkuy")
    parser.add_argument("--mode", choices=["api", "unsloth"], default="api", help="Modo de ejecución: 'api' (LM Studio) o 'unsloth' (PyTorch local)")
    parser.add_argument("--input", default="data/auditorias_y_benchmarks/resultados_pruebas_modelos_333.csv", help="Ruta al CSV de entrada")
    parser.add_argument("--output", default="data/auditorias_y_benchmarks/resultados_fewshot_thinkuy_cirugia.csv", help="Ruta al CSV de salida")
    parser.add_argument("--limit", type=int, default=None, help="Límite de casos a procesar (para pruebas rápidas)")
    parser.add_argument("--base_url", default="http://127.0.0.1:1234/v1", help="URL base de la API OpenAI local")
    parser.add_argument("--model", default="google/gemma-4-e2b", help="Nombre del modelo")
    
    args = parser.parse_args()
    
    if args.mode == "api":
        run_evaluation_api(args.input, args.output, limit=args.limit, base_url=args.base_url, model_name=args.model)
    else:
        run_evaluation_unsloth(args.input, args.output, model_name=args.model, limit=args.limit)
