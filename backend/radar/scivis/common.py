# -*- coding: utf-8 -*-
"""Constantes, caches y funciones auxiliares compartidas para el módulo SCIVIS."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from .. import config
from ..normalize import norm

log = logging.getLogger("radar.scivis")

# Cache de la colección activa de Common Crawl
_CC_COLLECTION_CACHE: Dict[str, Any] = {}
_CC_COLLECTION_LOCK = threading.Lock()

# Dataset local indexado (release activo) y rutas derivadas de configuración
CC_DOMAIN_RANKS_DB = str(config.CC_RANKS_DB)
CC_RANKS_GZ = str(config.CC_RANKS_GZ)
CC_HISTORY_DIR = str(config.CC_HISTORY_DIR)
CC_INLINKS_DB = str(config.CC_INLINKS_DB)
CC_RELEASE_ID = config.CC_RELEASE_ID
CC_AUDIT_TTL_HOURS = config.CC_AUDIT_TTL_HOURS

# Mapeo de dominios de revistas de referencia en Iberoamérica
KNOWN_JOURNAL_DOMAINS: Dict[str, str] = {
    "revista panamericana de comunicacion": "revistapanamericanadecomunicacion.up.edu.mx",
    "revista panamericana de pedagogia": "revistas.up.edu.mx",
    "comunicar": "revistacomunicar.com",
    "el profesional de la informacion": "profesionaldelainformacion.com",
    "estudios sobre el mensaje periodistico": "revistas.ucm.es",
    "revista latina de comunicacion social": "nuevaepoca.revistalatinacs.org",
    "cuadernos.info": "cuadernos.info",
    "comunicacion y sociedad": "comunicacionysociedad.cucsh.udg.mx",
    "chasqui": "revistachasqui.org",
    "palabra clave": "palabraclave.unisabana.edu.co",
    "alteridad": "alteridad.ups.edu.ec",
    "revista de ciencias sociales": "produccioncientificaluz.org",
    "historia y comunicacion social": "revistas.ucm.es",
    "zer": "ehu.eus",
    "razon y palabra": "revistarazonypalabra.org",
    "adcomunica": "adcomunicarevista.com",
}


def _get_db_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Abre conexión SQLite registrando la función personalizada de normalización.

    `config.DB_PATH` se resuelve en la llamada, no al importar: si se fija por defecto
    en la firma, un cambio de configuración (o una prueba) seguiría abriendo la base vieja.
    """
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("norm", 1, norm)
    return conn




# Sufijos públicos multi-nivel (subset operativo del PSL de publicsuffix.org) que jamás
# deben reportarse como dominio de una revista: la escalada de candidatos se detiene en ellos.
CC_PUBLIC_SUFFIXES = {
    "com.br", "com.mx", "com.ar", "com.co", "com.ec", "com.pe", "com.ve", "com.bo",
    "com.uy", "com.py", "com.cl", "com.do", "com.gt", "com.hn", "com.sv", "com.ni",
    "com.cr", "com.pa", "org.br", "org.mx", "org.ar", "org.co", "org.ec", "org.pe",
    "org.ve", "org.uy", "org.py", "org.cl", "edu.br", "edu.mx", "edu.co", "edu.ec",
    "edu.ar", "edu.pe", "edu.ve", "edu.bo", "edu.uy", "edu.py", "edu.cl",
    "gob.mx", "gov.br", "gov.co", "gov.mx", "gob.ar", "gob.ec", "gob.pe",
    "ac.uk", "co.uk", "org.uk", "gov.uk", "edu.au", "com.au", "net.au", "org.au",
    "ac.nz", "co.nz", "org.nz", "edu.cn", "com.cn", "net.cn", "org.cn", "gov.cn",
    "ac.jp", "co.jp", "or.jp", "ne.jp", "ac.in", "co.in", "net.in", "org.in", "gov.in",
    "com.sg", "com.my", "com.tw", "co.kr", "or.kr", "ac.kr", "com.pt", "edu.pt",
    "com.es", "edu.es", "gob.es", "org.es", "com.it", "edu.it", "gov.it",
    "com.fr", "gouv.fr", "edu.fr", "com.de", "edu.de", "com.be", "ac.be", "edu.gr",
    "ac.il", "co.il", "org.il", "co.za", "org.za", "net.za", "gov.za", "ac.za",
    "com.tr", "edu.tr", "gov.tr", "org.tr", "com.eg", "edu.eg", "com.ma", "org.ma",
    "com.pl", "edu.pl", "gov.pl", "com.ru", "net.ru", "org.ru", "edu.ru",
}


def _clean_domain(domain: str) -> str:
    """Depura una URL o dominio pegado por el usuario hasta su HOST completo.

    Elimina esquema (https://, ftp://, //), ruta, query, fragmento, puerto, subdominios
    www/wwwN, punto final FQDN y normaliza IDN a punycode. NO reduce a la raíz a la fuerza:
    conserva el host completo; la escalada al dominio registrable la hace _domain_candidates
    con el guard de sufijos públicos (lo correcto para OJS en subdominios universitarios).
    """
    d = (domain or "").strip().lower()
    if not d:
        return ""
    if d.startswith("//"):
        d = d[2:]
    else:
        d = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = re.sub(r":\d+$", "", d)   # puerto
    d = d.rstrip(".")             # punto final FQDN
    while re.match(r"^www\d?\.", d):
        d = re.sub(r"^www\d?\.", "", d)
    try:
        if any(ord(c) > 127 for c in d):
            d = d.encode("idna").decode("ascii")
    except Exception:
        pass
    return d.strip()


_OJS_GENERIC = {
    "index.php", "ojs", "public", "issue", "article", "view", "about", "login",
    "register", "search", "gateway", "files", "plugins", "library", "help",
    "user", "index", "indexation", "announcement",
}



def _split_url_scope(raw: str) -> Tuple[str, Optional[str], Optional[str]]:
    """De una URL pegada por el usuario devuelve (host_limpio, journal_segment, path_prefix).

    - journal_segment: identificador de la revista DENTRO de un portal compartido (p. ej.
      'sophia' en revistas.ugca.edu.co/index.php/sophia/...). None si no hay ruta con
      identidad de revista.
    - path_prefix: prefijo de ruta hasta ese segmento (p. ej. 'index.php/sophia'),
      útil para consultas CDX específicas de la revista.

    Así se evita atribuir a 'Revista Sophia' las citas/enlaces de 'Inciso' u otras revistas
    que comparten el mismo host OJS."""
    d = (raw or "").strip().lower()
    if d.startswith("//"):
        d = d[2:]
    else:
        d = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", d)
    path = ""
    if "/" in d:
        d, path = d.split("/", 1)
    host = _clean_domain(d)
    path = path.split("?")[0].split("#")[0].strip("/")
    if not path:
        return host, None, None
    segments = [s for s in path.split("/") if s]
    journal_seg = next((s for s in segments if s not in _OJS_GENERIC and not s.isdigit()), None)
    if journal_seg is None:
        return host, None, None
    idx = segments.index(journal_seg)
    return host, journal_seg, "/".join(segments[: idx + 1])


def _url_matches_scope(url: str, journal_seg: str) -> bool:
    """True si la URL enlaza específicamente al alcance de la revista dentro del portal."""
    u = (url or "").lower()
    return f"/{journal_seg}/" in u or u.endswith(f"/{journal_seg}") or f"journal={journal_seg}" in u


def _journal_identity_from_url(url: str) -> Optional[str]:
    """Identidad de la revista en un portal OJS compartido: el segmento inmediatamente
    posterior a 'index.php' en la ruta. Devuelve None si la URL no sigue ese patrón
    (p. ej. un sitio monorevista con secciones como /pdfs/ o /indice/), evitando así
    marcar como 'portal compartido' a una revista con su propio dominio.
    Normaliza a minúsculas para comparaciones insensibles a mayúsculas (index.php/Rehuso
    == index.php/rehuso)."""
    try:
        path = urllib.parse.urlparse(url or "").path.lower()
    except Exception:
        path = (url or "").split("?")[0].lower()
    segments = [s for s in path.split("/") if s]
    try:
        last_idx = len(segments) - 1 - segments[::-1].index("index.php")
    except ValueError:
        return None
    if last_idx + 1 >= len(segments):
        return None
    nxt = segments[last_idx + 1]
    if nxt not in _OJS_GENERIC and not nxt.isdigit() and "." not in nxt and ":" not in nxt:
        return nxt
    return None


def _n_es(n: int, singular: str, plural: str) -> str:
    """'1 cita en Wikipedia' / '3 citas en Wikipedia' (concordancia español)."""
    return f"{n} {singular if n == 1 else plural}"


def _otras_citas_frase(x: int, y: int) -> str:
    """Frase sobre cuántas de las Y citas del host en Wikipedia pertenecen a otras revistas."""
    if y <= 0:
        return "no hay citas del host en Wikipedia para comparar"
    if x <= 0:
        return "ninguna de las citas del host en Wikipedia proviene de otras revistas"
    if x == y:
        return "la única cita del host en Wikipedia proviene de otras revistas" if y == 1 \
            else f"las {y} citas del host en Wikipedia provienen de otras revistas"
    if x == 1:
        return f"1 de las {y} citas del host en Wikipedia proviene de otra revista del portal"
    return f"{x} de las {y} citas del host en Wikipedia provienen de otras revistas del portal"


def _is_portal_host(host: str) -> bool:
    """True si el host parece un portal OJS multirevista (revistas.x, ojs.x, journals.x…).

    En esos hosts la Centralidad Armónica/PageRank y las citas son del PORTAL completo,
    y las citas de Wikipedia deben filtrarse al alcance de la revista concreta."""
    h = (host or "").lower()
    if h.startswith(("revistas.", "ojs.", "journals.", "publicaciones.", "revistascientificas.", "portales.", "webs.")):
        return True
    return "/revistas/" in h or "/ojs/" in h or "/journals/" in h


def _is_public_suffix(base: str) -> bool:
    """True si 'base' es un sufijo público conocido (TLD o sufijo compuesto)."""
    if "." not in base:
        return True
    return base in CC_PUBLIC_SUFFIXES


def _domain_candidates(clean_dom: str) -> List[str]:
    """Candidatos de dominio para consultar el Web Graph: el dominio exacto y sus ancestros
    institucionales, deteniéndose antes de un sufijo público (PSL parcial). Ej.:
    palabraclave.unisabana.edu.co -> [palabraclave.unisabana.edu.co, unisabana.edu.co]
    (nunca 'edu.co')."""
    parts = clean_dom.split(".")
    out = [clean_dom]
    for i in range(1, len(parts) - 1):
        cand = ".".join(parts[i:])
        if _is_public_suffix(cand):
            break
        out.append(cand)
    return out


_total_domains_cache: Dict[str, int] = {}


def _cc_total_domains(db_path: str = CC_DOMAIN_RANKS_DB) -> Optional[int]:
    """Total de dominios del release indexado (tabla de metadatos del índice, con fallback COUNT)."""
    global _total_domains_cache
    if db_path in _total_domains_cache:
        return _total_domains_cache[db_path]
    if not os.path.exists(db_path):
        return None
    total: Optional[int] = None
    try:
        conn = sqlite3.connect(db_path)
        try:
            has_meta = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cc_index_meta'"
            ).fetchone()[0]
            if has_meta:
                row = conn.execute("SELECT total_domains FROM cc_index_meta LIMIT 1").fetchone()
                if row:
                    total = int(row[0])
            if total is None:
                total = int(conn.execute("SELECT COUNT(*) FROM cc_ranks").fetchone()[0])
        finally:
            conn.close()
    except Exception as e:
        log.warning("No se pudo leer el total de dominios de %s: %s", db_path, e)
        return None
    _total_domains_cache[db_path] = total
    return total


def _get_proximity_radius(r_rank: Optional[int], total_domains: int = 58_900_000) -> float:
    """Calcula el radio polar normalizado (0 a 1) para un rango de Centralidad Armónica."""
    import math
    if not r_rank or r_rank <= 0:
        return 0.94
    if r_rank <= 10_000:
        frac = max(0.0, math.log10(max(1, r_rank)) / 4.0)
        return 0.08 + frac * (0.25 - 0.08)
    elif r_rank <= 100_000:
        frac = (math.log10(r_rank) - 4.0) / 1.0
        return 0.25 + frac * (0.48 - 0.25)
    elif r_rank <= 500_000:
        frac = (math.log10(r_rank) - 5.0) / math.log10(5.0)
        return 0.48 + frac * (0.70 - 0.48)
    elif r_rank <= 2_000_000:
        frac = (math.log10(r_rank) - math.log10(500_000)) / math.log10(4.0)
        return 0.70 + frac * (0.88 - 0.70)
    else:
        denom = math.log10(total_domains) - math.log10(2_000_000)
        frac = min(1.0, (math.log10(r_rank) - math.log10(2_000_000)) / denom) if denom > 0 else 1.0
        return 0.88 + frac * (0.95 - 0.88)


def _iter_history_releases() -> List[Tuple[str, str, int]]:
    """Devuelve [(release_id, db_path, period_sort)] de los releases históricos indexados,
    en orden cronológico según el metadata del índice."""
    if not os.path.isdir(CC_HISTORY_DIR):
        return []
    out: List[Tuple[str, str, int]] = []
    for fname in os.listdir(CC_HISTORY_DIR):
        if not fname.endswith(".db"):
            continue
        db_path = os.path.join(CC_HISTORY_DIR, fname)
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT release_id, period_sort FROM cc_index_meta LIMIT 1"
            ).fetchone()
            conn.close()
        except Exception:
            continue
        if row:
            out.append((row[0], db_path, int(row[1] or 0)))
    out.sort(key=lambda x: x[2])
    return out



WEB_TWINS_RELEASE = "cc-main-2025-26-nov-dec-jan"

# Hubs sombra: los dominios más enlazados de toda la web (buscadores, redes globales,
# infraestructura de identificadores, plataformas). Enlazan a todo el mundo: no dicen
# nada de la revista ni son alcanzables por gestión editorial. Se excluyen de la
# brecha de enlaces y de la cabecera de referrers.
MEGA_HUB_DOMAINS = {
    "google.com", "googleapis.com", "googleusercontent.com", "gstatic.com", "youtube.com",
    "blogspot.com", "blogspot.com.es", "blogspot.com.ar", "blogspot.com.br", "blogspot.pe",
    "wikipedia.org", "wikimedia.org", "wikiwand.com",
    "facebook.com", "fb.com", "messenger.com", "instagram.com", "whatsapp.com",
    "twitter.com", "x.com", "t.co", "linkedin.com", "medium.com", "substack.com",
    "github.com", "githubusercontent.com", "gitlab.com",
    "amazon.com", "amazonaws.com", "cloudfront.net", "microsoft.com", "live.com",
    "office.com", "apple.com", "icloud.com", "vk.com", "ok.ru", "yandex.ru", "t.me",
    "researchgate.net", "academia.edu", "orcid.org", "doi.org", "crossref.org",
    "datacite.org", "issn.org", "wordpress.com", "gravatar.com",
    # Plataformas de hosting gratuito / shared: "el hub" son miles de sitios, no uno alcanzable.
    "github.io", "netlify.app", "vercel.app", "pages.dev", "eu.org", "glitch.me",
    "wixsite.com", "weebly.com", "cargo.site", "notion.site", "wordpress.com", "tumblr.com",
    "azurewebsites.net", "herokuapp.com", "web.app", "appspot.com", "worker.dev", "000webhostapp.com",
}

# TLDs usados casi exclusivamente por granjas SEO/spam: un "hub" en uno de estos no es
# una oportunidad de adquisición, es ruido del grafo.
_SPAM_TLDS = (".click", ".icu", ".monster", ".top", ".win", ".cyou", ".sbs", ".rest", ".bet", ".link")

# ccTLDs de la región iberoamericana + Portugal/Brasil: hubs terminados en estos son
# accionables (mismo ecosistema de indexación, idioma y redes académicas).
_IBERO_CC = (".es", ".mx", ".ar", ".co", ".pe", ".ec", ".uy", ".cl", ".bo", ".cr", ".gt",
             ".cu", ".do", ".ni", ".pa", ".sv", ".py", ".ve", ".hn", ".pt", ".br", ".pr")

# Infraestructura de visibilidad reconocida (accionable esté donde esté): indexarse o
# aparecer aquí es una gestión editorial concreta y legítima.
_INDEXER_KW = ("doaj", "scielo", "redalyc", "latindex", "clacso", "dialnet", "erih", "miar",
               "rebiun", "scilit", "dimensions.ai", "latinrev", "cuestiones", "actualidad",
               "repositorio", "docecalles", "freejournals", "gooe", "road", "issn", "openaire",
               "zenodo", "osf.io", "core.ac", "base-search", "ciriec", "fbic", "academia-lat")





_SCIVIS_RANKING_CACHE: Dict[str, Any] = {}
_SCIVIS_RANKING_TTL = 3600  # 1 h: el release no cambia entre consultas


