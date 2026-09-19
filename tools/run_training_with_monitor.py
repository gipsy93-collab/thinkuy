"""Lanzador Orquestador: Inicia el Dashboard de Telemetría + Entrenamiento Qwen V2 en GPU.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PYTHON_EXEC = r"C:\Users\gipsy\.unsloth\studio\unsloth_studio\Scripts\python.exe"
if not Path(PYTHON_EXEC).exists():
    PYTHON_EXEC = sys.executable


def main():
    print("=" * 80)
    print("THINKUY LAB: INICIANDO SISTEMA INTEGRADO DE ENTRENAMIENTO Y MONITOREO")
    print("=" * 80)

    # 1. Iniciar el Dashboard en un proceso separado
    print("\n[1/2] Levantando servidor de telemetría y desplegando ventana de monitoreo...")
    dash_proc = subprocess.Popen(
        [PYTHON_EXEC, "tools/train_monitor_dashboard.py"],
        creationflags=0x08000000 if sys.platform == "win32" else 0
    )
    time.sleep(2.0)
    print("✓ Dashboard activo en http://localhost:7860 (ventana abierta en escritorio).")

    # 2. Iniciar el entrenamiento en GPU
    print("\n[2/2] Iniciando entrenamiento QLoRA V2 en GPU GeForce RTX 5060...")
    try:
        train_proc = subprocess.run(
            [PYTHON_EXEC, "tools/train_qwen_cot_v2.py"],
            check=True
        )
        print("\n✓ Proceso de entrenamiento finalizado exitosamente.")
    except KeyboardInterrupt:
        print("\n[!] Entrenamiento detenido por el usuario.")
    except Exception as e:
        print(f"\n[ERROR] El entrenamiento falló: {e}")
    finally:
        print("\nEl monitor permanece disponible para consulta de métricas.")


if __name__ == "__main__":
    main()
