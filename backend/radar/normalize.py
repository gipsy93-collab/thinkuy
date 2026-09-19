"""Normalización de texto: acentos, entidades HTML, fechas. Clave para el matching."""
from __future__ import annotations

import html
import re
import unicodedata

_ALNUM_SPACE = re.compile(r"[^a-z0-9]+")
_HTML_TAGS = re.compile(r"<[^>]+>")


def unescape(s: str | None) -> str:
    """Limpia entidades HTML (p. ej. &#8217; en abstracts de SciELO) y etiquetas JATS."""
    if not s:
        return ""
    s = html.unescape(s)
    s = _HTML_TAGS.sub(" ", s)
    return " ".join(s.split())


def norm(s: str | None) -> str:
    """Minúsculas, sin acentos, solo caracteres alfanuméricos y espacios.
    'Comunicación Política' -> 'comunicacion politica'. Permite matching insensible a acentos."""
    s = unescape(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _ALNUM_SPACE.sub(" ", s.lower()).strip()


def tokens(s: str | None) -> list[str]:
    return norm(s).split()


_DOI_RE = re.compile(r"(10\.\d{4,9}/\S+)", re.IGNORECASE)
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def clean_doi(val: str | None) -> str:
    """Forma canónica de un DOI: `10.xxxx/…`, sin URL ni prefijo `doi:`, en minúsculas."""
    if not val:
        return ""
    s = str(val).strip()
    m = _DOI_RE.search(s)
    if m:
        s = m.group(1)
    else:
        s = _DOI_PREFIX_RE.sub("", s, count=1)
    return s.strip().lower().rstrip(".,;/")


def date_int(pub_date: str | None) -> int:
    """Clave numérica de una fecha ISO (`YYYYMMDD`) para ordenar; sin fecha = 0."""
    if not pub_date:
        return 0
    d = re.sub(r"\D", "", str(pub_date))[:8]
    return int(d) if d else 0


def edit_distance(s1: str, s2: str) -> int:
    """Distancia de Levenshtein con transposición (Damerau-Levenshtein)."""
    if s1 == s2:
        return 0
    len1, len2 = len(s1), len(s2)
    if abs(len1 - len2) > 2:
        return abs(len1 - len2)
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and s1[i - 1] == s2[j - 2] and s1[i - 2] == s2[j - 1]:
                dp[i][j] = min(dp[i][j], dp[i - 2][j - 2] + 1)
    return dp[len1][len2]


# Grupos de variantes equivalentes específicos del campo (p. ej. periodismo/jornalismo).
# Lo rellena profile.load_profile() desde el perfil activo.
EXTRA_VARIANT_GROUPS: list[frozenset] = []


def word_variants(w: str) -> set[str]:
    """Genera variantes morfológicas y equivalencias español-portugués."""
    wn = norm(w)
    if not wn:
        return set()
    res = {wn}
    # Terminaciones -ción (ES) <-> -ção (PT) y sus plurales
    if wn.endswith("cion"):
        stem = wn[:-4]
        res.update({stem + "cao", stem + "ciones", stem + "coes"})
    elif wn.endswith("cao"):
        stem = wn[:-3]
        res.update({stem + "cion", stem + "ciones", stem + "coes"})
    elif wn.endswith("ciones"):
        stem = wn[:-6]
        res.update({stem + "cion", stem + "cao", stem + "coes"})
    elif wn.endswith("coes"):
        stem = wn[:-4]
        res.update({stem + "cion", stem + "cao", stem + "ciones"})

    # social / sociales / sociais
    if wn in ("social", "sociales", "sociais"):
        res.update({"social", "sociales", "sociais"})

    # digital / digitales / digitais
    if wn in ("digital", "digitales", "digitais"):
        res.update({"digital", "digitales", "digitais"})

    # cientifica / cientifico / cientificas / cientificos
    if any(wn.startswith(prefix) for prefix in ("cientific", "politic", "academic", "tecnologic")):
        base = wn.rstrip("asoe")
        for suffix in ("a", "o", "as", "os"):
            res.add(base + suffix)

    # altmetrics y erratas frecuentes en español (p. ej. 'almétricas' sin la t)
    if wn in ("altmetrics", "altmetric", "almetrics", "almetric",
              "altmetrica", "altmetricas", "almetrica", "almetricas"):
        res.update({"altmetrics", "altmetric", "almetrics", "almetric",
                    "altmetrica", "altmetricas", "almetrica", "almetricas"})

    # periodismo <-> jornalismo y variantes (grupos del perfil de campo)
    for group in EXTRA_VARIANT_GROUPS:
        if wn in group:
            res |= group

    return res



def am_date(d: str | None) -> str | None:
    """Fecha SciELO 'YYYYMMDD' -> ISO 'YYYY-MM-DD'."""
    d = (d or "").strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d or None


def year_of(d: str | None) -> int | None:
    if not d:
        return None
    d = d.strip()
    if len(d) >= 4 and d[:4].isdigit():
        return int(d[:4])
    return None


# ISO 639-2 (3 letras) -> ISO 639-1 (2 letras), para idiomas frecuentes
_ISO639_2_TO_1 = {
    "spa": "es", "por": "pt", "eng": "en", "fra": "fr", "deu": "de", "ita": "it",
    "cat": "ca", "glg": "gl", "eus": "eu", "nld": "nl", "rus": "ru", "ara": "ar",
    "jpn": "ja", "zho": "zh", "pol": "pl", "tur": "tr", "swe": "sv", "dan": "da",
    "nor": "no", "fin": "fi", "ces": "cs", "ell": "el", "heb": "he", "hin": "hi",
    "ukr": "uk", "ron": "ro", "slv": "sl", "hrv": "hr", "srp": "sr", "bul": "bg",
    "vie": "vi", "tha": "th", "ind": "id", "msa": "ms", "fas": "fa", "hun": "hu",
}


def norm_lang(lang: str | None) -> str | None:
    """Normaliza el idioma a ISO 639-1 de 2 letras ('pt-BR' -> 'pt', 'spa' -> 'es').

    Devuelve None si no se puede normalizar (los feeds filtran por 'es','pt','en'...).
    """
    if not lang:
        return None
    l = lang.strip().lower().split("-")[0]
    if len(l) == 3:
        l = _ISO639_2_TO_1.get(l, l)
    if len(l) != 2 or not l.isalpha():
        return None
    return l


# ==============================================================================
# EVALUACIÓN DEL TEXTO DUBLIN CORE DE OAI-PMH (detectar, no inventar)
# ==============================================================================
# Motivo medido (18-09-2026): la descripción que Redalyc publica en su OAI viene del texto
# extraído de PDF sin separador en los saltos de línea, de modo que las palabras llegan
# pegadas ('delSoconusco', 'losproblemas', 'estrategiasque'), y en muchos registros los
# glifos están sustituidos ('cafetalerq', 'Tijuanq', '&' por 'de').
#
# **Se intentó repararlo por reglas y se midió que es inseguro.** Sobre 500 resúmenes
# LIMPIOS de la propia base, las reglas de reparación modificaban texto correcto:
#
#   | regla                       | modifica texto limpio | daño observado                            |
#   |-----------------------------|----------------------:|-------------------------------------------|
#   | guion de línea              |                 67,8 % | 'food-energy-water' -> 'foodenergywater'  |
#   | prefijo palabra función     |                 98,0 % | 'community' -> 'com munity'               |
#   | minúscula->MAYÚSCULA        |                  9,4 % | 'DataStream' -> 'Data Stream'             |
#   | espacio antes de puntuación |                  5,0 % | contra la norma RAE ('70 %' lleva espacio)|
#
# Conclusión medida: **el pegote no es reparable por reglas sin corromper texto limpio**, y
# **las señales de superficie no permiten detectarlo con fidelidad**. Lo que se hace es:
#
#   1. normalizar SOLO el espaciado (`normalizar_espacios`), que es inocuo (0 % de palabras
#      alteradas sobre 500 resúmenes limpios de la base);
#   2. obtener el texto citable del **PDF** (escalón 4), que **sí arregla los pegotes** porque
#      la extracción respeta el diseño de la página.
#
# La corrupción de glifos ('cafetalerq', 'jhales') **está en el PDF de origen** —su fuente
# tiene un mapa ToUnicode roto—, de modo que ningún método de ingesta la arregla. Se acepta y
# se muestra tal cual: reconstruirla sería inventar caracteres, lo que el protocolo prohíbe.

_LETRA = "a-záéíóúüñç"
_RE_ESPACIOS = re.compile(r"\s+")

# Señales de glifos sustituidos: ALTA precisión (mejor no marcar que acusar en falso).
# Se excluye el dígrafo 'qu', que es legítimo, y los clústeres consonánticos del español
# ('nstr' en 'construcción'), que producían falsos positivos en la primera versión.
_SENALES_GLIFOS = (
    re.compile(rf"[{_LETRA}]\d[{_LETRA}]"),              # dígito dentro de palabra: 'demogr6jico'
    re.compile(r"q(?!u)"),                               # 'q' sin 'u': 'Tijuanq', 'cafetalerq'
    re.compile(rf"(?:^|\s)&(?:\s|$)|&[{_LETRA}]"),        # '&' suelto o pegado: '& conocer'
    re.compile(rf"[bcdfghklmnpqrstvwxyz]j[{_LETRA}]"),    # 'j' tras consonante: 'geográjka'
    re.compile(rf"[{_LETRA}][A-ZÁÉÍÓÚÜÑÇ][{_LETRA}]"),    # mayúscula interior: 'CaüfomhA'
    re.compile(r"\b[bcdfghjklmnpqrstvwxyz]{5,}\b"),    # palabra sin vocales: 'jhls'
)

# Señal de PEGOTE: cambio de minúscula a MAYÚSCULA dentro de palabra ('delSoconusco').
# Medido: NO discrimina como filtro (dispara en 'BioClima', 'MyPlate'), así que se usa para
# CONTAR y diagnosticar, nunca como veredicto.
_SENAL_PEGOTE = re.compile(rf"[{_LETRA}][a-záéíóúüñç][A-ZÁÉÍÓÚÜÑÇ][a-záéíóúüñç]{{2,}}")


def normalizar_espacios(texto: str | None) -> str:
    """Normalización inocua: resuelve entidades y colapsa espacios. No altera palabras."""
    return _RE_ESPACIOS.sub(" ", unescape(texto)).strip()


def senales_glifos(texto: str | None) -> list[str]:
    """Qué señales de glifos sustituidos aparecen (vacío = ninguna)."""
    t = texto or ""
    return [patron.pattern for patron in _SENALES_GLIFOS if patron.search(t)]


def senales_pegotes(texto: str | None) -> int:
    """Cuántos pegotes por cambio de caso aparecen en el texto."""
    return len(_SENAL_PEGOTE.findall(texto or ""))


def evaluar_texto_dc(texto: str | None) -> dict:
    """Diagnóstico de un texto Dublin Core: espaciado normalizado y **conteo** de señales.

    No emite veredicto. Se probó un veredicto `citable` y **se midió que no discrimina**:
    marcaba como sospechoso el 42 % de resúmenes LIMPIOS de la propia base mientras solo
    detectaba el 42–51 % del texto dañado. Las señales de superficie (`j` tras consonante
    dispara en 'objectives'; mayúscula interior en 'BioClima') son inútiles como filtro.

    Se conserva el conteo porque es la evidencia con la que se llegó a esa conclusión y
    sirve para volver a medir, no como aviso al usuario.
    """
    return {
        "texto": normalizar_espacios(texto),
        "pegotes": senales_pegotes(texto),
        "glifos": senales_glifos(texto),
    }