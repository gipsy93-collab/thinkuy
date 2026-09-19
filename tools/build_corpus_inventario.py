"""Inventario definitivo del corpus V2: deduplicacion por hash y usabilidad por tarea.

Lee data/corpus_v2/extraccion_v2.json, calcula el SHA-256 de cada PDF, marca copias
duplicadas (fuga potencial en el split) y determina la usabilidad real de cada
articulo para T1 (rol desde abstract), T2 (PCC desde metodologia) y T3 (auditoria
de citas). Produce:

    data/corpus_v2/inventario_unicos.json
    data/corpus_v2/COBERTURA_V2.md

USO:
    python tools/build_corpus_inventario.py
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPUS_V2 = PROJECT_ROOT / "data" / "corpus_v2"
ENTRADAS = sorted(CORPUS_V2.glob("extraccion_*.json"))

OBJETIVO = {"ES": 0.40, "PT": 0.30, "EN": 0.30}


PT_DETECT = re.compile(r"ção|ções|\bnão\b|\bembora\b|\bainda que\b|\bResumo\b|\bMétodos\b|\bResultados\b")
ES_DETECT = re.compile(r"ción|ciones|\bñ|\bResumen\b|\bMétodos\b|\bResultados\b|\bno obstante\b")
EN_DETECT = re.compile(r"\bthe\b|\bthis study\b|\bwe\b|\bmethods\b|\bresults\b", re.IGNORECASE)


def detectar_idioma(texto: str) -> str:
    if not texto:
        return "UNKNOWN"
    pt, es, en = len(PT_DETECT.findall(texto)), len(ES_DETECT.findall(texto)), len(EN_DETECT.findall(texto))
    mejor = max(pt, es, en)
    if mejor == 0:
        return "UNKNOWN"
    ganadores = [n for n, v in (("PT", pt), ("ES", es), ("EN", en)) if v == mejor]
    return ganadores[0] if len(ganadores) == 1 else "UNCERTAIN"


def idioma_del_cuerpo(rec: dict) -> str:
    """Idioma del CUERPO del artículo, no del abstract.

    Las revistas bilingües (SciELO, SciELO Brasil) exponen el abstract en inglés
    mientras el cuerpo está en español o portugués. Detectar el idioma en el abstract
    produce una estratificación falsa (caso detectado por el IP: "EN-07 no está en inglés").
    """
    sect = rec.get("sections") or {}
    claves = ("methods", "introduction", "results", "discussion", "conclusion")
    cuerpo = "\n".join(sect.get(k) or "" for k in claves)
    return detectar_idioma(cuerpo) if len(cuerpo) > 400 else detectar_idioma(
        (sect.get("abstract") or "") + (sect.get("abstract_alt") or "")
    )


def usabilidad(rec: dict) -> dict:
    sect = rec.get("sections") or {}
    abstract = (sect.get("abstract") or sect.get("abstract_alt") or "").strip()
    methods = (sect.get("methods") or "").strip()
    flags = set(rec.get("flags") or [])
    n_refs = rec.get("n_referencias") or 0
    total_chars = sum(len(v or "") for v in sect.values())

    t1 = len(abstract) >= 500 and "POSIBLE_NO_ARTICULO" not in flags
    t2 = (
        len(methods) >= 800
        and "METHODS_DESPROPORCIONADO" not in flags
        and "TABLA_EN_METHODS" not in flags
        and "REFS_EN_METHODS" not in flags
    )
    t3 = n_refs >= 10 and total_chars >= 8000 and "POSIBLE_NO_ARTICULO" not in flags
    return {"T1": t1, "T2": t2, "T3": t3}


def main() -> None:
    if not ENTRADAS:
        print(f"ERROR: no hay archivos extraccion_*.json en {CORPUS_V2}")
        return
    registros: list[dict] = []
    for entrada in ENTRADAS:
        lote = json.loads(entrada.read_text(encoding="utf-8"))
        for r in lote:
            r["lote"] = entrada.stem.replace("extraccion_", "")
        registros.extend(lote)
        print(f"  {entrada.name}: {len(lote)} registros")
    print(f"Registros totales fusionados: {len(registros)}")

    # ── Deduplicacion por hash de contenido ──
    por_hash: dict[str, list[dict]] = defaultdict(list)
    for r in registros:
        if "error" in r:
            continue
        sha = r.get("sha256") or ""
        if not sha:
            try:
                sha = hashlib.sha256(Path(r["pdf_path"]).read_bytes()).hexdigest()
            except Exception:
                sha = "SIN_HASH_" + r["doi_filename"]
        r["sha256"] = sha
        por_hash[sha].append(r)

    unicos: list[dict] = []
    duplicados: list[dict] = []
    for sha, grupo in por_hash.items():
        orden = sorted(grupo, key=lambda x: (x["area"] not in ("PRISMA_JBI", "SIN_PRISMA"), x["ruta_relativa"]))
        principal = orden[0]
        principal["es_duplicado"] = False
        principal["copias"] = [x["ruta_relativa"] for x in orden[1:]]
        principal["usabilidad"] = usabilidad(principal)
        # Idioma recalculado sobre el cuerpo (corrige la estratificación falsa del abstract)
        principal["idioma_abstract"] = principal.get("idioma")
        idioma_cuerpo = idioma_del_cuerpo(principal)
        if idioma_cuerpo not in ("UNKNOWN",):
            principal["idioma"] = idioma_cuerpo
        unicos.append(principal)
        for x in orden[1:]:
            x["es_duplicado"] = True
            x["duplicado_de"] = principal["ruta_relativa"]
            duplicados.append(x)

    # ── Agregados sobre unicos y utilizables ──
    idiomas = Counter(r["idioma"] for r in unicos)
    utiles_por_tarea = {
        t: Counter(r["idioma"] for r in unicos if r["usabilidad"][t]) for t in ("T1", "T2", "T3")
    }
    sin_ninguna = [r for r in unicos if not any(r["usabilidad"].values())]
    flags = Counter(f for r in unicos for f in (r.get("flags") or []))

    lineas = []
    lineas.append("# COBERTURA DEL CORPUS V2 — Informe de Fase 2")
    lineas.append("")
    lineas.append(f"> Fusiona {len(ENTRADAS)} lotes: " + ", ".join(f"`{e.name}`" for e in ENTRADAS))
    lineas.append("> Motor: `backend/radar/text_extractor.py` corregido (secciones ES/PT/EN, corte de bibliografía, exclusión de tablas, rescate de abstract estructurado)")
    lineas.append("")
    lineas.append("## 1. Deduplicación por contenido (fuga en el split)")
    lineas.append("")
    lineas.append(f"- PDFs extraídos: **{len(registros)}**")
    lineas.append(f"- Artículos únicos por SHA-256: **{len(unicos)}**")
    lineas.append(f"- Copias duplicadas descartadas: **{len(duplicados)}** de {len(por_hash) - len([s for s, g in por_hash.items() if len(g) == 1])} archivos repetidos")
    lineas.append("")
    if duplicados:
        lineas.append("| Copia descartada | Duplicado de |")
        lineas.append("|---|---|")
        for d in sorted(duplicados, key=lambda x: x["duplicado_de"]):
            lineas.append(f"| `{d['ruta_relativa']}` | `{d['duplicado_de']}` |")
        lineas.append("")
    lineas.append("**Sin esta deduplicación, el mismo artículo puede caer en entrenamiento y prueba a la vez y las métricas quedan infladas.**")
    lineas.append("")
    lineas.append("## 2. Idioma (artículos únicos)")
    lineas.append("")
    lineas.append("| Idioma | n | % | Objetivo | Estado |")
    lineas.append("|---|---:|---:|---:|---|")
    total_u = len(unicos)
    for lang in ("ES", "PT", "EN", "UNCERTAIN"):
        n = idiomas.get(lang, 0)
        pct = n / total_u * 100 if total_u else 0
        obj = OBJETIVO.get(lang)
        if obj is None:
            estado = "—"
        elif lang == "EN":
            estado = "OK" if pct <= obj * 100 else f"EXCEDE (+{pct - obj * 100:.0f} pp)"
        else:
            estado = "OK" if pct >= obj * 100 else f"FALTA ({obj * 100 - pct:.0f} pp)"
        lineas.append(f"| {lang} | {n} | {pct:.1f} % | {'—' if obj is None else f'{obj*100:.0f} %'} | {estado} |")
    lineas.append("")
    lineas.append("## 3. Usabilidad por tarea (sobre únicos)")
    lineas.append("")
    lineas.append("| Tarea | Criterio | Utilizables | ES | PT | EN | Otros |")
    lineas.append("|---|---|---:|---:|---:|---:|---:|")
    criterios = {
        "T1": "abstract ≥ 500 chars",
        "T2": "métodos ≥ 800 chars, sin tabla/refs, no desproporcionado",
        "T3": "≥ 10 referencias y ≥ 8.000 chars de cuerpo",
    }
    for t in ("T1", "T2", "T3"):
        d = utiles_por_tarea[t]
        otros = d.get("UNCERTAIN", 0) + d.get("UNKNOWN", 0)
        lineas.append(f"| {t} | {criterios[t]} | **{sum(d.values())}** | {d.get('ES',0)} | {d.get('PT',0)} | {d.get('EN',0)} | {otros} |")
    lineas.append("")
    lineas.append(f"Artículos únicos sin ninguna tarea utilizable: **{len(sin_ninguna)}**")
    if sin_ninguna:
        for r in sin_ninguna:
            lineas.append(f"- `{r['ruta_relativa']}` — {', '.join(r.get('flags') or []) or 'sin flags'}")
    lineas.append("")
    lineas.append("## 4. Banderas de calidad (sobre únicos)")
    lineas.append("")
    lineas.append("| Bandera | n |")
    lineas.append("|---|---:|")
    for f, n in flags.most_common():
        lineas.append(f"| `{f}` | {n} |")
    lineas.append("")
    lineas.append("## 5. Lectura operativa")
    lineas.append("")
    lineas.append(f"1. El corpus útil para T1 es de {sum(utiles_por_tarea['T1'].values())} artículos únicos; para T2, {sum(utiles_por_tarea['T2'].values())}; para T3, {sum(utiles_por_tarea['T3'].values())}.")
    lineas.append("2. La deuda principal de idioma es el **portugués**, aunque el bloque PRISMA_JBI ya lo introduce en el corpus (antes era 0).")
    lineas.append("3. Las banderas `ABSTRACT_CORTO_O_AUSENTE` y `METHODS_CORTO_O_AUSENTE` señalan artículos cuyo layout no expone esas secciones; no se usarán para la tarea correspondiente en lugar de inventar contenido.")
    lineas.append("4. Los artículos marcados `POSIBLE_NO_ARTICULO` (memorias de congreso, erratas) quedan fuera del entrenamiento.")
    lineas.append("")

    (CORPUS_V2 / "COBERTURA_V2.md").write_text("\n".join(lineas), encoding="utf-8")
    (CORPUS_V2 / "inventario_unicos.json").write_text(
        json.dumps({"unicos": unicos, "duplicados": duplicados}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    print(f"Unicos: {len(unicos)} | duplicados: {len(duplicados)}")
    print(f"Idiomas: {dict(idiomas)}")
    for t in ("T1", "T2", "T3"):
        print(f"Utilizables {t}: {sum(utiles_por_tarea[t].values())} -> {dict(utiles_por_tarea[t])}")
    print(f"Sin ninguna tarea: {len(sin_ninguna)}")
    print(f"Informe: {CORPUS_V2 / 'COBERTURA_V2.md'}")


if __name__ == "__main__":
    main()
