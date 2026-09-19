"""Generador del Dataset Maestro Epistémico V2:
1. Predominio del Español (> 75%).
2. Incorporación masiva de léxico académico culto y rebuscado (verbos, sustantivos y adjetivos de alta complejidad retórica).
3. Razonamiento Previo (Chain-of-Thought 'rationale' en JSON) para resolver concesiones e ironías antes de la postura.
4. Minería de Negativos Difíciles (Hard Negatives) para distinguir citas neutrales con léxico afirmativo frente a consensos reales.
5. Salidas en formatos Alpaca y ChatML.
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

SYSTEM_PROMPT_V2 = (
    "Eres un asistente de análisis epistemológico y retórico de literatura científica especializada en español. "
    "Tu labor es evaluar el párrafo donde un artículo cita a otra obra y clasificar su función retórica "
    "en una de estas 4 categorías exactas:\n"
    "- supporting_or_agreement: posible consenso (el autor apoya, confirma, replica o halla evidencia a favor).\n"
    "- contrasting_or_refuting: posible disenso (el autor cuestiona, contradice, refuta, señala inconsistencias o límites).\n"
    "- methodological_adoption: posible adopción metodológica (se adopta o adapta método, escala, software, diseño o protocolo).\n"
    "- neutral_or_mention: posible mención contextual (mención de estado del arte o literatura previa sin postura activa).\n\n"
    "REGLA OBLIGATORIA: Primero emite un 'rationale' (breve diagnóstico retórico de 10 a 20 palabras que analice "
    "conectores, léxico culto y función argumental). Luego declara 'stance', extrae el 'claim' literal exacto del texto "
    "(subcadena idéntica sin alterar, máximo 25 palabras; o cadena vacía si es neutral) y 'confidence'.\n"
    "Responde ÚNICAMENTE un JSON con: {\"rationale\": \"...\", \"stance\": \"...\", \"claim\": \"...\", \"confidence\": \"high|low\"}."
)

# Léxico académico rebuscado
VERBOS_DISENSO = ["impugna", "soslaya", "adolece de", "desvirtúa", "desdeña", "desestima", "objeta", "controviértese", "pone en tela de juicio", "refuta", "discrepa de", "desacredita", "invalida", "arguye falacias en"]
SUSTANTIVOS_DISENSO = ["un sesgo palmario", "una aporía metodológica", "un anacronismo conceptual", "un yerro analítico", "una falacia de generalización", "una parquedad empírica", "índices endebles", "una anfibología interpretativa"]
ADJETIVOS_DISENSO = ["espurio", "inconcluso", "endeble", "baladí", "cuestionable", "deficiente", "inconsistente", "deleznable"]

VERBOS_CONSENSO = ["refrenda", "convalida", "rubrica", "suscribe", "colige en concordancia con", "corrobora", "valida empíricamente", "apuntala la tesis de", "ratifica", "preconiza congruentemente con"]
SUSTANTIVOS_CONSENSO = ["hallazgos fidedignos", "evidencia prístina", "plausibilidad teórica", "consistencia empírica", "validez convergente", "rigor metodológico", "concordancia axiomática"]
ADJETIVOS_CONSENSO = ["fidedigno", "prístino", "irrefutable", "concluyente", "robusto", "sólido", "taxativo"]

VERBOS_METODO = ["adopta el diseño de", "extrapola el protocolo de", "emplea la escala validada por", "implementa la taxonomía de", "se supedita a la métrica propuesta por", "reproduce la heurística de", "instrumentaliza la matriz de"]
SUSTANTIVOS_METODO = ["la heurística algorítmica", "el constructo psicométrico", "el dispositivo analítico", "la matriz categorial", "el protocolo experimental", "el baremo estandarizado", "la rúbrica analítica"]

VERBOS_NEUTRO = ["esgrime en su disquisición", "alude a los antecedentes de", "recapitula la doctrina de", "sitúa el estado del arte conforme a", "consigna la producción bibliográfica de", "entronca con la tradición de", "expone en su exégesis"]
SUSTANTIVOS_NEUTRO = ["la profusa literatura de", "el marco referencial de", "la exégesis teórica de", "el axioma clásico de", "la perspectiva fundacional de", "el corpus documental de"]

AUTORES = [
    "García y Martínez (2020)", "Fernández (2019)", "Pérez et al. (2021)", "Duque y Cervantes (2019)",
    "Hernández-Zamora (2022)", "Moravcsik y Murugesan (1975)", "Vallaeys (2018)", "López-Cózar et al. (2023)",
    "Castillo y Rodríguez (2021)", "Mendoza et al. (2022)", "Navarro (2020)", "Santillán y Romero (2023)",
    "Bourdieu (1986)", "Toulmin (1958)", "Vargas y Gómez (2022)", "Albornoz et al. (2021)"
]

TEMAS = [
    "la responsabilidad social universitaria", "la evaluación cienciométrica", "la deserción estudiantil",
    "el rendimiento neurocognitivo", "la gobernanza institucional", "la brecha de género académica",
    "la citación normativa en Scopus", "el aprendizaje basado en problemas", "la competencia digital docente",
    "la apropiación social del conocimiento", "la dinámica de co-citación bibliográfica"
]


def generate_high_register_spanish_corpus(n_samples: int = 4000) -> List[Dict[str, Any]]:
    """Genera citas en Español con léxico académico culto y diagnóstico retórico previo."""
    samples = []
    
    # 1. Disensos (con giros concesivos, ironías y refutaciones explícitas)
    for _ in range(n_samples // 4):
        autor = random.choice(AUTORES)
        tema = random.choice(TEMAS)
        verbo = random.choice(VERBOS_DISENSO)
        sust = random.choice(SUSTANTIVOS_DISENSO)
        adj = random.choice(ADJETIVOS_DISENSO)
        
        casos = [
            (
                f"Si bien {autor} preconiza que {tema} exhibe estabilidad, nuestro estudio {verbo} dicha aseveración al constatar {sust}.",
                f"El autor concede mérito preliminar pero {verbo} la tesis central de la obra citada aportando evidencia disonante.",
                f"nuestro estudio {verbo} dicha aseveración al constatar {sust}"
            ),
            (
                f"A diferencia del optimismo que esgrime {autor}, las pruebas empíricas demuestran que su postulado {adj} {verbo} por {sust}.",
                f"Objeción retórica y empírica explícita que invalida las conclusiones previas por debilidad metodológica.",
                f"su postulado {adj} {verbo} por {sust}"
            ),
            (
                f"Aunque la disquisición de {autor} resulta sugerente, adolece de {sust}, tornando sus inferencias en un planteamiento {adj}.",
                f"Crítica académica profunda que expone limitaciones analíticas sustanciales en el estudio referenciado.",
                f"adolece de {sust}, tornando sus inferencias en un planteamiento {adj}"
            ),
            (
                f"Nuestros contrastes estadísticos desvirtúan de modo palmario el modelo de {autor}, evidenciando {sust}.",
                f"Refutación terminante sustentada en incompatibilidad estadística con el modelo teórico previo.",
                f"desvirtúan de modo palmario el modelo de {autor}, evidenciando {sust}"
            )
        ]
        texto, rationale, claim = random.choice(casos)
        samples.append({
            "text": texto,
            "section": random.choice(["Discusión", "Resultados y Discusión", "Análisis Crítico"]),
            "rationale": rationale,
            "stance": "contrasting_or_refuting",
            "claim": claim,
            "confidence": "high",
            "lang": "es"
        })

    # 2. Consensos (convalidación, refrendo y convergencia)
    for _ in range(n_samples // 4):
        autor = random.choice(AUTORES)
        tema = random.choice(TEMAS)
        verbo = random.choice(VERBOS_CONSENSO)
        sust = random.choice(SUSTANTIVOS_CONSENSO)
        adj = random.choice(ADJETIVOS_CONSENSO)
        
        casos = [
            (
                f"Los resultados de nuestra cohorte {verbo} la tesis de {autor}, ratificando {sust} en el contexto analizado.",
                f"El autor corrobora los hallazgos previos confirmando la hipótesis con datos empíricos convergentes.",
                f"nuestra cohorte {verbo} la tesis de {autor}, ratificando {sust}"
            ),
            (
                f"En perfecta consonancia con lo discernido por {autor}, se constata que {tema} opera como un factor {adj}.",
                f"Adhesión teórica explícita que suscribe el planteamiento doctrinal del estudio antecedente.",
                f"En perfecta consonancia con lo discernido por {autor}"
            ),
            (
                f"Nuestros datos aportan una prueba {adj} que {verbo} de forma taxativa los postulados de {autor}.",
                f"Aportación de evidencia a favor que convalida y robustece la investigación referenciada.",
                f"aportan una prueba {adj} que {verbo} de forma taxativa"
            )
        ]
        texto, rationale, claim = random.choice(casos)
        samples.append({
            "text": texto,
            "section": random.choice(["Resultados", "Discusión", "Conclusiones"]),
            "rationale": rationale,
            "stance": "supporting_or_agreement",
            "claim": claim,
            "confidence": "high",
            "lang": "es"
        })

    # 3. Adopción Metodológica (instrumentos, escalas, baremos, algoritmos)
    for _ in range(n_samples // 4):
        autor = random.choice(AUTORES)
        verbo = random.choice(VERBOS_METODO)
        sust = random.choice(SUSTANTIVOS_METODO)
        
        casos = [
            (
                f"Para la operacionalización de las variables, esta investigación {verbo} {autor}, aplicando {sust}.",
                f"Adopción metodológica directa donde se asume el protocolo o escala validada por la obra citada.",
                f"esta investigación {verbo} {autor}, aplicando {sust}"
            ),
            (
                f"Siguiendo la pauta estandarizada por {autor}, se procedió a calibrar {sust} bajo un diseño cuasiexperimental.",
                f"Implementación instrumental que replica y calibra la técnica procedural del autor antecedente.",
                f"Siguiendo la pauta estandarizada por {autor}, se procedió a calibrar {sust}"
            ),
            (
                f"El análisis de conglomerados se estructuró a partir de {sust} desarrollada originalmente por {autor}.",
                f"Utilización operativa de un dispositivo o algoritmo analítico formulado por la fuente citada.",
                f"se estructuró a partir de {sust} desarrollada originalmente por {autor}"
            )
        ]
        texto, rationale, claim = random.choice(casos)
        samples.append({
            "text": texto,
            "section": random.choice(["Metodología", "Materiales y Métodos", "Diseño Experimental"]),
            "rationale": rationale,
            "stance": "methodological_adoption",
            "claim": claim,
            "confidence": "high",
            "lang": "es"
        })

    # 4. Negativos Difíciles (Hard Negatives): Citas Neutras con vocabulario culto
    for _ in range(n_samples // 4):
        autor = random.choice(AUTORES)
        tema = random.choice(TEMAS)
        verbo = random.choice(VERBOS_NEUTRO)
        sust = random.choice(SUSTANTIVOS_NEUTRO)
        
        casos = [
            (
                f"Conforme {verbo} {autor}, {tema} ha constituido históricamente un objeto de profuso debate sociológico.",
                f"Mención contextual del estado del arte; el autor cita un antecedente teórico sin manifestar postura propia.",
                ""
            ),
            (
                f"En la literatura especializada, {sust} {autor} plantea las directrices canónicas sobre la materia.",
                f"Referencia expositiva de doctrina académica; mención de fondo que no implica validación empírica activa.",
                ""
            ),
            (
                f"Tal como consigna {autor} en su influyente monografía, las instituciones experimentan transformaciones continuas.",
                f"Cita informativa en el marco teórico; no constituye consenso activo ni refutación empírica.",
                ""
            ),
            (
                f"La evolución epistemológica de este campo ha sido documentada exhaustivamente en los trabajos de {autor}.",
                f"Atribución bibliográfica general de antecedentes; mención neutral sin adhesión ni juicio crítico.",
                ""
            )
        ]
        texto, rationale, claim = random.choice(casos)
        samples.append({
            "text": texto,
            "section": random.choice(["Introducción", "Marco Teórico", "Estado del Arte", "Antecedentes"]),
            "rationale": rationale,
            "stance": "neutral_or_mention",
            "claim": claim,
            "confidence": "high",
            "lang": "es"
        })

    return samples


def generate_cot_for_existing_sample(input_str: str, output_obj: dict) -> dict:
    """Genera un diagnóstico retórico adecuado para una muestra preexistente."""
    stance = output_obj.get("stance", "neutral_or_mention")
    claim = output_obj.get("claim", "")
    
    # Extraer texto entre comillas
    m = re.search(r'Contexto de citación:\s*"(.*?)"', input_str, re.DOTALL)
    text = m.group(1) if m else input_str
    
    is_spanish = any(w in text.lower() for w in [" el ", " la ", " en ", " de ", " que ", " se ", " por ", " los ", " las ", " con "])
    
    if stance == "contrasting_or_refuting":
        if is_spanish:
            rationale = "El autor introduce objeciones, evidencia disonante o límites metodológicos que contradicen la obra citada."
        else:
            rationale = "The author presents conflicting findings, limitations, or empirical counterevidence challenging the cited study."
    elif stance == "supporting_or_agreement":
        if is_spanish:
            rationale = "El autor aporta evidencia confirmatoria y replica favorablemente las tesis del estudio citado."
        else:
            rationale = "The empirical data supports, replicates, or aligns positively with the findings of the cited work."
    elif stance == "methodological_adoption":
        if is_spanish:
            rationale = "El estudio adopta, adapta o emplea el instrumento, escala o diseño metodológico propuesto por el autor."
        else:
            rationale = "The manuscript explicitly adapts or utilizes the specific method, tool, protocol, or scale from the cited source."
    else:
        if is_spanish:
            rationale = "Mención expositiva del estado del arte o marco referencial sin compromiso empírico de adhesión o rechazo."
        else:
            rationale = "Background context or literature review mention without active empirical consensus or refutation."

    return {
        "rationale": rationale,
        "stance": stance,
        "claim": claim,
        "confidence": output_obj.get("confidence", "high")
    }


def main():
    print("=" * 85)
    print("GENERADOR MASTER DEL DATASET EPISTÉMICO V2 (CoT + LÉXICO CULTO + ESPAÑOL DOMINANTE)")
    print("=" * 85)

    # 1. Generar 8.000 citas sintéticas de altísimo registro culto en Español
    print("\n1. Generando 8.000 citas con léxico académico rebuscado en Español...")
    high_spanish = generate_high_register_spanish_corpus(n_samples=8000)
    print(f"✓ Generadas {len(high_spanish)} citas cultas en Español.")

    # 2. Cargar y enriquecer el dataset anterior de 6.032 citas
    print("\n2. Ingestando y dotando de CoT Rationale a las 6.032 citas previas...")
    enriched_prev = []
    prev_train_path = Path("data/epistemic_train.jsonl")
    if prev_train_path.exists():
        with open(prev_train_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    out_obj = json.loads(obj["output"])
                    new_out = generate_cot_for_existing_sample(obj["input"], out_obj)
                    
                    # Extraer texto y seccion
                    m_sec = re.search(r'Sección:\s*(.*)', obj["input"])
                    sec = m_sec.group(1).strip() if m_sec else "Cuerpo del manuscrito"
                    m_txt = re.search(r'Contexto de citación:\s*"(.*?)"', obj["input"], re.DOTALL)
                    txt = m_txt.group(1) if m_txt else obj["input"]
                    
                    enriched_prev.append({
                        "text": txt,
                        "section": sec,
                        "rationale": new_out["rationale"],
                        "stance": new_out["stance"],
                        "claim": new_out["claim"],
                        "confidence": new_out["confidence"]
                    })
                except Exception:
                    continue
    print(f"✓ Enriquecidas {len(enriched_prev)} citas previas.")

    # 3. Consolidar dataset maestro
    all_records = high_spanish + enriched_prev
    random.seed(42)
    random.shuffle(all_records)

    total_len = len(all_records)
    n_test = int(total_len * 0.10)
    test_set = all_records[:n_test]
    train_set = all_records[n_test:]

    spanish_count = len([x for x in train_set if any(w in x["text"].lower() for w in [" el ", " la ", " en ", " de ", " que ", " se ", " por ", " los ", " las ", " con "])])
    spanish_ratio = (spanish_count / len(train_set)) * 100

    print(f"\n3. Estadísticas Finales del Dataset Maestro V2:")
    print(f"   • Total Muestras: {total_len}")
    print(f"   • Entrenamiento (Train): {len(train_set)}")
    print(f"   • Evaluación Ciega (Test Holdout): {len(test_set)}")
    print(f"   • Proporción en Español: {spanish_ratio:.1f}% (Predominio Absoluto)")

    # 4. Guardar archivos Alpaca y ChatML
    Path("data").mkdir(exist_ok=True)

    # A. Train Alpaca CoT
    train_path = "data/epistemic_train_cot.jsonl"
    with open(train_path, "w", encoding="utf-8") as f:
        for item in train_set:
            input_text = f'Sección: {item["section"]}\nContexto de citación: "{item["text"]}"'
            out_json = json.dumps({
                "rationale": item["rationale"],
                "stance": item["stance"],
                "claim": item["claim"],
                "confidence": item["confidence"]
            }, ensure_ascii=False)
            f.write(json.dumps({
                "instruction": SYSTEM_PROMPT_V2,
                "input": input_text,
                "output": out_json
            }, ensure_ascii=False) + "\n")

    # B. Test Alpaca CoT
    test_path = "data/epistemic_test_cot.jsonl"
    with open(test_path, "w", encoding="utf-8") as f:
        for item in test_set:
            input_text = f'Sección: {item["section"]}\nContexto de citación: "{item["text"]}"'
            out_json = json.dumps({
                "rationale": item["rationale"],
                "stance": item["stance"],
                "claim": item["claim"],
                "confidence": item["confidence"]
            }, ensure_ascii=False)
            f.write(json.dumps({
                "instruction": SYSTEM_PROMPT_V2,
                "input": input_text,
                "output": out_json
            }, ensure_ascii=False) + "\n")

    # C. Train ChatML CoT
    train_chatml_path = "data/epistemic_train_cot_chatml.jsonl"
    with open(train_chatml_path, "w", encoding="utf-8") as f:
        for item in train_set:
            input_text = f'Sección: {item["section"]}\nContexto de citación: "{item["text"]}"'
            out_json = json.dumps({
                "rationale": item["rationale"],
                "stance": item["stance"],
                "claim": item["claim"],
                "confidence": item["confidence"]
            }, ensure_ascii=False)
            f.write(json.dumps({
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_V2},
                    {"role": "user", "content": input_text},
                    {"role": "assistant", "content": out_json}
                ]
            }, ensure_ascii=False) + "\n")

    # D. Test ChatML CoT
    test_chatml_path = "data/epistemic_test_cot_chatml.jsonl"
    with open(test_chatml_path, "w", encoding="utf-8") as f:
        for item in test_set:
            input_text = f'Sección: {item["section"]}\nContexto de citación: "{item["text"]}"'
            out_json = json.dumps({
                "rationale": item["rationale"],
                "stance": item["stance"],
                "claim": item["claim"],
                "confidence": item["confidence"]
            }, ensure_ascii=False)
            f.write(json.dumps({
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_V2},
                    {"role": "user", "content": input_text},
                    {"role": "assistant", "content": out_json}
                ]
            }, ensure_ascii=False) + "\n")

    print(f"\n✓ 4 Archivos generados limpiamente:")
    print(f"  → {train_path} ({len(train_set)} citas)")
    print(f"  → {test_path} ({len(test_set)} citas)")
    print(f"  → {train_chatml_path}")
    print(f"  → {test_chatml_path}")


if __name__ == "__main__":
    main()
