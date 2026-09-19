import pandas as pd
import re

df = pd.read_csv('data/auditorias_y_benchmarks/resultados_thinkuy_v2_inferencia.csv', encoding='utf-8-sig')

valid_hits = 0
valid_total = 0

for idx, r in df.iterrows():
    raw = str(r.get('thinkuy_v2_raw', ''))
    m = re.search(r'["\']perspectiva["\']\s*:\s*["\'](.*?)["\']', raw)
    if m:
        val = m.group(1).strip()
        gold = r['referencia_canonica_perspectiva']
        if 'P1' in val:
            valid_total += 1
            if gold == 'P1_MEDICION_ESCALAS': valid_hits += 1
        elif 'P2' in val:
            valid_total += 1
            if gold == 'P2_ESTRATEGICO_STAKEHOLDERS': valid_hits += 1
        elif 'P3' in val:
            valid_total += 1
            if gold == 'P3_CONEXION_SOCIAL_EXTENSION': valid_hits += 1

print(f"Total de respuestas con etiqueta formal P1/P2/P3: {valid_total}/333 ({valid_total/333*100:.1f}%)")
print(f"Aciertos reales en esas respuestas válidas: {valid_hits}/{valid_total} ({valid_hits/valid_total*100:.1f}%)")
print(f"Exactitud real estricta sobre todo el corpus (sin fallback): {valid_hits}/333 ({valid_hits/333*100:.1f}%)")
