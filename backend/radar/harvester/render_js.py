"""Escalón 5 de la escalera de ingesta: renderizado con navegador sin cabeza (Playwright).

**Último recurso.** Solo sobre URLs concretas que el investigador solicita, nunca en
recorridos masivos. Dos muros medidos el 18-09-2026 lo justifican:

* **SciELO** (ruta antigua `scielo.php?script=sci_arttext&pid=...`): devolvió **714 bytes
  de un CDN** en lugar de la ficha.
* **Redalyc**: la ficha pesa ~10 KB y **el resumen se carga por JavaScript**; su PDF
  tampoco lo trae en los artículos antiguos.

Reglas de entrada (no negociables):

1. **Una URL por llamada.** No hay método de recorrido ni de descubrimiento.
2. **`robots.txt` se consulta antes** de renderizar. Si no se puede verificar, se declara
   en el resultado (`robots: "no_verificable"`) en lugar de fingir que se comprobó.
3. **El HTML se cachea en disco**: la misma URL no se renderiza dos veces.

Uso:

    if render_js.disponible() and render_js.robots_permite(url, http):
        html = render_js.render(url)
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .. import config

log = logging.getLogger("radar.render_js")

DIR_CACHE = config.DATA_DIR / "html_render"

# Recursos que no aportan metadatos: se abortan para bajar el coste del render.
RECURSOS_INUTILES = ("image", "font", "media", "stylesheet")


class RenderNoDisponible(RuntimeError):
    """Playwright no está instalado en este entorno."""


class RobotsDenegado(RuntimeError):
    """`robots.txt` prohíbe explícitamente que el agente consulte esa URL."""


def disponible() -> bool:
    """¿Está Playwright instalado? No comprueba que el navegador esté descargado."""
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def ruta_cache(url: str) -> Path:
    """Ruta del HTML renderizado en caché (nombre estable a partir de la URL)."""
    limpio = re.sub(r"\W+", "_", url)[-70:]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return DIR_CACHE / f"{limpio}_{digest}.html"


def robots_permite(url: str, http: httpx.Client | None = None) -> bool | None:
    """¿Permite `robots.txt` consultar esa URL?

    Devuelve ``True``/``False`` si se pudo verificar, y ``None`` si no (robots.txt
    inalcanzable). Nunca lanza: la decisión de seguir queda en quien llama.
    """
    partes = urlparse(url)
    if not partes.scheme or not partes.netloc:
        return None
    cerrar = http is None
    cliente = http or httpx.Client(headers={"User-Agent": config.USER_AGENT},
                                   follow_redirects=True, timeout=15.0)
    try:
        respuesta = cliente.get(f"{partes.scheme}://{partes.netloc}/robots.txt")
        if respuesta.status_code >= 400:
            return True  # sin robots.txt no hay restricción declarada
        analizador = RobotFileParser()
        analizador.parse(respuesta.text.splitlines())
        return bool(analizador.can_fetch(config.USER_AGENT, url))
    except Exception as e:
        log.warning("robots.txt de %s no verificable: %s", partes.netloc, e)
        return None
    finally:
        if cerrar:
            cliente.close()


def render(url: str, *, timeout_ms: int = 30000, esperar_ms: int = 1500,
           espera_selector: str | None = None, bloquear_recursos: bool = True) -> str:
    """Renderiza la URL y devuelve el HTML **después** de ejecutar el JavaScript."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RenderNoDisponible(f"Playwright no está instalado: {e}") from e

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = navegador.new_context(user_agent=config.USER_AGENT,
                                         java_script_enabled=True)
        if bloquear_recursos:
            def _filtrar(ruta):
                try:
                    if ruta.request.resource_type in RECURSOS_INUTILES:
                        ruta.abort()
                    else:
                        ruta.continue_()
                except Exception:
                    ruta.continue_()
            contexto.route("**/*", _filtrar)

        pagina = contexto.new_page()
        try:
            pagina.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if espera_selector:
                pagina.wait_for_selector(espera_selector, timeout=timeout_ms)
            if esperar_ms:
                pagina.wait_for_timeout(esperar_ms)
            return pagina.content()
        finally:
            try:
                navegador.close()
            except Exception:
                pass


def render_cacheado(url: str, *, usar_cache: bool = True, http: httpx.Client | None = None,
                    **kwargs) -> tuple[str, bool]:
    """Renderiza con caché en disco. Devuelve (html, vino_de_cache).

    Si `usar_cache` y ya existe, **no se renderiza de nuevo** (no se vuelve a molestar
    al servidor) y tampoco se consulta `robots.txt` otra vez.
    """
    destino = ruta_cache(url)
    if usar_cache and destino.exists():
        return destino.read_text(encoding="utf-8", errors="replace"), True

    permiso = robots_permite(url, http)
    if permiso is False:
        raise RobotsDenegado(f"robots.txt prohíbe consultar {url}")

    html = render(url, **kwargs)
    try:
        DIR_CACHE.mkdir(parents=True, exist_ok=True)
        destino.write_text(html, encoding="utf-8")
    except OSError as e:
        log.warning("no se pudo cachear el render de %s: %s", url, e)
    return html, False
