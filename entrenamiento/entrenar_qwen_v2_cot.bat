@echo off
chcp 65001 > nul
cd /d "%~dp0.."
title Thinkuy — Entrenamiento Qwen 2.5 1.5B V2 con Telemetria en Vivo

echo ===============================================================================
echo   THINKUY LAB - ENTRENAMIENTO QLORA V2 CON VENTANA DE MONITOREO EN VIVO
echo   Hardware: NVIDIA GeForce RTX 5060 Laptop GPU
echo   Modelo: Qwen 2.5 1.5B Instruct (r=32, alpha=64, CoT Rationale)
echo ===============================================================================
echo.

set PYTHON_EXEC=C:\Users\gipsy\.unsloth\studio\unsloth_studio\Scripts\python.exe

if not exist "%PYTHON_EXEC%" (
    echo [ERROR] No se encontro el entorno Unsloth en: %PYTHON_EXEC%
    pause
    exit /b 1
)

echo [1/3] Verificando dataset de entrenamiento V3 (28k citas con Hard Negatives)...
if not exist "data\epistemic_train_cot.jsonl" (
    echo Generando dataset V3 con negativos dificiles...
    "%PYTHON_EXEC%" tools\build_epistemic_dataset_v3_hard_negatives.py
)

echo.
echo [2/3] Levantando ventana de monitoreo visual en http://localhost:7860...
start "" "%PYTHON_EXEC%" tools\train_monitor_dashboard.py
timeout /t 2 /nobreak > nul

echo.
echo [3/3] Iniciando entrenamiento en GPU NVIDIA GeForce RTX 5060...
echo.

"%PYTHON_EXEC%" tools\train_qwen_cot_v2.py

echo.
echo ===============================================================================
echo   Proceso finalizado. Adaptadores guardados en models\qwen_epistemic_v2_cot
echo   El monitor sigue disponible en su navegador.
echo ===============================================================================
pause
