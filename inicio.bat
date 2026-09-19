@echo off
chcp 65001 >nul
title Thinkuy - Radar de Comunicacion Cientifica
cd /d "%~dp0backend"

echo ============================================================
echo   THINKUY - Radar de Comunicacion Cientifica
echo   PWA:    http://localhost:8000/app/
echo   Widget: http://localhost:8000/widget
echo ============================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Entorno virtual no encontrado en backend\.venv.
    echo Instala las dependencias necesarias antes de continuar:
    echo   cd backend
    echo   uv venv .venv
    echo   uv pip install --python .venv fastapi "uvicorn[standard]" apscheduler httpx
    pause
    exit /b 1
)

echo  [1] Arrancar servidor (Modo en vivo OpenAlex / Dialnet / OpenAIRE)
echo  [2] Cosechar ultimos 30 dias e iniciar
echo  [3] Cosecha completa 1 ano e iniciar
echo.
set OPCION=1
set /p OPCION="Elige una opcion (1/2/3) [Enter = 1]: "

if "%OPCION%"=="2" .venv\Scripts\python.exe -m radar.harvester.cli --days 30 --max-articles 800
if "%OPCION%"=="3" .venv\Scripts\python.exe -m radar.harvester.cli --days 365 --max-articles 2500

echo.
echo Arrancando servidor Thinkuy...
.venv\Scripts\python.exe run_server.py
pause
