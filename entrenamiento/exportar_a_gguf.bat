@echo off
chcp 65001 > nul
cd /d "%~dp0.."
title Exportar Modelo a GGUF (LM Studio / Thinkuy)
echo ===============================================================================
echo   EXPORTACION DEL MODELO EPISTEMICO A GGUF (Q4_K_M)
echo ===============================================================================
echo.
echo Este proceso fusionara los adaptadores LoRA del paso 190 y creara el archivo
echo .gguf optimizado en: exports\thinkuy_qwen25_1_5b_gguf\
echo.
echo Presiona cualquier tecla para comenzar la exportacion...
pause > nul

"C:\Users\gipsy\.unsloth\studio\unsloth_studio\Scripts\python.exe" tools\export_to_gguf.py

echo.
echo ===============================================================================
echo Proceso finalizado. El archivo .gguf ya esta listo para usar en LM Studio.
echo ===============================================================================
pause
