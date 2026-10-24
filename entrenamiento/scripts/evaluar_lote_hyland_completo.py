"""
=============================================================================
Thinkuy V3 - Evaluación de Lote Amplio (10 Casos) con Protocolo Hyland/Swales
=============================================================================
Audita con rigor metodológico las 3 micro-tareas de Thinkuy contra LM Studio:
- 4 Casos de T1 (Síntesis, Empírico primario, Teórico, Metodológico)
- 5 Casos de T3 (Consenso, Disenso, Concesión/Matización, Adopción, Neutralidad)
- 1 Caso de T2 (Extracción Matriz PCC JBI)
=============================================================================
"""

import os
import sys
import json
import time
import re
import urllib.request
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
OUTPUT_CSV = "data/auditorias_y_benchmarks/auditoria_lote_10_hyland.csv"

CASOS_PRUEBA = [
    # ── TAREA 1: CLASIFICACIÓN & SCREENING PRISMA (4 Variantes) ──────────────
    {
        "tarea": "T1_Scoping_Review",
        "area": "medicina-social",
        "esperado": {"rol": "Síntesis_Review", "aptitud": "Apto"},
        "prompt": (
            "Eres el Módulo Epistémico Thinkuy. Analiza el siguiente resumen de un artículo científico en el área de medicina-social.\n\n"
            "RESUMEN:\n"
            "Introducción: La soledad y el aislamiento social representan un problema crítico de salud pública en adultos mayores. "
            "Método: Se realizó una revisión de alcance (scoping review) siguiendo las directrices PRISMA-ScR y el marco de Arksey & O'Malley en 5 etapas. "
            "Se consultaron las bases de datos PubMed, Scopus, Web of Science y SciELO entre 2018 y 2024. "
            "Resultados: Se incluyeron 45 estudios que mapean los factores determinantes sociales, intervenciones comunitarias y barreras de acceso. "
            "Conclusiones: Se evidencia la necesidad de políticas públicas intersectoriales centradas en la salud comunitaria.\n\n"
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
    },
    {
        "tarea": "T1_Control_Negativo_Empirico",
        "area": "ciencias-duras",
        "esperado": {"rol": "Empírico", "aptitud": "Excluir"},
        "prompt": (
            "Eres el Módulo Epistémico Thinkuy. Analiza el siguiente resumen de un artículo científico en el área de ciencias-duras.\n\n"
            "RESUMEN:\n"
            "Se evaluó la eficacia de un nuevo protocolo farmacológico antiarrítmico en una muestra de 180 pacientes hospitalizados. "
            "Se realizó un ensayo clínico controlado aleatorizado de dos brazos durante 12 semanas. "
            "Los registros electrocardiográficos continuos demostraron una reducción estadísticamente significativa (p < 0.005) de episodios de fibrilación auricular en el grupo tratado. "
            "Se concluye que el fármaco es seguro y eficaz en dosis terapéuticas controladas.\n\n"
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
    },
    {
        "tarea": "T1_Marco_Teorico_Critico",
        "area": "pensamiento-critico",
        "esperado": {"rol": "Teórico_Framework", "aptitud": "Dudoso"},
        "prompt": (
            "Eres el Módulo Epistémico Thinkuy. Analiza el siguiente resumen de un artículo científico en el área de pensamiento-critico.\n\n"
            "RESUMEN:\n"
            "Este artículo propone un marco teórico descolonial para reinterpretar la apropiación social del conocimiento en universidades del Sur Global. "
            "A partir de una crítica conceptual a los rankings hegemónicos anglosajones, se argumenta que la evaluación del impacto científico debe fundarse en la soberanía comunitaria y la ecología de saberes. "
            "No se realiza una revisión sistemática formal, sino un ensayo crítico propositivo.\n\n"
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
    },
    {
        "tarea": "T1_Diseno_Metodologico_Escala",
        "area": "educacion-apropiacion",
        "esperado": {"rol": "Metodológico", "aptitud": "Dudoso"},
        "prompt": (
            "Eres el Módulo Epistémico Thinkuy. Analiza el siguiente resumen de un artículo científico en el área de educacion-apropiacion.\n\n"
            "RESUMEN:\n"
            "El objetivo de este trabajo es diseñar y validar psicométricamente un cuestionario de 32 ítems para evaluar la competencia digital docente en educación básica. "
            "Se aplicó el instrumento a 450 profesores. El análisis factorial exploratorio y confirmatorio (SEM) arrojó un alfa de Cronbach de 0.92 y ajuste óptimo de bondad. "
            "Se presenta la escala definitiva como herramienta de autodiagnóstico.\n\n"
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
    },

    # ── TAREA 3: AUDITORÍA DE CITAS & FÓRMULAS HYLAND (5 Posturas) ───────────
    {
        "tarea": "T3_Formula_Consenso",
        "area": "ciencias-duras",
        "esperado": {"tipo_relacion": "Consenso", "verbo": "corroboran"},
        "prompt": (
            "Eres el Módulo de Auditoría de Citas (Paso 3). Analiza el siguiente párrafo extraído del cuerpo de un artículo científico.\n\n"
            "PÁRRAFO:\n"
            "Nuestros resultados experimentales corroboran de manera consistente los hallazgos de Rodríguez et al. (2023), confirmando que la adición de nanopartículas de plata incrementa la resistencia mecánica del compuesto en más del 25%.\n\n"
            "TAREA:\n"
            "Identifica los autores citados, la relación epistémica (Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion), el verbo clave de Hyland y el claim literal.\n\n"
            "FORMATO OBLIGATORIO:\n"
            "<pensamiento>\n"
            "1. Agente y Objeto: [Quién cita a quién]\n"
            "2. Marcador y Modalidad: [Identificar verbo clave y fórmula Hyland]\n"
            "3. Clasificación de Postura: [Justificación de la relación dialéctica]\n"
            "</pensamiento>\n"
            "<salida_json>\n"
            "{\n"
            '  "autores_citados": ["Autor, Año"],\n'
            '  "tipo_relacion": "[Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion]",\n'
            '  "marcador_epistemico": "[Verbo clave]",\n'
            '  "formula_hyland": "[Fórmula Hyland]",\n'
            '  "claim_extraido": "[Afirmación literal verbatim, máx 25 palabras]"\n'
            "}\n"
            "</salida_json>"
        )
    },
    {
        "tarea": "T3_Formula_Disenso_Ruptura",
        "area": "ciencia-tecnologia",
        "esperado": {"tipo_relacion": "Disenso", "verbo": "refuta"},
        "prompt": (
            "Eres el Módulo de Auditoría de Citas (Paso 3). Analiza el siguiente párrafo extraído del cuerpo de un artículo científico.\n\n"
            "PÁRRAFO:\n"
            "Este estudio refuta abiertamente la afirmación de Gómez & Martínez (2020) sobre la supuesta infalibilidad de los clasificadores automáticos, demostrando que exhiben un sesgo algorítmico sistemático del 34% cuando se procesan dialectos regionales no hegemónicos.\n\n"
            "TAREA:\n"
            "Identifica los autores citados, la relación epistémica (Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion), el verbo clave de Hyland y el claim literal.\n\n"
            "FORMATO OBLIGATORIO:\n"
            "<pensamiento>\n"
            "1. Agente y Objeto: [Quién cita a quién]\n"
            "2. Marcador y Modalidad: [Identificar verbo clave y fórmula Hyland]\n"
            "3. Clasificación de Postura: [Justificación de la relación dialéctica]\n"
            "</pensamiento>\n"
            "<salida_json>\n"
            "{\n"
            '  "autores_citados": ["Autor, Año"],\n'
            '  "tipo_relacion": "[Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion]",\n'
            '  "marcador_epistemico": "[Verbo clave]",\n'
            '  "formula_hyland": "[Fórmula Hyland]",\n'
            '  "claim_extraido": "[Afirmación literal verbatim, máx 25 palabras]"\n'
            "}\n"
            "</salida_json>"
        )
    },
    {
        "tarea": "T3_Formula_Concesion_Matizacion",
        "area": "cts-epistemologia",
        "esperado": {"tipo_relacion": "Concesion_Matizacion", "verbo": "recontextualiza"},
        "prompt": (
            "Eres el Módulo de Auditoría de Citas (Paso 3). Analiza el siguiente párrafo extraído del cuerpo de un artículo científico.\n\n"
            "PÁRRAFO:\n"
            "Si bien reconocemos la enorme pertinencia histórica del marco teórico de Latour (2005), este trabajo recontextualiza su noción de ensamblaje sociotécnico para delimitar las asimetrías de poder digital en comunidades rurales desconectadas.\n\n"
            "TAREA:\n"
            "Identifica los autores citados, la relación epistémica (Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion), el verbo clave de Hyland y el claim literal.\n\n"
            "FORMATO OBLIGATORIO:\n"
            "<pensamiento>\n"
            "1. Agente y Objeto: [Quién cita a quién]\n"
            "2. Marcador y Modalidad: [Identificar verbo clave y fórmula Hyland]\n"
            "3. Clasificación de Postura: [Justificación de la relación dialéctica]\n"
            "</pensamiento>\n"
            "<salida_json>\n"
            "{\n"
            '  "autores_citados": ["Autor, Año"],\n'
            '  "tipo_relacion": "[Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion]",\n'
            '  "marcador_epistemico": "[Verbo clave]",\n'
            '  "formula_hyland": "[Fórmula Hyland]",\n'
            '  "claim_extraido": "[Afirmación literal verbatim, máx 25 palabras]"\n'
            "}\n"
            "</salida_json>"
        )
    },
    {
        "tarea": "T3_Formula_Adopcion_Metodologica",
        "area": "educacion-apropiacion",
        "esperado": {"tipo_relacion": "Adopcion_Metodologica", "verbo": "adopta"},
        "prompt": (
            "Eres el Módulo de Auditoría de Citas (Paso 3). Analiza el siguiente párrafo extraído del cuerpo de un artículo científico.\n\n"
            "PÁRRAFO:\n"
            "Para la recolección de los datos empíricos sobre clima escolar, esta investigación adopta el cuestionario validado de López & Silva (2019), aplicando su escala Likert de 5 puntos en 12 centros educativos de la región.\n\n"
            "TAREA:\n"
            "Identifica los autores citados, la relación epistémica (Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion), el verbo clave de Hyland y el claim literal.\n\n"
            "FORMATO OBLIGATORIO:\n"
            "<pensamiento>\n"
            "1. Agente y Objeto: [Quién cita a quién]\n"
            "2. Marcador y Modalidad: [Identificar verbo clave y fórmula Hyland]\n"
            "3. Clasificación de Postura: [Justificación de la relación dialéctica]\n"
            "</pensamiento>\n"
            "<salida_json>\n"
            "{\n"
            '  "autores_citados": ["Autor, Año"],\n'
            '  "tipo_relacion": "[Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion]",\n'
            '  "marcador_epistemico": "[Verbo clave]",\n'
            '  "formula_hyland": "[Fórmula Hyland]",\n'
            '  "claim_extraido": "[Afirmación literal verbatim, máx 25 palabras]"\n'
            "}\n"
            "</salida_json>"
        )
    },
    {
        "tarea": "T3_Formula_Neutral_Mencion",
        "area": "medicina-social",
        "esperado": {"tipo_relacion": "Mencion_Contextual", "verbo": "describe"},
        "prompt": (
            "Eres el Módulo de Auditoría de Citas (Paso 3). Analiza el siguiente párrafo extraído del cuerpo de un artículo científico.\n\n"
            "PÁRRAFO:\n"
            "En un estudio previo sobre atención primaria, Pérez (2021) describe las características demográficas y los patrones de consulta de pacientes crónicos en zonas periféricas sin emitir recomendaciones prescriptivas.\n\n"
            "TAREA:\n"
            "Identifica los autores citados, la relación epistémica (Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion), el verbo clave de Hyland y el claim literal.\n\n"
            "FORMATO OBLIGATORIO:\n"
            "<pensamiento>\n"
            "1. Agente y Objeto: [Quién cita a quién]\n"
            "2. Marcador y Modalidad: [Identificar verbo clave y fórmula Hyland]\n"
            "3. Clasificación de Postura: [Justificación de la relación dialéctica]\n"
            "</pensamiento>\n"
            "<salida_json>\n"
            "{\n"
            '  "autores_citados": ["Autor, Año"],\n'
            '  "tipo_relacion": "[Consenso | Disenso | Adopcion_Metodologica | Mencion_Contextual | Concesion_Matizacion]",\n'
            '  "marcador_epistemico": "[Verbo clave]",\n'
            '  "formula_hyland": "[Fórmula Hyland]",\n'
            '  "claim_extraido": "[Afirmación literal verbatim, máx 25 palabras]"\n'
            "}\n"
            "</salida_json>"
        )
    },

    # ── TAREA 2: EXTRACCIÓN ESTRUCTURADA PCC JBI (1 Caso Conciso) ─────────────
    {
        "tarea": "T2_Extraccion_PCC_JBI",
        "area": "ciencia-tecnologia",
        "esperado": {"diseno": "Scoping review"},
        "prompt": (
            "Eres el Módulo de Extracción JBI (Paso 2). Analiza la siguiente sección de metodología de una revisión científica.\n\n"
            "METODOLOGÍA:\n"
            "Diseño: Se llevó a cabo una revisión de alcance (scoping review) conforme a las directrices metodológicas del Instituto Joanna Briggs (JBI). "
            "Población: Manuscritos que evalúan la adopción de herramientas de inteligencia artificial en pequeñas y medianas empresas (PYMES). "
            "Concepto: Modelos de madurez digital, barreras de adopción y beneficios organizacionales reportados. "
            "Contexto: Publicaciones científicas de Iberoamérica indexadas en Scopus, SciELO y Dialnet entre 2019 y 2024.\n\n"
            "TAREA:\n"
            "Extrae la matriz PCC (Población, Concepto, Contexto) y los detalles metodológicos clave de forma estructurada.\n\n"
            "FORMATO OBLIGATORIO:\n"
            "<pensamiento>\n"
            "1. Desglose Estructural: [Población / Unidades]\n"
            "2. Concepto Central: [Fenómeno evaluado]\n"
            "3. Contexto y Protocolo: [Marco temporal, geográfico y diseño]\n"
            "</pensamiento>\n"
            "<salida_json>\n"
            "{\n"
            '  "poblacion": "[Descripción literal o \'No especificado\']",\n'
            '  "concepto": "[Fenómeno central]",\n'
            '  "contexto": "[Geográfico, temporal o institucional]",\n'
            '  "diseno": "[Scoping review | Revisión sistemática | Mixto]",\n'
            '  "criterios_inclusion": "[Resumen en máximo 15 palabras]"\n'
            "}\n"
            "</salida_json>"
        )
    }
]

def consultar_lm_studio(prompt):
    payload = {
        "model": "google/gemma-4-e2b",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres el Modelo Epistémico Thinkuy especializado en Revisiones Sistemáticas, "
                    "Scoping Reviews y Epistemología Iberoamericana. Analiza con rigor lingüístico "
                    "(Hyland / Swales) y genera siempre un bloque <pensamiento> conciso antes de <salida_json>."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 1024
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
    print("AUDITORÍA DE LOTE AMPLIADO (10 CASOS): MODELO LOCAL LM STUDIO")
    print("Protocolo: CERO complacencia, CERO fallbacks. Lingüística Hyland / Swales.")
    print("=" * 80)
    
    resultados = []
    
    for idx, caso in enumerate(CASOS_PRUEBA, 1):
        tarea_nombre = caso["tarea"]
        area = caso["area"]
        prompt = caso["prompt"]
        
        print(f"\n[{idx:02d}/10] Evaluando: {tarea_nombre} ({area})...")
        
        raw_out, latencia, err = consultar_lm_studio(prompt)
        
        if err:
            print(f"  ❌ Error de conexión: {err}")
            resultados.append({
                "id": idx, "tarea": tarea_nombre, "area": area,
                "latencia_seg": 0, "status": "ERROR_CONEXION",
                "pensamiento": "", "json_extraido": {}
            })
            continue
            
        pensamiento, json_obj = parse_cot_and_json(raw_out)
        
        es_valido = (json_obj is not None)
        status = "OK_VALIDO" if es_valido else "INVALID_OUTPUT"
        
        print(f"  ⚡ Latencia GPU: {latencia:.2f}s | Estado: {status}")
        print(f"  🧠 <pensamiento>:")
        if pensamiento:
            for l in pensamiento.split("\n"):
                print(f"     {l}")
        else:
            print("     [Sin pensamiento]")
            
        print(f"  📊 <salida_json>:")
        if json_obj:
            print("     " + json.dumps(json_obj, ensure_ascii=False, indent=2).replace("\n", "\n     "))
        else:
            print(f"     ❌ No parseable. Raw: {raw_out[:200]}...")
            
        resultados.append({
            "id": idx, "tarea": tarea_nombre, "area": area,
            "latencia_seg": round(latencia, 2), "status": status,
            "pensamiento": pensamiento, "json_extraido": json_obj,
            "raw_output": raw_out
        })
        print("-" * 80)

    # Resumen Estadístico
    validos = sum(1 for r in resultados if r["status"] == "OK_VALIDO")
    print("\n" + "=" * 80)
    print(f"RESUMEN DE AUDITORÍA: {validos}/10 Respuestas Válidas ({validos*10:.1f}%)")
    print("=" * 80)
    
    with open(OUTPUT_CSV, "w", encoding="utf-8") as f:
        # Guardar en CSV estructurado
        df = pd.DataFrame(resultados)
        df.to_csv(f, index=False)
        
    print(f"Resultados guardados en: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
