"""Banco de pruebas: extracción de metadatos de una página de artículo.

Compara DOS vías sobre la MISMA página HTML:

  VÍA A — determinista: meta etiquetas `citation_*` y JSON-LD (si la página las trae).
  VÍA B — dirigida por esquema: un LLM recibe la página + un JSON Schema y devuelve JSON.
          Es el modo de trabajo del modelo Schematron (inference-net), pero sirve cualquier
          modelo del endpoint compatible con OpenAI de LM Studio.

El objetivo es medir cuánto aporta la VÍA B cuando la VÍA A no alcanza (páginas OJS que no
exponen meta etiquetas), y confirmar si en páginas tipo SciELO la VÍA A ya es suficiente.

USO:
    python tools/probar_schematron.py --html data/demo/html/scielo_reben.html
    python tools/probar_schematron.py --url https://revista.ejemplo.org/articulo/123 --guardar
    python tools/probar_schematron.py --html ... --modelo inference-net/schematron-3b
SALIDAS:
    data/demo/comparacion_extraccion.json  y  impresión en consola
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

LLM_API = os.environ.get("THINKUY_LLM_API", "http://127.0.0.1:1234/v1").rstrip("/")
LLM_MODEL = os.environ.get("THINKUY_LLM_MODEL", "qwen2.5-coder-7b-instruct")
LLM_KEY = os.environ.get("THINKUY_LLM_KEY", "")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# Esquema de salida (JSON Schema). Se le entrega al modelo tal cual.
ESQUEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string", "description": "Título del artículo, en su idioma original."},
        "autores": {"type": "array", "items": {"type": "string"},
                    "description": "Nombres completos de los autores, en orden."},
        "anio": {"type": "integer", "description": "Año de publicación."},
        "revista": {"type": "string", "description": "Nombre de la revista."},
        "doi": {"type": "string", "description": "DOI del artículo, sin URL. Cadena vacía si no aparece."},
        "idioma": {"type": "string", "description": "Código de idioma del texto (es, pt, en)."},
        "resumen": {"type": "string", "description": "Resumen del artículo (máx. 1500 caracteres)."},
        "palabras_clave": {"type": "array", "items": {"type": "string"},
                           "description": "Palabras clave declaradas por los autores."},
        "tipo_publicacion": {"type": "string",
                             "description": "Tipo declarado: revisión sistemática, scoping review, artículo original, etc. Cadena vacía si no se declara."},
    },
    "required": ["titulo", "autores", "anio", "revista", "doi", "idioma", "resumen",
                 "palabras_clave", "tipo_publicacion"],
    "additionalProperties": False,
}

# Formato de prompt que usa la familia Schematron (respetarlo mejora su comportamiento)
PROMPT_1 = ("You are going to be given a JSON schema following the standardized JSON Schema "
            "format. You are going to be given a HTML page and you are going to apply the schema "
            "to the HTML page however you see it as applicable and return the results in a JSON "
            "object. The schema is as follows:")
PROMPT_2 = "Here is the HTML page:"
PROMPT_3 = "MAKE SURE ITS VALID JSON."


def norm(t: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def limpiar_html(t: str) -> str:
    """Quita script/style y colapsa espacios: la familia Schematron espera HTML pre-limpiado."""
    t = re.sub(r"<script\b.*?</script>", " ", t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<style\b.*?</style>", " ", t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.DOTALL)
    return t


def reducir_a_contenido(t: str) -> str:
    """Recorta a la región del artículo.

    Necesario en la práctica: la página completa de un OJS ronda los 8.500 tokens y un
    LM Studio típico carga 8.192 de contexto. La documentación de Schematron también
    recomienda pre-limpiar el HTML (dice que coincide con sus datos de entrenamiento).
    """
    # 1) bloques contenedores por etiqueta semántica
    for etiqueta in ("article", "main"):
        m = re.search(rf"<{etiqueta}\b.*?</{etiqueta}>", t, flags=re.DOTALL | re.IGNORECASE)
        if m and len(m.group(0)) > 1500:
            return m.group(0)
    # 2) contenedores por id/clase habituales en OJS
    for pat in (r'<div[^>]+id=["\'][^"\']*(?:content|main|article|primary)[^"\']*["\'][^>]*>',
                r'<div[^>]+class=["\'][^"\']*(?:content|main|article|primary)[^"\']*["\'][^>]*>'):
        m = re.search(pat, t, flags=re.IGNORECASE)
        if m:
            ini = m.start()
            # recorte conservador: 40.000 caracteres desde el contenedor
            return t[ini:ini + 40000]
    # 3) eliminar regiones claramente accesorias
    for etiqueta in ("nav", "header", "footer", "aside", "form"):
        t = re.sub(rf"<{etiqueta}\b.*?</{etiqueta}>", " ", t, flags=re.DOTALL | re.IGNORECASE)
    return t


def estimar_tokens(t: str) -> int:
    """Estimación gruesa para español/inglés: ~3,2 caracteres por token."""
    return int(len(t) / 3.2)


def meta_de(html_texto: str) -> dict:
    """VÍA A — meta etiquetas y JSON-LD. No usa LLM."""
    out: dict = {"titulo": "", "autores": [], "anio": None, "revista": "", "doi": "",
                 "idioma": "", "resumen": "", "palabras_clave": [], "tipo_publicacion": ""}
    metas = re.findall(r"<meta\s+([^>]+)>", html_texto, flags=re.IGNORECASE)
    for atributos in metas:
        nombre = re.search(r'name=["\']([^"\']+)["\']', atributos, re.IGNORECASE)
        contenido = re.search(r'content=["\'](.*?)["\']', atributos, re.IGNORECASE | re.DOTALL)
        if not nombre or not contenido:
            continue
        clave, valor = nombre.group(1).lower(), _html.unescape(contenido.group(1)).strip()
        if clave == "citation_title" and not out["titulo"]:
            out["titulo"] = valor
        elif clave == "citation_author":
            out["autores"].append(valor)
        elif clave == "citation_journal_title" and not out["revista"]:
            out["revista"] = valor
        elif clave in ("citation_publication_date", "citation_date", "citation_year") and not out["anio"]:
            m = re.search(r"(19|20)\d{2}", valor)
            if m:
                out["anio"] = int(m.group(0))
        elif clave == "citation_doi" and not out["doi"]:
            out["doi"] = valor.strip().lower()
        elif clave in ("citation_language", "citation_journal_language") and not out["idioma"]:
            out["idioma"] = valor.strip().lower()[:2]
        elif clave in ("citation_abstract", "description") and not out["resumen"]:
            out["resumen"] = valor
        elif clave == "citation_keywords":
            out["palabras_clave"].append(valor)
    return out


def json_ld_de(html_texto: str) -> dict:
    """VÍA A (ampliada) — datos estructurados schema.org."""
    out: dict = {}
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                         html_texto, flags=re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        for nodo in (data if isinstance(data, list) else [data]):
            if not isinstance(nodo, dict):
                continue
            if nodo.get("@type") in ("ScholarlyArticle", "Article", "NewsArticle"):
                out.setdefault("ld_titulo", nodo.get("headline") or nodo.get("name") or "")
                autores = nodo.get("author") or []
                if isinstance(autores, dict):
                    autores = [autores]
                out.setdefault("ld_autores", [a.get("name", "") for a in autores if isinstance(a, dict)])
                out.setdefault("ld_revista", (nodo.get("isPartOf") or {}).get("name", "")
                               if isinstance(nodo.get("isPartOf"), dict) else "")
                fecha = nodo.get("datePublished") or ""
                mm = re.search(r"(19|20)\d{2}", str(fecha))
                if mm:
                    out.setdefault("ld_anio", int(mm.group(0)))
    return out


def pedir_al_llm(html_texto: str, modelo: str, timeout: float = 600.0) -> dict | None:
    """VÍA B — LLM + JSON Schema.

    `max_tokens` se acota a 1.200: el JSON de salida (con un resumen de hasta 1.500
    caracteres) cabe de sobra, y valores altos solo alargan la generación en hardware
    de consumo. Un timeout de 600 s evita caídas cuando hay varios modelos cargados.
    """
    esquema_txt = json.dumps(ESQUEMA, ensure_ascii=False)
    prompt = f"{PROMPT_1}\n\n{esquema_txt}\n\n{PROMPT_2}\n\n{html_texto}\n\n{PROMPT_3}"
    cuerpo = {
        "model": modelo,
        "messages": [{"role": "system", "content": "You are a helpful assistant"},
                     {"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 1200,
        "stream": False,
    }
    cab = {"Content-Type": "application/json"}
    if LLM_KEY:
        cab["Authorization"] = f"Bearer {LLM_KEY}"
    r = httpx.post(f"{LLM_API}/chat/completions", json=cuerpo, timeout=timeout, headers=cab)
    if r.status_code >= 400:
        print(f"  LLM HTTP {r.status_code}: {r.text[:200]}")
        return None
    contenido = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", contenido, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def comparar(meta: dict, ld: dict, llm: dict | None) -> dict:
    campos = ["titulo", "autores", "anio", "revista", "doi", "idioma", "palabras_clave"]
    filas = []
    for c in campos:
        a = meta.get(c)
        b = llm.get(c) if llm else None
        if c == "autores" or c == "palabras_clave":
            a_txt = f"{len(a)}" if isinstance(a, list) else "0"
            b_txt = f"{len(b)}" if isinstance(b, list) else "—"
            coincide = bool(a) and bool(b) and norm(" ".join(map(str, a))[:60]) == norm(" ".join(map(str, b))[:60])
        else:
            a_txt = (str(a) or "—")[:60]
            b_txt = (str(b) if b is not None else "—")[:60]
            coincide = bool(a) and bool(b) and norm(str(a))[:40] == norm(str(b))[:40]
        filas.append({"campo": c, "meta": a_txt, "llm": b_txt, "coincide": coincide})
    return {"filas": filas, "ld": ld}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="", help="Ruta a un HTML local")
    ap.add_argument("--url", default="", help="URL de la página a probar")
    ap.add_argument("--modelo", default=LLM_MODEL)
    ap.add_argument("--guardar", action="store_true")
    ap.add_argument("--sin-llm", action="store_true", help="Solo la vía determinista")
    args = ap.parse_args()

    if args.url:
        r = httpx.get(args.url, follow_redirects=True, timeout=60, headers={"User-Agent": UA})
        html_texto = r.text
        destino = PROJECT_ROOT / "data" / "demo" / "html" / (re.sub(r"\W+", "_", args.url)[-60:] + ".html")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(html_texto, encoding="utf-8")
        print(f"Descargado {args.url} -> {destino} ({len(html_texto)} bytes)")
    else:
        p = Path(args.html)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if not p.exists():
            print(f"No existe {p}")
            return
        html_texto = p.read_text(encoding="utf-8", errors="replace")
        print(f"HTML local: {p.name} ({len(html_texto)} bytes)")

    limpio = limpiar_html(html_texto)
    reducido = reducir_a_contenido(limpio)
    print(f"HTML tras limpieza: {len(limpio)} bytes (~{estimar_tokens(limpio)} tokens)")
    print(f"HTML recortado a la región del artículo: {len(reducido)} bytes (~{estimar_tokens(reducido)} tokens)")

    print("\n" + "=" * 78)
    print("VÍA A — DETERMINISTA (meta etiquetas + JSON-LD)")
    print("=" * 78)
    meta = meta_de(html_texto)
    ld = json_ld_de(html_texto)
    for k, v in meta.items():
        if v:
            print(f"  meta {k}: {str(v)[:100]}")
    print(f"  JSON-LD encontrado: {list(ld.keys()) or 'ninguno'}")

    llm = None
    if not args.sin_llm:
        print("\n" + "=" * 78)
        print(f"VÍA B — LLM DIRIGIDO POR ESQUEMA (modelo: {args.modelo})")
        print("=" * 78)
        print("  enviando la página y el esquema…")
        import time
        t0 = time.time()
        llm = pedir_al_llm(reducido, args.modelo)
        print(f"  respuesta en {time.time()-t0:.1f} s")
        if llm:
            for k in ESQUEMA["required"]:
                v = llm.get(k)
                print(f"  {k}: {str(v)[:110]}")
        else:
            print("  sin respuesta parseable")

    print("\n" + "=" * 78)
    print("COMPARACIÓN")
    print("=" * 78)
    comp = comparar(meta, ld, llm)
    print(f"  {'campo':16} {'VÍA A (meta)':40} {'VÍA B (llm)':40}")
    for f in comp["filas"]:
        print(f"  {f['campo']:16} {str(f['meta']):40} {str(f['llm']):40}")

    if args.guardar:
        salida = PROJECT_ROOT / "data" / "demo" / "comparacion_extraccion.json"
        salida.write_text(json.dumps({"meta": meta, "json_ld": ld, "llm": llm, "comparacion": comp["filas"]},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nGuardado: {salida}")


if __name__ == "__main__":
    main()
