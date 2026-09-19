# Thinkuy en un contenedor: la base de datos NO vive en la máquina de nadie.
#
#   docker compose up --build
#   -> http://localhost:8000/app/
#
# El dato persistente vive en el volumen `/data` (ver docker-compose.yml), no en la imagen.
# Así el código se puede actualizar sin perder nada, y la base es del servidor, no del operador.
FROM python:3.13-slim

# Dependencias del sistema que necesitan PyMuPDF y Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) Dependencias de Python (capa cacheable)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 2) Navegador sin cabeza (escalón 5 de la ingesta). Opcional pero declarado:
#    sin él, `render_js` degrada avisando en lugar de fallar.
RUN playwright install --with-deps chromium

# 3) Código: backend, perfiles y PWA
COPY backend/ /app/backend/
COPY profiles/ /app/profiles/
COPY pwa/ /app/pwa/

# El dato va FUERA del código (volumen). Sin esto, cada actualización borraría la base.
ENV THINKUY_DATA_DIR=/data \
    THINKUY_HOST=0.0.0.0 \
    THINKUY_PORT=8000 \
    THINKUY_INDEX_LIVE_RESULTS=0 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data

EXPOSE 8000

WORKDIR /app/backend

# Un solo proceso escritor: SQLite serializa las escrituras y `--reload` es de desarrollo.
CMD ["python", "-m", "uvicorn", "radar.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
