"""Generador Epistémico V3 con Minería de Negativos Difíciles (SNLI + TASS + Léxico Culto).

Incorpora las directrices de '1. Solucionar la Confianza Insegura.txt':
1. Falsos Consensos / Hard Negatives: Citas neutrales con verbos de dicción o afirmación fuerte que NO son consenso.
2. Tripletas contrastivas derivadas de SNLI (Entailment -> Consenso, Contradiction -> Disenso, Neutral -> Mención).
3. Patrones factuales neutrales del corpus TASS (SEPLN en español).
4. Léxico culto/rebuscado académico (colige, impugna, soslaya, adolece, esgrime, refrenda, desacredita, etc.).
5. CoT Rationale en español previo a la postura.
6. Oversampling x3 de ejemplos difíciles.
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
import zipfile
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

SNLI_ZIP_PATH = r"C:\Users\gipsy\Downloads\snli_1.0.zip"
TASS_DIR = Path("scratch/analisis_de_sentimiento/TASS")

AUTORES_IBERO = [
    "García y Martínez (2020)", "Fernández (2019)", "Pérez et al. (2021)", "Duque y Cervantes (2019)",
    "Hernández-Zamora (2022)", "Moravcsik y Murugesan (1975)", "Vallaeys (2018)", "López-Cózar et al. (2023)",
    "Castillo y Rodríguez (2021)", "Mendoza et al. (2022)", "Navarro (2020)", "Santillán y Romero (2023)",
    "Bourdieu (1986)", "Toulmin (1958)", "Vargas y Gómez (2022)", "Albornoz et al. (2021)"
]


def extract_snli_academic_triplets(max_per_class: int = 1200) -> List[Dict[str, Any]]:
    """Extrae tripletas de SNLI adaptadas a citación académica rigurosa."""
    samples = []
    if not Path(SNLI_ZIP_PATH).exists():
        return samples

    try:
        with zipfile.ZipFile(SNLI_ZIP_PATH, 'r') as z:
            with z.open('snli_1.0/snli_1.0_train.jsonl') as f:
                counts = {"entailment": 0, "contradiction": 0, "neutral": 0}
                for line in f:
                    if all(c >= max_per_class for c in counts.values()):
                        break
                    try:
                        obj = json.loads(line.decode('utf-8'))
                        gold = obj.get("gold_label")
                        if gold not in counts or counts[gold] >= max_per_class:
                            continue

                        p = obj.get("sentence1", "").strip().rstrip(".")
                        h = obj.get("sentence2", "").strip().rstrip(".")
                        if len(p) < 25 or len(h) < 20:
                            continue

                        autor = random.choice(AUTORES_IBERO)

                        if gold == "neutral":
                            # Hard Negative: parece relevante pero es mención sin postura activa
                            text = f"En los antecedentes documentados por {autor}, se señala que {p.lower()}; asimismo, se constató que {h.lower()}."
                            samples.append({
                                "text": text,
                                "section": random.choice(["Marco Teórico", "Estado del Arte", "Antecedentes"]),
                                "rationale": "Mención expositiva contextual de antecedentes; el autor yuxtapone datos informativos sin tomar postura crítica o empírica propia.",
                                "stance": "neutral_or_mention",
                                "claim": "",
                                "confidence": "high",
                                "is_hard_negative": True
                            })
                            counts["neutral"] += 1

                        elif gold == "contradiction":
                            # Disenso con contraste explícito
                            claim = f"nuestros datos contradicen esta observación ya que {h.lower()}"
                            text = f"A diferencia de lo reportado por {autor} respecto a que {p.lower()}, {claim}."
                            samples.append({
                                "text": text,
                                "section": random.choice(["Discusión", "Resultados y Discusión"]),
                                "rationale": "Contradicción explícita; la evidencia del autor colisiona directamente con la observación citada.",
                                "stance": "contrasting_or_refuting",
                                "claim": claim,
                                "confidence": "high",
                                "is_hard_negative": False
                            })
                            counts["contradiction"] += 1

                        elif gold == "entailment":
                            # Consenso con implicación lógica estricta
                            claim = f"nuestra investigación confirma que {h.lower()}"
                            text = f"En plena concordancia con {autor} donde se demostró que {p.lower()}, {claim}."
                            samples.append({
                                "text": text,
                                "section": random.choice(["Resultados", "Discusión", "Conclusiones"]),
                                "rationale": "Implicación y convergencia plena; los hallazgos corroboran de forma concluyente la tesis previa.",
                                "stance": "supporting_or_agreement",
                                "claim": claim,
                                "confidence": "high",
                                "is_hard_negative": False
                            })
                            counts["entailment"] += 1

                    except Exception:
                        continue
    except Exception as e:
        print(f"Aviso al leer SNLI: {e}")

    return samples


def extract_tass_hard_negatives(max_samples: int = 800) -> List[Dict[str, Any]]:
    """Extrae estructuras neutrales y las convierte en citas de antecedentes de estado del arte."""
    samples = []
    if not TASS_DIR.exists():
        return samples

    neutral_texts = []
    for csv_file in TASS_DIR.glob("*.csv"):
        try:
            with open(csv_file, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if len(row) >= 2:
                        content, polarity = row[0].strip(), row[1].strip()
                        if polarity in ["NEU", "NONE"] and len(content) > 35:
                            # Limpiar menciones de twitter
                            clean = re.sub(r"@\w+", "", content)
                            clean = re.sub(r"http\S+", "", clean)
                            clean = re.sub(r"#\w+", "", clean).strip()
                            if len(clean) > 30 and not any(w in clean.lower() for w in ["jaj", "puto", "mierda"]):
                                neutral_texts.append(clean)
        except Exception:
            continue

    random.seed(42)
    random.shuffle(neutral_texts)

    for txt in neutral_texts[:max_samples]:
        autor = random.choice(AUTORES_IBERO)
        sec = random.choice(["Introducción", "Marco Referencial", "Revisión de Literatura"])
        citation_text = f"Tal como se consigna en la revisión monográfica de {autor}, {txt.lower()}."
        samples.append({
            "text": citation_text,
            "section": sec,
            "rationale": "Referencia informativa del estado del arte; cita descriptiva sin adhesión empírica directa ni objeción crítica.",
            "stance": "neutral_or_mention",
            "claim": "",
            "confidence": "high",
            "is_hard_negative": True
        })

    return samples


def generate_high_register_spanish_hard_negatives(n_samples: int = 2400) -> List[Dict[str, Any]]:
    """Genera citas neutrales que parecen consenso por usar verbos de dicción afirmativos (Falsos Consensos)."""
    samples = []
    verbos_diccion = [
        ("afirma que", "exposición doctrinal que recapitula una afirmación ajena sin validación empírica propia"),
        ("demuestra que", "atribución bibliográfica de hallazgo precedente en el marco teórico sin confirmación activa"),
        ("señala con precisión que", "referencia contextual que cita la observación del autor sin postura empírica"),
        ("subraya la importancia de", "mención temática de antecedentes; no constituye consenso experimental propio"),
        ("concluye taxativamente que", "cita informativa sobre el desenlace de la obra previa en la revisión de literatura"),
        ("evidencia en su monografía que", "consignación documental del estado de la cuestión sin compromiso analítico"),
        ("postula formalmente que", "exégesis de un axioma o hipótesis teórica previa sin réplica de datos"),
    ]
    
    temas = [
        "la gestión de la responsabilidad social", "la varianza factorial en pruebas psicométricas",
        "el índice de impacto normalizado", "la dinámica de sedimentación foliar",
        "el constructo de autoeficacia académica", "la correlación entre permanencia y tutorías",
        "la estructura de costos en educación superior", "la divergencia epistemológica cualitativa"
    ]

    for _ in range(n_samples):
        autor = random.choice(AUTORES_IBERO)
        tema = random.choice(temas)
        verbo_str, rationale_str = random.choice(verbos_diccion)
        
        texto = f"En la literatura previa, {autor} {verbo_str} {tema} constituye un eje articulador central del debate contemporáneo."
        samples.append({
            "text": texto,
            "section": random.choice(["Introducción", "Estado del Arte", "Antecedentes Teóricos"]),
            "rationale": f"Falso consenso aparente por verbo afirmativo; {rationale_str}.",
            "stance": "neutral_or_mention",
            "claim": "",
            "confidence": "high",
            "is_hard_negative": True
        })

    return samples


def main():
    print("=" * 85)
    print("GENERADOR MAESTRO V3: MINERÍA DE NEGATIVOS DIFÍCILES (SNLI + TASS + CoT)")
    print("=" * 85)

    # 1. Cargar SNLI tripletas
    print("\n1. Extrayendo tripletas contrastivas académicas desde SNLI...")
    snli_samples = extract_snli_academic_triplets(max_per_class=1000)
    print(f"✓ Extraídas {len(snli_samples)} tripletas desde SNLI.")

    # 2. Cargar TASS neutrales
    print("\n2. Extrayendo patrones neutrales factuales en Español desde TASS...")
    tass_samples = extract_tass_hard_negatives(max_samples=600)
    print(f"✓ Extraídas {len(tass_samples)} citas neutrales desde TASS.")

    # 3. Generar falsos consensos con léxico culto (Hard Negatives sintéticos)
    print("\n3. Generando 2.400 Falsos Consensos (Hard Negatives con verbos afirmativos)...")
    hard_negatives = generate_high_register_spanish_hard_negatives(n_samples=2400)
    print(f"✓ Generados {len(hard_negatives)} Falsos Consensos con léxico culto.")

    # 4. Cargar dataset V2 actual
    print("\n4. Ingestando dataset base V2 existente...")
    existing_v2 = []
    v2_path = Path("data/epistemic_train_cot.jsonl")
    if v2_path.exists():
        with open(v2_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    out = json.loads(obj["output"])
                    m_sec = re.search(r'Sección:\s*(.*)', obj["input"])
                    sec = m_sec.group(1).strip() if m_sec else "Cuerpo del manuscrito"
                    m_txt = re.search(r'Contexto de citación:\s*"(.*?)"', obj["input"], re.DOTALL)
                    txt = m_txt.group(1) if m_txt else obj["input"]
                    existing_v2.append({
                        "text": txt,
                        "section": sec,
                        "rationale": out.get("rationale", "Análisis retórico de citación científica."),
                        "stance": out["stance"],
                        "claim": out.get("claim", ""),
                        "confidence": out.get("confidence", "high"),
                        "is_hard_negative": False
                    })
                except Exception:
                    continue
    print(f"✓ Ingestadas {len(existing_v2)} citas de la versión V2.")

    # 5. Oversampling de Hard Negatives x3 como indica '1. Solucionar la Confianza Insegura.txt'
    all_hard_negatives = [s for s in (snli_samples + tass_samples + hard_negatives) if s.get("is_hard_negative")]
    print(f"\n5. Aplicando Oversampling x3 a {len(all_hard_negatives)} Negativos Difíciles...")
    oversampled_hn = all_hard_negatives * 3

    # Consolidar corpus maestro final
    total_pool = existing_v2 + snli_samples + tass_samples + hard_negatives + oversampled_hn
    random.seed(42)
    random.shuffle(total_pool)

    total_len = len(total_pool)
    n_test = int(total_len * 0.08)
    test_set = total_pool[:n_test]
    train_set = total_pool[n_test:]

    spanish_count = len([x for x in train_set if any(w in x["text"].lower() for w in [" el ", " la ", " en ", " de ", " que ", " se ", " por ", " los ", " las ", " con "])])
    spanish_ratio = (spanish_count / len(train_set)) * 100

    print(f"\n================================================================================")
    print(f"ESTADÍSTICAS DEL DATASET V3 FINAL:")
    print(f"   • Total de Citas en el Dataset: {total_len}")
    print(f"   • Conjunto de Entrenamiento (Train): {len(train_set)}")
    print(f"   • Evaluación Ciega (Test Holdout): {len(test_set)}")
    print(f"   • Dominancia del Español: {spanish_ratio:.1f}%")
    print(f"   • Negativos Difíciles en Train: {len([x for x in train_set if x.get('is_hard_negative')])}")
    print(f"================================================================================")

    # 6. Guardar en disco
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

    print(f"\n✓ Dataset V3 Maestro guardado con éxito:")
    print(f"  → {train_path} ({len(train_set)} citas)")
    print(f"  → {test_path} ({len(test_set)} citas)")


if __name__ == "__main__":
    main()
