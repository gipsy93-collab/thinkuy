# Entrenamiento — pipeline de dataset y modelos

Aquí vive todo lo que **no forma parte del servicio** (el backend FastAPI y la PWA): la
construcción del dataset epistémico, el entrenamiento QLoRA y su evaluación. Requiere el
entorno de Unsloth (no el `.venv` del servidor).

> Los scripts de **desarrollo/operación** del proyecto (lint, pruebas, versión) NO están aquí:
> `scripts/dev_check.ps1` sigue en la raíz del proyecto.

## Contenido

| Ruta | Qué es |
| :--- | :--- |
| `entrenar_qwen_v2_cot.bat` | Pipeline vigente: genera el dataset V3 (hard negatives), levanta el monitor y entrena. |
| `entrenar_qwen_1_5b.bat` | Entrenamiento V1 (histórico, sigue operativo). |
| `probar_modelo_entrenado.bat` | Evaluación en vivo del LoRA entrenado. |
| `exportar_a_gguf.bat` | Fusiona adaptadores y exporta a `.gguf` para LM Studio. |
| `iniciar_unsloth_studio.bat` | Abre la GUI de Unsloth Studio. |
| `scripts/` | Pipeline numerado (`02_`…`10_`) + utilidades de dataset, cosecha y evaluación. |
| `scripts/_LEGACY/` | Cuarentena declarada (no usar). |
| `bitacora.txt` | Log de entrenamiento. |

Los `.bat` hacen `cd /d "%~dp0.."`, así que pueden ejecutarse haciendo doble clic desde aquí:
las rutas relativas (`tools\…`, `data\…`, `models\…`) resuelven desde la raíz del proyecto.
