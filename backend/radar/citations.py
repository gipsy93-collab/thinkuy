"""Exportación de citas: APA 7, BibTeX y RIS (Zotero)."""
from __future__ import annotations

import re
from datetime import datetime

from .normalize import unescape

_LANG_RIS = {
    "es": "spa", "pt": "por", "en": "eng", "fr": "fre", "it": "ita",
    "de": "ger", "ca": "cat", "gl": "glg", "eu": "eus", "no": "nor",
}

# ---------------------------------------------------------------- helpers
def _authors(art: dict) -> list[dict]:
    out = []
    for au in art.get("authors") or []:
        if isinstance(au, dict):
            given = unescape(au.get("given") or au.get("n") or "")
            family = unescape(au.get("family") or au.get("s") or "")
        else:
            given, family = "", unescape(str(au))
        if family or given:
            out.append({"given": given, "family": family,
                        "orcid": (au.get("orcid") if isinstance(au, dict) else "")})
    return out


def _year(art: dict) -> str:
    y = art.get("year")
    if not y:
        return "s. f."
    return str(y)


def _doi_url(art: dict) -> str:
    doi = (art.get("doi") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    return art.get("url") or ""


def _pages(art: dict) -> tuple[str, str]:
    p = art.get("pages")
    if not p:
        return "", ""
    if "-" in p:
        a, b = p.split("-", 1)
        return a.strip(), b.strip()
    return p, ""


# ---------------------------------------------------------------- APA 7
def _apa_names(aus: list[dict]) -> str:
    """Autores en formato APA 7: 1 -> 'Apellido, N.'; 2 -> 'A & B';
    3-20 -> 'A, B, C, & D'; 21+ -> primeros 19 + '…' + último (sin &)."""
    names = []
    for au in aus:
        surname = au["family"].strip()
        init = "".join(p[0].upper() + "." for p in au["given"].replace("-", " ").split() if p)
        names.append(f"{surname}, {init}" if (surname and init) else (surname or init))
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    if len(names) <= 20:
        return ", ".join(names[:-1]) + " & " + names[-1]
    return ", ".join(names[:19]) + ", … " + names[-1]


def format_apa(art: dict) -> str:
    aus = _authors(art)
    head = _apa_names(aus) or (art.get("journal_title") or "Anónimo")
    year = _year(art)
    title = unescape(art.get("title") or "")
    journal = unescape(art.get("journal_title") or "")
    vol = art.get("volume") or ""
    iss = art.get("issue") or ""
    sp, ep = _pages(art)
    parts = [f"{head} ({year})."]
    if title:
        parts.append(title.rstrip(".") + ".")
    jpart = journal
    if vol:
        jpart += f", *{vol}*"
    if iss:
        jpart += f"({iss})"
    if sp:
        jpart += ", " + (f"{sp}-{ep}" if ep else sp)
    if jpart.strip():
        parts.append(jpart.rstrip(",") + ".")
    url = _doi_url(art)
    if url:
        parts.append(url)
    return " ".join(parts)


# ---------------------------------------------------------------- BibTeX
def _bibkey(art: dict, used: set[str]) -> str:
    aus = _authors(art)
    base = re.sub(r"[^a-zA-Z0-9]", "", (aus[0]["family"] if aus else "anon")).lower()[:24] or "anon"
    doi = art.get("doi") or ""
    # DOI truncado (8 caracteres alfanuméricos): unicidad global entre autores homónimos
    doi_part = re.sub(r"[^a-zA-Z0-9]", "", doi)[:8] if doi else ""
    key = f"{base}{_year(art)}{doi_part}"
    n = 1
    while key in used:
        n += 1
        key = f"{base}{_year(art)}{doi_part}{'abcdefghij'[n - 1]}"
    used.add(key)
    return key


def format_bibtex(art: dict, used: set[str] | None = None) -> str:
    used = used if used is not None else set()
    key = _bibkey(art, used)
    aus = _authors(art)
    author = " and ".join(
        f"{au['family']}, {au['given']}" if au["given"] else au["family"] for au in aus
    ) if aus else "Anónimo"
    fields = [
        ("author", author),
        ("title", unescape(art.get("title") or "")),
    ]
    if art.get("journal_title"):
        fields.append(("journal", unescape(art["journal_title"])))
    if art.get("volume"):
        fields.append(("volume", str(art["volume"])))
    if art.get("issue"):
        fields.append(("number", str(art["issue"])))
    sp, ep = _pages(art)
    if sp:
        fields.append(("pages", f"{sp}--{ep}" if ep else sp))
    if art.get("year"):
        fields.append(("year", str(art["year"])))
    if art.get("doi"):
        fields.append(("doi", art["doi"]))
    url = _doi_url(art)
    if url:
        fields.append(("url", url))
    if art.get("lang"):
        fields.append(("language", art["lang"]))
    body = ",\n  ".join(f"{k} = {{{unescape(str(v))}}}" for k, v in fields)
    return f"@article{{{key},\n  {body}\n}}"


# ---------------------------------------------------------------- RIS (Zotero)
def format_ris(art: dict) -> str:
    lines = ["TY  - JOUR"]
    for au in _authors(art):
        name = f"{au['family']}, {au['given']}" if au["given"] else au["family"]
        lines.append(f"AU  - {name}")
    if art.get("year"):
        lines.append(f"PY  - {art['year']}")
    if art.get("pub_date"):
        lines.append(f"DA  - {art['pub_date']}")
    lines.append(f"TI  - {unescape(art.get('title') or '')}")
    if art.get("title_alt"):
        lines.append(f"TT  - {unescape(art['title_alt'])}")
    if art.get("journal_title"):
        # JO (journal name) es el campo RIS canónico; JF ya no se duplica
        lines.append(f"JO  - {unescape(art['journal_title'])}")
    if art.get("volume"):
        lines.append(f"VL  - {art['volume']}")
    if art.get("issue"):
        lines.append(f"IS  - {art['issue']}")
    sp, ep = _pages(art)
    if sp:
        lines.append(f"SP  - {sp}")
    if ep:
        lines.append(f"EP  - {ep}")
    if art.get("doi"):
        lines.append(f"DO  - {art['doi']}")
    url = _doi_url(art)
    if url:
        lines.append(f"UR  - {url}")
    if art.get("lang"):
        lines.append(f"LA  - {_LANG_RIS.get(art['lang'], 'und')}")
    if art.get("abstract"):
        lines.append(f"AB  - {unescape(art['abstract'])}")
    for kw in art.get("keywords") or []:
        if isinstance(kw, dict):
            kw = kw.get("k", "")
        if kw:
            lines.append(f"KW  - {kw}")
    lines.append("ER  - ")
    return "\n".join(lines)


def format_citation(art: dict, fmt: str) -> str:
    fmt = (fmt or "apa").lower()
    if fmt == "bibtex":
        return format_bibtex(art)
    if fmt == "ris":
        return format_ris(art)
    return format_apa(art)


def citation_filename(art: dict, fmt: str) -> str:
    aus = _authors(art)
    base = re.sub(r"[^a-zA-Z0-9]", "", (aus[0]["family"] if aus else "thinkuy")).lower()
    y = art.get("year") or "s.f."
    ext = {"apa": "txt", "bibtex": "bib", "ris": "ris"}.get(fmt, "txt")
    return f"thinkuy-{base}-{y}.{ext}"