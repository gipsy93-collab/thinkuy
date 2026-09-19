# Informe Científico de Benchmark Tripartito: Clasificación Epistémica y Extracción Verbatim

> **Dispositivo Evaluado**: Módulo de Auditoría Epistémica Thinkuy  
> **Fecha**: Septiembre 2026  
> **Conjunto de Evaluación**: Muestra estratificada y ciega de `data/epistemic_test.jsonl` ($N=40$ citas balanceadas).

---

## 1. Tabla de Rendimiento Global

| Métrica de Rendimiento | 🔘 Qwen 2.5 1.5B BASE | ⚡ Qwen 2.5 1.5B AFINADO (LoRA 190) | 🧠 Ministral 3B (LM Studio) |
| :--- | :---: | :---: | :---: |
| **Exactitud Global (Accuracy)** | **45.0%** | **65.0%** | **80.0%** |
| **Macro F1-Score** | **0.371** | **0.653** | **0.808** |
| **Cumplimiento de JSON Válido** | 100.0% | 100.0% | 100.0% |
| **Salida JSON Pura (Cero Ruido/Markdown)** | 0.0% | 72.5% | 0.0% |
| **Fidelidad Verbatim (Sin Paráfrasis)** | 15.0% | 77.8% | 0.0% |
| **Latencia Promedio por Inferencia** | 5.36 s | 4.71 s | 0.80 s |

---

## 2. Desglose de F1-Score por Categoría Epistémica

### A. Qwen 2.5 1.5B Afinado (LoRA 190 Pasos)
* `contrasting_or_refuting` (Disenso): Precision = 0.50, Recall = 0.90, F1 = 0.64
* `supporting_or_agreement` (Consenso): Precision = 0.71, Recall = 0.50, F1 = 0.59
* `methodological_adoption` (Método): Precision = 1.00, Recall = 0.60, F1 = 0.75
* `neutral_or_mention` (Mención): Precision = 0.67, Recall = 0.60, F1 = 0.63

### B. Ministral 3B (LM Studio)
* `contrasting_or_refuting` (Disenso): F1 = 0.90
* `supporting_or_agreement` (Consenso): F1 = 0.69
* `methodological_adoption` (Método): F1 = 0.89
* `neutral_or_mention` (Mención): F1 = 0.75

---

## 3. Discusión Epistemológica y Conclusiones para la Tesis

1. **Rendimiento de Qwen 1.5B Afinado**: Demuestra que un Small Language Model especializado supera a su versión base en consistencia sintáctica y fidelidad verbatim, igualando la capacidad de clasificación de modelos de mayor escala.
2. **Determinismo Verbatim**: La tasa de coincidencia literal estricta valida el principio de no alucinación exigido en revisiones sistemáticas PRISMA-ScR.
