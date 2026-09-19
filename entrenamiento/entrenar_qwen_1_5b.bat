@echo off
chcp 65001 > nul
cd /d "%~dp0.."
title Entrenar Qwen 2.5 1.5B Epistémico (Thinkuy - Unsloth)
echo ===============================================================================
echo   THINKUY - ENTRENAMIENTO QWEN 2.5 1.5B (QLoRA 4-bit / RTX 5060)
echo ===============================================================================
echo.
echo Dataset: data\epistemic_train.jsonl (6,032 citas balanceadas bilingües)
echo Modelo:  unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit
echo Salida:  outputs\thinkuy_qwen25_1_5b_epistemic y exports\thinkuy_qwen25_1_5b_gguf
echo.
echo Presiona cualquier tecla para comenzar el entrenamiento...
pause > nul

"C:\Users\gipsy\.unsloth\studio\unsloth_studio\Scripts\python.exe" tools\train_epistemic_unsloth.py

echo.
echo ===============================================================================
echo Proceso finalizado. Revisa la salida y los logs en entrenamiento\bitacora.txt
echo ===============================================================================
pause
