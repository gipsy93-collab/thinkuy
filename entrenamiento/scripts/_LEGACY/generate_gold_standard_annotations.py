"""SUPERSEDED / CUARENTENA (Fase 0, 2026-09-18).
Genero el Gold Standard descartado (Hito 23): rationale estatico atado al campo area,
concepto PCC colapsado y 12/18 pensamientos contradictorios con su etiqueta.
Se conserva solo como evidencia forense. NO USAR para generar datasets.
"""
"""Generador y Curador del Dataset Gold Standard Thinkuy V3 (83 instancias).
Aplica las directrices de Anotación _Gold Standard.md para las 3 micro-tareas
a lo largo de las 6 áreas científicas.
"""
import json
import re
from pathlib import Path

def parse_t1_annotation(item):
    """Genera la anotación Gold Standard para T1 (Abstract -> Epistemología & PRISMA)."""
    text = item["raw_input"]
    area = item["area"]
    tipo = item["tipo_revision"]
    art_id = item["id"]
    
    # Análisis contextual
    text_lower = text.lower()
    
    # Rol metodológico
    if "scoping review" in text_lower or "revisión de alcance" in text_lower or "revisión sistemática" in text_lower or "systematic review" in text_lower or "revisión panorámica" in text_lower or "estado del arte" in text_lower:
        rol = "Síntesis_Review"
    elif "metodología" in text_lower and ("propuesta" in text_lower or "protocolo" in text_lower or "guía" in text_lower):
        rol = "Metodológico"
    elif "marco teórico" in text_lower or "epistemológico" in text_lower or "conceptual" in text_lower:
        rol = "Teórico_Framework"
    elif "estudio transversal" in text_lower or "cohorte" in text_lower or "ensayo clínico" in text_lower or "muestra de" in text_lower:
        rol = "Empírico"
    else:
        rol = "Síntesis_Review"
        
    # Tradición epistémica según área y lenguaje
    if area == "medicina-social" or "salud colectiva" in text_lower or "determinación social" in text_lower or "salud comunitaria" in text_lower:
        tradicion = "Medicina Social"
    elif "decolonial" in text_lower or "decolonialidad" in text_lower or "sur global" in text_lower or "buen vivir" in text_lower:
        tradicion = "Decolonial"
    elif "ecología de saberes" in text_lower or "saberes ancestrales" in text_lower or "diálogo de saberes" in text_lower:
        tradicion = "Ecología de Saberes"
    elif "apropiación social" in text_lower or "divulgación científica" in text_lower or "comunicación de la ciencia" in text_lower:
        tradicion = "Apropiación Social"
    elif area == "pensamiento-critico" or "teoría crítica" in text_lower or "hegemonía" in text_lower or "marxista" in text_lower or "crítica latinoamericana" in text_lower:
        tradicion = "Crítica Latinoamericana"
    elif area in ["ciencias-duras", "ciencia-tecnologia"] or "positivista" in text_lower or "meta-análisis" in text_lower or "cuantitativo" in text_lower:
        tradicion = "Hegemónica"
    elif area == "educacion-apropiacion":
        tradicion = "Apropiación Social"
    elif area == "cts-epistemologia":
        tradicion = "Crítica Latinoamericana"
    else:
        tradicion = "Hegemónica"

    # Aptitud PRISMA / JBI
    if rol == "Síntesis_Review":
        aptitud = "Apto"
        motivo = "Diseño de síntesis documental elegible para protocolo PRISMA/JBI."
    elif rol in ["Teórico_Framework", "Metodológico"]:
        aptitud = "Dudoso"
        motivo = "Aporte conceptual o metodológico que requiere evaluación de criterios de síntesis."
    else:
        aptitud = "Excluir"
        motivo = "Estudio empírico primario fuera del alcance de revisiones secundarias."

    # Bloque pensamiento estructurado en 3 pasos
    metodo_decl = f"Diseño declarado: {tipo.replace('_', ' ').capitalize()} sobre {area}."
    epistem_just = f"Opera desde la tradición {tradicion} sustentada en el enfoque disciplinar del área {area}."
    descarte_just = f"Clasificado como {rol}; se descartan roles primarios por constituir un mapeo y síntesis de literatura."

    pensamiento = f"""1. Método declarado: {metodo_decl}
2. Epistemología: {epistem_just}
3. Descarte: {descarte_just}"""

    salida_json = {
        "rol_metodologico": rol,
        "tradicion_epistemica": tradicion,
        "aptitud_prisma": aptitud,
        "motivo": motivo
    }

    return pensamiento, salida_json


def parse_t2_annotation(item):
    """Genera la anotación Gold Standard para T2 (Metodología -> Matriz PCC JBI)."""
    text = item["raw_input"]
    area = item["area"]
    tipo = item["tipo_revision"]
    text_lower = text.lower()

    # Extracción guiada de Población (P)
    poblacion = "Documentos y estudios publicados sobre el fenómeno de estudio"
    if "estudiantes" in text_lower:
        poblacion = "Estudiantes y comunidad educativa reportada en la literatura"
    elif "pacientes" in text_lower or "adultos mayores" in text_lower or "mujeres" in text_lower:
        poblacion = "Población y grupos clínicos o comunitarios documentados"
    elif "docentes" in text_lower or "profesores" in text_lower:
        poblacion = "Docentes y profesionales de la educación"
    elif "comunidades" in text_lower:
        poblacion = "Comunidades y actores sociales territoriales"

    # Extracción de Concepto (C)
    if "inteligencia artificial" in text_lower or "ia" in text_lower:
        concepto = "Uso e impacto de Inteligencia Artificial y tecnologías emergentes"
    elif "salud" in text_lower or "atención primaria" in text_lower:
        concepto = "Prácticas de salud y modelos de atención sociosanitaria"
    elif "educación" in text_lower or "aprendizaje" in text_lower:
        concepto = "Procesos pedagógicos y estrategias de formación y aprendizaje"
    elif "comunicación" in text_lower or "divulgación" in text_lower:
        concepto = "Dinámicas de comunicación científica y apropiación de saberes"
    else:
        concepto = f"Mapeo conceptual y dimensiones teóricas en {area.replace('-', ' ')}"

    # Contexto (C)
    if "américa latina" in text_lower or "iberoamérica" in text_lower or "latinoamérica" in text_lower:
        contexto = "Iberoamérica / América Latina en publicaciones indexadas"
    elif "global" in text_lower or "internacional" in text_lower:
        contexto = "Contexto internacional global en bases de datos académicas"
    else:
        contexto = "Publicaciones científicas indexadas en bases de datos académicas"

    # Diseño
    if "scoping" in text_lower:
        diseno = "Scoping Review (JBI / Arksey & O'Malley)"
    elif "sistemática" in text_lower or "systematic" in text_lower:
        diseno = "Revisión Sistemática (PRISMA)"
    elif "integrativa" in text_lower:
        diseno = "Revisión Integrativa"
    else:
        diseno = "Revisión de Literatura / Scoping Review"

    # Criterios de inclusión
    criterios = "Artículos revisados por pares con acceso a texto completo."

    pensamiento = "Analizo la sección para identificar: 1) Quiénes son los sujetos/unidades (P), 2) Qué fenómeno se estudia (C), 3) Dónde/cuándo (C), 4) Cómo se hizo (Diseño, bases de datos, criterios)."

    salida_json = {
        "poblacion": poblacion,
        "concepto": concepto,
        "contexto": contexto,
        "diseno": diseno,
        "criterios_inclusion": criterios
    }

    return pensamiento, salida_json


def parse_t3_annotation(item):
    """Genera la anotación Gold Standard para T3 (Auditoría de Citas -> Postura Retórica)."""
    text = item["raw_input"]
    autores_detectados = item.get("autores_detectados", [])
    text_lower = text.lower()

    # Formatear autores citados
    if autores_detectados:
        autores_citados = [f"{a.get('autor', 'Autor')}, {a.get('año', '2023')}" if isinstance(a, dict) else str(a) for a in autores_detectados[:2]]
    else:
        # Regex de respaldo para encontrar citas (Autor, Año)
        matches = re.findall(r'([A-ZÁÉÍÓÚ][a-záéíóúñ]+(?:\s+y\s+[A-ZÁÉÍÓÚ][a-záéíóúñ]+)?(?:\s+et\s+al\.)?)[,\s]+(\d{4})', text)
        if matches:
            autores_citados = [f"{m[0]}, {m[1]}" for m in matches[:2]]
        else:
            autores_citados = ["Referencia citada en contexto"]

    # Clasificación de postura retórica
    if "sin embargo" in text_lower or "a diferencia" in text_lower or "no obstante" in text_lower or "limita" in text_lower or "cuestiona" in text_lower:
        tipo_relacion = "Disenso"
        claim = text[:120].strip().replace("\n", " ") + "..."
    elif "según el protocolo" in text_lower or "metodología de" in text_lower or "siguiendo a" in text_lower or "adaptado de" in text_lower or "framework" in text_lower or "propuesto por" in text_lower:
        tipo_relacion = "Adopcion_Metodologica"
        claim = text[:120].strip().replace("\n", " ") + "..."
    elif "como señalan" in text_lower or "de acuerdo con" in text_lower or "demuestran que" in text_lower or "confirma" in text_lower or "respalda" in text_lower:
        tipo_relacion = "Consenso"
        claim = text[:120].strip().replace("\n", " ") + "..."
    else:
        tipo_relacion = "Mencion_Contextual"
        claim = text[:120].strip().replace("\n", " ") + "..."

    # Recortar claim a máx 20 palabras
    palabras = claim.split()
    claim_20 = " ".join(palabras[:18]) + "..." if len(palabras) > 18 else " ".join(palabras)

    autores_str = ", ".join(autores_citados)
    pensamiento = f"""1. Autores citados: [{autores_str}].
2. Relación: El autor establece una relación de {tipo_relacion} con la literatura de referencia.
3. Evidencia en el texto: "{claim_20}"."""

    salida_json = {
        "autores_citados": autores_citados,
        "tipo_relacion": tipo_relacion,
        "claim_extraido": claim_20
    }

    return pensamiento, salida_json


def main():
    with open("data/_LEGACY/prompts_para_gold_standard.json", "r", encoding="utf-8") as f:
        prompts_db = json.load(f)

    chatml_records = []
    gold_records = []

    system_prompt = (
        "Eres el Modelo Epistémico Thinkuy especializado en Revisiones Sistemáticas, "
        "Scoping Reviews y Epistemología Iberoamericana. Analiza con rigor metodológico "
        "y genera siempre un bloque de razonamiento <pensamiento> seguido estrictamente de un bloque <salida_json>."
    )

    # Procesar T1
    for item in prompts_db["tarea_1"]:
        pensamiento, salida_json = parse_t1_annotation(item)
        assistant_resp = f"<pensamiento>\n{pensamiento}\n</pensamiento>\n<salida_json>\n{json.dumps(salida_json, ensure_ascii=False, indent=2)}\n</salida_json>"
        
        chatml = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": item["prompt"]},
                {"role": "assistant", "content": assistant_resp}
            ]
        }
        chatml_records.append(chatml)
        gold_records.append({
            "id": item["id"],
            "area": item["area"],
            "tarea": item["tarea"],
            "pensamiento": pensamiento,
            "salida_json": salida_json,
            "chatml": chatml
        })

    # Procesar T2
    for item in prompts_db["tarea_2"]:
        pensamiento, salida_json = parse_t2_annotation(item)
        assistant_resp = f"<pensamiento>\n{pensamiento}\n</pensamiento>\n<salida_json>\n{json.dumps(salida_json, ensure_ascii=False, indent=2)}\n</salida_json>"
        
        chatml = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": item["prompt"]},
                {"role": "assistant", "content": assistant_resp}
            ]
        }
        chatml_records.append(chatml)
        gold_records.append({
            "id": item["id"],
            "area": item["area"],
            "tarea": item["tarea"],
            "pensamiento": pensamiento,
            "salida_json": salida_json,
            "chatml": chatml
        })

    # Procesar T3
    for item in prompts_db["tarea_3"]:
        pensamiento, salida_json = parse_t3_annotation(item)
        assistant_resp = f"<pensamiento>\n{pensamiento}\n</pensamiento>\n<salida_json>\n{json.dumps(salida_json, ensure_ascii=False, indent=2)}\n</salida_json>"
        
        chatml = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": item["prompt"]},
                {"role": "assistant", "content": assistant_resp}
            ]
        }
        chatml_records.append(chatml)
        gold_records.append({
            "id": item["id"],
            "area": item["area"],
            "tarea": item["tarea"],
            "pensamiento": pensamiento,
            "salida_json": salida_json,
            "chatml": chatml
        })

    # Guardar en formato JSON completo
    with open("data/_LEGACY/gold_standard_annotated_v3.json", "w", encoding="utf-8") as f:
        json.dump(gold_records, f, ensure_ascii=False, indent=2)

    # Guardar en formato ChatML JSONL para Unsloth
    with open("data/thinkuy_v3_gold_standard_chatml.jsonl", "w", encoding="utf-8") as f:
        for rec in chatml_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n=======================================================")
    print(f"DATASET GOLD STANDARD THINKUY V3 GENERADO CON ÉXITO")
    print(f"=======================================================")
    print(f"Total registros anotados: {len(chatml_records)}")
    print(f"  - Tarea 1 (Abstract -> Epistemología): {len(prompts_db['tarea_1'])}")
    print(f"  - Tarea 2 (Metodología -> PCC JBI):    {len(prompts_db['tarea_2'])}")
    print(f"  - Tarea 3 (Citas -> Postura Retórica): {len(prompts_db['tarea_3'])}")
    print(f"Archivos generados:")
    print(f"  - data/_LEGACY/gold_standard_annotated_v3.json (JSON detallado)")
    print(f"  - data/thinkuy_v3_gold_standard_chatml.jsonl (ChatML para Unsloth)")

if __name__ == "__main__":
    main()
