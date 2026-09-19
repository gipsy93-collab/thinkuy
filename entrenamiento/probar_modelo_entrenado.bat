@echo off
chcp 65001 > nul
cd /d "%~dp0.."
title Probar Modelo Epistémico Qwen 2.5 1.5B Afinado
echo ===============================================================================
echo   EVALUACION EN VIVO — QWEN 2.5 1.5B (PASO 190 / 2 EPOCAS)
echo ===============================================================================
echo.
echo Ejecutando 5 casos de prueba contra los adaptadores LoRA entrenados...
echo.
"C:\Users\gipsy\.unsloth\studio\unsloth_studio\Scripts\python.exe" tools\eval_trained_qwen.py
echo.
pause
