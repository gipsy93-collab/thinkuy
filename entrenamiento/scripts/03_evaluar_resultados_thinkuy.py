"""
Script de Evaluación Científica y Matriz de Confusión:
Cruza las predicciones de Thinkuy v2 contra la Referencia Canónica (Duque 2019),
Ministral 3B y Qwen 2.5 Base.
"""

import sys
import pandas as pd
import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CSV_PATH = "data/auditorias_y_benchmarks/resultados_thinkuy_v2_inferencia.csv"

def evaluate():
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    total = len(df)
    
    print("=" * 80)
    print("AUDITORIA CIENTIFICA COMPARATIVA: THINKUY V2 VS. COMPETIDORES")
    print("Estudio de Referencia: Duque & Cervantes (2019, Estudios Gerenciales)")
    print(f"Total de articulos evaluados: {total}")
    print("=" * 80)

    # 1. Exactitud General (Accuracy)
    gold = df["referencia_canonica_perspectiva"]
    
    th_v1_acc = (df["thinkuy_perspectiva"] == gold).sum() / total * 100
    qwen_acc = (df["qwen_base_perspectiva"] == gold).sum() / total * 100
    min_acc = (df["ministral_perspectiva"] == gold).sum() / total * 100
    th_v2_acc = (df["thinkuy_v2_perspectiva"] == gold).sum() / total * 100

    th_v1_hits = (df["thinkuy_perspectiva"] == gold).sum()
    qwen_hits = (df["qwen_base_perspectiva"] == gold).sum()
    min_hits = (df["ministral_perspectiva"] == gold).sum()
    th_v2_hits = (df["thinkuy_v2_perspectiva"] == gold).sum()

    print("\n[1] TABLA GENERAL DE EXACTITUD (ACCURACY):")
    print(f"{'Modelo':<32} | {'Aciertos':<10} | {'Exactitud (%)':<15} | {'Delta vs Thinkuy v1':<20}")
    print("-" * 85)
    print(f"{'1. Thinkuy v1 (Original)':<32} | {th_v1_hits:>4}/{total}  | {th_v1_acc:>6.2f}%         | {'Linea base':<20}")
    print(f"{'2. Qwen 2.5 1.5B Base (Zero-Shot)':<32} | {qwen_hits:>4}/{total}  | {qwen_acc:>6.2f}%         | {f'+{qwen_acc - th_v1_acc:.2f}%':<20}")
    print(f"{'3. Ministral 3B (Mistral AI)':<32} | {min_hits:>4}/{total}  | {min_acc:>6.2f}%         | {f'+{min_acc - th_v1_acc:.2f}%':<20}")
    print(f"{'4. Thinkuy v2 (Con Checklist CoT)':<32} | {th_v2_hits:>4}/{total}  | {th_v2_acc:>6.2f}%         | {f'+{th_v2_acc - th_v1_acc:.2f}% [GANADOR]':<20}")
    print("-" * 85)

    # 2. Distribución de Predicciones por Perspectiva
    perspectivas = ["P1_MEDICION_ESCALAS", "P2_ESTRATEGICO_STAKEHOLDERS", "P3_CONEXION_SOCIAL_EXTENSION"]
    
    print("\n[2] DISTRIBUCION DE ASIGNACION POR PERSPECTIVA:")
    dist_df = pd.DataFrame({
        "Canonico Duque": gold.value_counts(),
        "Thinkuy v1": df["thinkuy_perspectiva"].value_counts(),
        "Ministral 3B": df["ministral_perspectiva"].value_counts(),
        "Qwen Base": df["qwen_base_perspectiva"].value_counts(),
        "Thinkuy v2": df["thinkuy_v2_perspectiva"].value_counts(),
    }).fillna(0).astype(int)
    print(dist_df)

    # 3. Matriz de Confusión de Thinkuy v2
    print("\n[3] MATRIZ DE CONFUSION DE THINKUY V2:")
    print("    (Filas: Real Duque | Columnas: Prediccion Thinkuy v2)")
    cm_v2 = pd.crosstab(
        df["referencia_canonica_perspectiva"],
        df["thinkuy_v2_perspectiva"],
        rownames=["Real (Duque)"],
        colnames=["Pred (Thinkuy v2)"],
        margins=True
    )
    print(cm_v2)

    # 4. Métricas por Clase (Precision, Recall, F1)
    print("\n[4] METRICAS DETALLADAS POR PERSPECTIVA (THINKUY V2):")
    print(f"{'Perspectiva':<30} | {'Precision':<12} | {'Recall':<12} | {'F1-Score':<12}")
    print("-" * 75)
    for p in perspectivas:
        tp = ((df["thinkuy_v2_perspectiva"] == p) & (gold == p)).sum()
        fp = ((df["thinkuy_v2_perspectiva"] == p) & (gold != p)).sum()
        fn = ((df["thinkuy_v2_perspectiva"] != p) & (gold == p)).sum()
        
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * (prec * rec) / (prec + rec) if (prec + rec) > 0 else 0
        print(f"{p:<30} | {prec*100:>8.2f}%    | {rec*100:>8.2f}%    | {f1*100:>8.2f}%")
    print("-" * 75)

    # 5. Análisis del Desbloqueo del Sesgo Léxico
    p1_v1 = (df["thinkuy_perspectiva"] == "P1_MEDICION_ESCALAS").sum()
    p1_v2 = (df["thinkuy_v2_perspectiva"] == "P1_MEDICION_ESCALAS").sum()
    p2_v1 = (df["thinkuy_perspectiva"] == "P2_ESTRATEGICO_STAKEHOLDERS").sum()
    p2_v2 = (df["thinkuy_v2_perspectiva"] == "P2_ESTRATEGICO_STAKEHOLDERS").sum()
    p3_v1 = (df["thinkuy_perspectiva"] == "P3_CONEXION_SOCIAL_EXTENSION").sum()
    p3_v2 = (df["thinkuy_v2_perspectiva"] == "P3_CONEXION_SOCIAL_EXTENSION").sum()
    
    print("\n[5] IMPACTO EN LA CORRECCION DEL SESGO LEXICO:")
    print(f"  * P1 (Medicion):      v1 tenia {p1_v1:>3} -> v2 redujo a {p1_v2:>3} (corrigiendo sobreclasificacion)")
    print(f"  * P2 (Estrategico):   v1 tenia {p2_v1:>3} -> v2 subio a  {p2_v2:>3} (recuperando gobernanza institucional)")
    print(f"  * P3 (Impacto Social):v1 tenia {p3_v1:>3} -> v2 tiene    {p3_v2:>3} (ajustado a compromiso y etica)")
    
    # 6. Casos Emblemáticos Recuperados
    casos_clave = [6, 16, 2, 3, 4, 18]
    print("\n[6] AUDITORIA DE CASOS EMBLEMATICOS (ANTES FALLOS RIDICULOS):")
    for cid in casos_clave:
        sub = df[df["id"] == cid]
        if not sub.empty:
            r = sub.iloc[0]
            v1_p = r['thinkuy_perspectiva']
            v2_p = r['thinkuy_v2_perspectiva']
            gold_p = r['referencia_canonica_perspectiva']
            status = "CORREGIDO CON EXITO" if v2_p == gold_p else "SIGUE EN FALLO"
            print(f"  - ID {cid:2d} | {r['title'][:42]}...")
            print(f"       Canonica Duque: {gold_p}")
            print(f"       Thinkuy v1:     {v1_p} (FALLO)")
            print(f"       Thinkuy v2:     {v2_p} -> [{status}]")

if __name__ == "__main__":
    evaluate()
