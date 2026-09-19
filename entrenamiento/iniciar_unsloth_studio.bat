@echo off
chcp 65001 > nul
cd /d "%~dp0.."
title Iniciar Unsloth Studio
echo ===============================================================================
echo   INICIANDO UNSLOTH STUDIO (GUI)
echo ===============================================================================
echo.
echo Recuerda en la interfaz:
echo 1. Modelo: unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit
echo 2. Dataset: Carga data\epistemic_train.jsonl (6,032 registros)
echo    [NO selecciones epistemic_test.jsonl que solo tiene 671]
echo 3. Formato: Alpaca (instruction, input, output) o ChatML (epistemic_train_chatml.jsonl)
echo 4. Epocas: 1.0 a 2.0 (o aprox 377 a 750 pasos) para no subentrenar
echo.
call "C:\Users\gipsy\.unsloth\studio\bin\unsloth.cmd" studio
pause
