"""Configuración de Thinkuy (variables de entorno con valores por defecto).

Todo lo específico de una disciplina vive en el perfil de campo
(`profiles/<campo>.json`), no aquí. El perfil activo se elige con THINKUY_FIELD.
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

DATA_DIR = Path(os.environ.get("THINKUY_DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = Path(os.environ.get("THINKUY_DB_PATH", DATA_DIR / "radar.db"))
PWA_DIR = Path(os.environ.get("THINKUY_PWA_DIR", PROJECT_ROOT / "pwa"))
PROFILES_DIR = Path(os.environ.get("THINKUY_PROFILES_DIR", PROJECT_ROOT / "profiles"))

THINKUY_FIELD = os.environ.get("THINKUY_FIELD", "general")

MAILTO = os.environ.get("THINKUY_MAILTO", "contacto@thinkuy.dev")
USER_AGENT = os.environ.get(
    "THINKUY_USER_AGENT",
    f"Thinkuy/0.3 (radar de comunicacion cientifica abierta; contacto: {MAILTO})",
)

# OpenAlex (feb-2026): el polite pool por mailto fue reemplazado por API key con
# creditos. Sin key quedan 100 creditos/dia (luego HTTP 409). Define
# THINKUY_OPENALEX_API_KEY para autenticar todas las llamadas.
OPENALEX_API_KEY = os.environ.get("THINKUY_OPENALEX_API_KEY", "")


def openalex_headers(user_agent: str | None = None) -> dict:
    """Headers para api.openalex.org: UA de cortesía + Bearer si hay key."""
    h = {"User-Agent": user_agent or USER_AGENT}
    if OPENALEX_API_KEY:
        h["Authorization"] = f"Bearer {OPENALEX_API_KEY}"
    return h

HARVEST_INTERVAL_HOURS = int(os.environ.get("THINKUY_HARVEST_INTERVAL_HOURS", "6"))
AUTO_HARVEST = os.environ.get("THINKUY_AUTO_HARVEST", "0") == "1"
DEFAULT_DAYS = int(os.environ.get("THINKUY_DEFAULT_DAYS", "365"))
MAX_ARTICLES_PER_RUN = int(os.environ.get("THINKUY_MAX_ARTICLES", "1500"))
REQUEST_DELAY = float(os.environ.get("THINKUY_REQUEST_DELAY", "0.15"))

# Orígenes permitidos por CORS. `*` sirve en local (la PWA se sirve del mismo origen y no
# necesita CORS), pero **un despliegue público DEBE fijarlo** a su dominio, o cualquier sitio
# podrá llamar a la API desde el navegador de un tercero. Lista separada por comas.
# Ver `docs/DESPLIEGUE_MULTIUSUARIO.md`.
CORS_ORIGINS = [o.strip() for o in os.environ.get("THINKUY_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if o.strip()]

# ¿La búsqueda en vivo indexa sus resultados en el catálogo local?
# **Por defecto NO** (comportamiento de servidor): buscar es una operación de LECTURA y no debe
# ensanchar un estado compartido. Medido el 18-09-2026: una sola búsqueda clínica metió 95
# artículos de oncología en el catálogo de comunicación del investigador.
# Lo que sí persiste es **transferir resultados a una revisión** (acción explícita).
# Poner `THINKUY_INDEX_LIVE_RESULTS=1` restaura el comportamiento antiguo (y hace crecer la base
# con cada búsqueda: no usar en un despliegue abierto).
INDEX_LIVE_RESULTS = os.environ.get("THINKUY_INDEX_LIVE_RESULTS", "0") == "1"

# Interfaz de escucha. `127.0.0.1` = solo esta máquina (uso local). `0.0.0.0` = accesible desde
# la red — es el primer paso para emular un servidor o probar el acceso desde otro dispositivo.
HOST = os.environ.get("THINKUY_HOST", "127.0.0.1")

REDALYC_TOKEN = os.environ.get("REDALYC_TOKEN", "")

# Clave secreta para firmas criptográficas de tokens de autenticación de usuario (JWT HS256)
SECRET_KEY = os.environ.get("THINKUY_SECRET_KEY", "thinkuy-default-secret-key-change-in-production-2026")


# ---------------------------------------------------------------- Common Crawl (SCIVIS)
# Rutas y release del dataset oficial de WebGraph de Common Crawl. En el entorno de
# desarrollo local viven en D:\ ; en despliegue se sobrescriben con variables de entorno.
def _env_path(name: str, default) -> Path:
    v = os.environ.get(name)
    return Path(v) if v else Path(default)


CC_RANKS_DB = _env_path("THINKUY_CC_RANKS_DB", DATA_DIR / "commoncrawl" / "cc_domain_ranks.db")
CC_RANKS_GZ = _env_path("THINKUY_CC_RANKS_GZ", DATA_DIR / "commoncrawl" / "cc_domain_ranks.txt.gz")
CC_EDGES_GZ = _env_path("THINKUY_CC_EDGES_GZ", DATA_DIR / "commoncrawl" / "cc_edges.txt.gz")
CC_VERTICES_GZ = _env_path("THINKUY_CC_VERTICES_GZ", DATA_DIR / "commoncrawl" / "cc_vertices.txt.gz")
CC_HISTORY_DIR = _env_path("THINKUY_CC_HISTORY_DIR", DATA_DIR / "commoncrawl" / "cc_ranks_history")
CC_INLINKS_DB = _env_path("THINKUY_CC_INLINKS_DB", DATA_DIR / "commoncrawl" / "cc_inlinks.db")

# Identificador del release activo (el que alimenta CC_RANKS_DB).
CC_RELEASE_ID = os.environ.get("THINKUY_CC_RELEASE", "cc-main-2026-jun-jul-aug")

# TTL (horas) de la caché de auditorías SCIVIS.
CC_AUDIT_TTL_HOURS = int(os.environ.get("THINKUY_CC_AUDIT_TTL_HOURS", "24"))

VERSION = "0.3.1"