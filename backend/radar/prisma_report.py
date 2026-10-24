"""Checklist PRISMA 2020 (27 ítems) e informe final de una revisión.

Fuente normativa: Page MJ et al. «Declaración PRISMA 2020: una guía actualizada para la
publicación de revisiones sistemáticas». Rev Esp Cardiol. 2021;74(9):790-799
(`docs/referencias/PRISMA_2020_es.pdf`).

Principio de diseño: el informe **rellena automáticamente** lo que la plataforma puede derivar
de sus propios datos (búsqueda, cribado, charting) y **declara explícitamente** lo que exige una
decisión del investigador o lo que no aplica. Nunca inventa un valor.
"""
from __future__ import annotations

import sqlite3
from datetime import date

# Los 27 ítems de la lista de verificación PRISMA 2020 (con subítems).
PRISMA_2020_ITEMS: list[dict[str, str]] = [
    {"id": "1", "seccion": "Título", "item": "Identifique la publicación como una revisión sistemática."},
    {"id": "2", "seccion": "Resumen", "item": "Resumen estructurado (ver lista de verificación PRISMA 2020 para resúmenes)."},
    {"id": "3", "seccion": "Introducción", "item": "Describa la justificación de la revisión en el contexto del conocimiento existente."},
    {"id": "4", "seccion": "Introducción", "item": "Proporcione una declaración explícita de los objetivos o las preguntas que aborda la revisión."},
    {"id": "5", "seccion": "Métodos", "item": "Especifique los criterios de inclusión y exclusión y cómo se agruparon los estudios para la síntesis."},
    {"id": "6", "seccion": "Métodos", "item": "Especifique todas las bases de datos, registros, sitios web y otros recursos consultados, y la fecha de la última búsqueda."},
    {"id": "7", "seccion": "Métodos", "item": "Presente las estrategias de búsqueda completas de todas las bases de datos, con filtros y límites."},
    {"id": "8", "seccion": "Métodos", "item": "Especifique los métodos de selección, cuántos revisores cribaron y si hubo herramientas de automatización."},
    {"id": "9", "seccion": "Métodos", "item": "Indique los métodos de extracción de datos, cuántos revisores extrajeron y si hubo automatización."},
    {"id": "10a", "seccion": "Métodos", "item": "Enumere y defina todos los desenlaces para los que se buscaron datos."},
    {"id": "10b", "seccion": "Métodos", "item": "Enumere y defina las demás variables buscadas y los supuestos sobre información ausente."},
    {"id": "11", "seccion": "Métodos", "item": "Especifique los métodos de evaluación del riesgo de sesgo de los estudios incluidos."},
    {"id": "12", "seccion": "Métodos", "item": "Especifique, para cada desenlace, las medidas del efecto utilizadas."},
    {"id": "13a", "seccion": "Métodos", "item": "Describa el proceso para decidir qué estudios eran elegibles para cada síntesis."},
    {"id": "13b", "seccion": "Métodos", "item": "Describa los métodos de preparación de los datos para su presentación o síntesis."},
    {"id": "13c", "seccion": "Métodos", "item": "Describa los métodos para tabular o presentar visualmente los resultados."},
    {"id": "13d", "seccion": "Métodos", "item": "Describa los métodos de síntesis y su justificación (modelos, heterogeneidad, software)."},
    {"id": "13e", "seccion": "Métodos", "item": "Describa los métodos para explorar las causas de heterogeneidad."},
    {"id": "13f", "seccion": "Métodos", "item": "Describa los análisis de sensibilidad realizados."},
    {"id": "14", "seccion": "Métodos", "item": "Describa los métodos para evaluar el riesgo de sesgo por resultados faltantes."},
    {"id": "15", "seccion": "Métodos", "item": "Describa los métodos para evaluar la certeza (o confianza) en el cuerpo de la evidencia."},
    {"id": "16a", "seccion": "Resultados", "item": "Describa los resultados de la búsqueda y selección, del número de registros identificados al de estudios incluidos (diagrama de flujo)."},
    {"id": "16b", "seccion": "Resultados", "item": "Cite los estudios que aparentemente cumplían los criterios pero fueron excluidos, y explique por qué."},
    {"id": "17", "seccion": "Resultados", "item": "Cite cada estudio incluido y presente sus características."},
    {"id": "18", "seccion": "Resultados", "item": "Presente las evaluaciones del riesgo de sesgo de cada estudio incluido."},
    {"id": "19", "seccion": "Resultados", "item": "Presente, para todos los desenlaces y estudios, los estadísticos de resumen y las estimaciones del efecto."},
    {"id": "20a", "seccion": "Resultados", "item": "Resuma las características y el riesgo de sesgo de los estudios que contribuyen a cada síntesis."},
    {"id": "20b", "seccion": "Resultados", "item": "Presente los resultados de todas las síntesis estadísticas realizadas."},
    {"id": "20c", "seccion": "Resultados", "item": "Presente los resultados de las investigaciones sobre causas de heterogeneidad."},
    {"id": "20d", "seccion": "Resultados", "item": "Presente los resultados de los análisis de sensibilidad."},
    {"id": "21", "seccion": "Resultados", "item": "Presente las evaluaciones del riesgo de sesgo por resultados faltantes para cada síntesis."},
    {"id": "22", "seccion": "Resultados", "item": "Presente las evaluaciones de la certeza en el cuerpo de la evidencia para cada desenlace."},
    {"id": "23a", "seccion": "Discusión", "item": "Proporcione una interpretación general de los resultados en el contexto de otras evidencias."},
    {"id": "23b", "seccion": "Discusión", "item": "Argumente las limitaciones de la evidencia incluida en la revisión."},
    {"id": "23c", "seccion": "Discusión", "item": "Argumente las limitaciones de los procesos de revisión utilizados."},
    {"id": "23d", "seccion": "Discusión", "item": "Argumente las implicaciones para la práctica, las políticas y las futuras investigaciones."},
    {"id": "24a", "seccion": "Otra información", "item": "Proporcione el registro de la revisión (nombre y número) o declare que no fue registrada."},
    {"id": "24b", "seccion": "Otra información", "item": "Indique dónde se puede acceder al protocolo, o declare que no se redactó."},
    {"id": "24c", "seccion": "Otra información", "item": "Describa y explique cualquier enmienda al registro o al protocolo."},
    {"id": "25", "seccion": "Otra información", "item": "Describa las fuentes de apoyo financiero o no financiero y el papel de los financiadores."},
    {"id": "26", "seccion": "Otra información", "item": "Declare los conflictos de intereses de los autores de la revisión."},
    {"id": "27", "seccion": "Otra información", "item": "Especifique qué materiales (plantillas, datos, código) están disponibles públicamente y dónde."},
]

# Estados posibles de un ítem.
AUTO = "auto"          # la plataforma lo rellena desde sus datos
DECLARADO = "declarado"  # se declara por defecto y el investigador confirma
MANUAL = "manual"      # requiere que el investigador lo redacte


def _fuentes_y_fechas(busquedas: list[dict]) -> dict:
    """Última fecha de búsqueda por fuente y número de registros identificados (ítem 6)."""
    por_fuente: dict[str, dict] = {}
    for b in busquedas:
        fuente = b.get("source") or "desconocida"
        fecha = b.get("searched_at") or ""
        entrada = por_fuente.setdefault(fuente, {"ultima_fecha": "", "registros": 0})
        entrada["registros"] += int(b.get("records_identified") or 0)
        if fecha > entrada["ultima_fecha"]:
            entrada["ultima_fecha"] = fecha
    return por_fuente


def build_checklist(conn: sqlite3.Connection, protocol_id: int,
                    owner_id: str | None = None) -> dict:
    """Devuelve los 27 ítems PRISMA 2020 con su estado y la evidencia disponible."""
    from . import db

    protocol = db.get_protocol(conn, protocol_id, owner_id=owner_id) or {}
    busquedas = db.list_protocol_searches(conn, protocol_id, owner_id=owner_id)
    flow = db.screening_flow_counts(conn, protocol_id, owner_id=owner_id)
    p = flow.get("prisma_2020", {})
    cribado = p.get("cribado", {})
    incluidos = p.get("incluidos", {})
    chartings = db.list_charting(conn, protocol_id, limit=500, owner_id=owner_id)
    screenings = db.list_screenings(conn, protocol_id, limit=2000, owner_id=owner_id)

    fuentes = _fuentes_y_fechas(busquedas)
    revisores = sorted({s.get("screened_by") for s in screenings if s.get("screened_by")})
    tiene_ft = bool(p.get("segunda_etapa_implementada"))

    # Relleno automático por ítem. Lo que no está aquí es `manual`.
    auto: dict[str, tuple[str, object]] = {
        "4": (AUTO, protocol.get("research_question") or ""),
        "5": (AUTO, {
            "inclusion": protocol.get("inclusion_criteria"),
            "exclusion": protocol.get("exclusion_criteria"),
            "framework": protocol.get("framework"),
        }),
        "6": (AUTO, fuentes),
        "7": (AUTO, [
            {"fuente": b.get("source"), "consulta": b.get("query"),
             "desde": b.get("year_from"), "hasta": b.get("year_to"),
             "fecha": b.get("searched_at")}
            for b in busquedas
        ]),
        "8": (AUTO, {"revisores": revisores, "automatizacion": "ranker de aprendizaje activo"}),
        "9": (AUTO, {"extractor": "charting JBI PCC", "filas_extraidas": len(chartings)}),
        "16a": (AUTO, {
            "identificados": p.get("identificacion", {}).get("total"),
            "duplicados_removidos": p.get("removidos_antes_del_cribado", {}).get("duplicados"),
            "registros_unicos": cribado.get("registros_unicos"),
            "registros_cribados": cribado.get("registros_cribados"),
            "registros_excluidos": cribado.get("registros_excluidos"),
            "informes_buscados": cribado.get("informes_buscados"),
            "informes_no_recuperados": cribado.get("informes_no_recuperados"),
            "informes_evaluados": cribado.get("informes_evaluados"),
            "informes_excluidos": cribado.get("informes_excluidos"),
            "incluidos": incluidos.get("estudios"),
            "segunda_etapa_implementada": tiene_ft,
        }),
        "16b": (AUTO, cribado.get("motivos_exclusion") or {}),
        "17": (AUTO, {"estudios_incluidos": incluidos.get("estudios"),
                      "con_charting": len(chartings)}),
        "24b": (AUTO, {"protocolo_id": protocol_id, "titulo": protocol.get("title"),
                       "accesible_en": f"/api/review/protocol/{protocol_id}"}),
        "27": (AUTO, {"exportacion": "CSV / RIS / BibTeX por protocolo",
                      "datos_extraidos": len(chartings)}),
    }
    declarado: dict[str, object] = {
        "24a": "La revisión no ha sido registrada en un registro público (a confirmar por el investigador).",
        "24c": "Sin enmiendas al protocolo.",
    }

    items = []
    for base in PRISMA_2020_ITEMS:
        item = dict(base)
        if item["id"] in auto:
            item["estado"], item["evidencia"] = auto[item["id"]]
        elif item["id"] in declarado:
            item["estado"], item["evidencia"] = DECLARADO, declarado[item["id"]]
        else:
            item["estado"], item["evidencia"] = MANUAL, None
        items.append(item)

    conteo = {AUTO: 0, DECLARADO: 0, MANUAL: 0}
    for it in items:
        conteo[it["estado"]] = conteo.get(it["estado"], 0) + 1

    return {
        "protocol_id": protocol_id,
        "titulo": protocol.get("title"),
        "items": items,
        "resumen": conteo,
        "total": len(items),
    }


def _fmt(valor) -> str:
    if valor is None or valor == "":
        return "—"
    if isinstance(valor, dict):
        return "; ".join(f"{k}: {_fmt(v)}" for k, v in valor.items() if v not in (None, "", [], {}))
    if isinstance(valor, list):
        return " | ".join(_fmt(v) for v in valor) if valor else "—"
    return str(valor)


def build_report(conn: sqlite3.Connection, protocol_id: int,
                 owner_id: str | None = None) -> str:
    """Informe final en Markdown: protocolo, búsquedas, flujo PRISMA y checklist."""
    from . import db

    protocol = db.get_protocol(conn, protocol_id, owner_id=owner_id) or {}
    flow = db.screening_flow_counts(conn, protocol_id, owner_id=owner_id)
    checklist = build_checklist(conn, protocol_id, owner_id=owner_id)
    busquedas = db.list_protocol_searches(conn, protocol_id, owner_id=owner_id)
    p = flow.get("prisma_2020", {})
    idn = p.get("identificacion", {})
    rem = p.get("removidos_antes_del_cribado", {})
    cri = p.get("cribado", {})
    inc = p.get("incluidos", {})

    lineas = [
        f"# Informe de revisión — {protocol.get('title') or 'Sin título'}",
        "",
        f"- **Pregunta de investigación:** {protocol.get('research_question') or '—'}",
        f"- **Marco:** {protocol.get('framework') or '—'}",
        f"- **Estado:** {protocol.get('status') or '—'}",
        f"- **Fecha del informe:** {date.today().isoformat()}",
        "",
        "## 1. Identificación y estrategia de búsqueda (ítems 6 y 7)",
        "",
        "| Fuente | Consulta | Desde | Hasta | Registros | Fecha |",
        "| :--- | :--- | :--- | :--- | ---: | :--- |",
    ]
    if busquedas:
        for b in busquedas:
            lineas.append(
                f"| {b.get('source') or '—'} | {_fmt(b.get('query'))} | {b.get('year_from') or '—'} "
                f"| {b.get('year_to') or '—'} | {b.get('records_identified') or 0} | {b.get('searched_at') or '—'} |"
            )
    else:
        lineas.append("| — | — | — | — | 0 | — |")

    lineas += [
        "",
        "## 2. Diagrama de flujo PRISMA 2020 (ítem 16a)",
        "",
        f"- Registros identificados en bases de datos: **{idn.get('total', 0)}**",
    ]
    for fuente, n in (idn.get("bases_de_datos") or {}).items():
        lineas.append(f"  - {fuente}: {n}")
    lineas += [
        f"- Duplicados removidos antes del cribado: **{rem.get('duplicados', 0)}**",
        f"- Registros únicos cribados: **{cri.get('registros_unicos', 0)}**",
        f"- Registros excluidos (título/resumen): **{cri.get('registros_excluidos', 0)}**",
    ]
    if p.get("segunda_etapa_implementada"):
        lineas += [
            f"- Informes buscados para recuperación: **{_fmt(cri.get('informes_buscados'))}**",
            f"- Informes no recuperados: **{_fmt(cri.get('informes_no_recuperados'))}**",
            f"- Informes evaluados para elegibilidad: **{_fmt(cri.get('informes_evaluados'))}**",
            f"- Informes excluidos (texto completo): **{_fmt(cri.get('informes_excluidos'))}**",
        ]
    else:
        lineas.append("- Segunda etapa (texto completo): **no iniciada** (protocolo de una etapa).")
    lineas += [f"- **Estudios incluidos en la síntesis: {inc.get('estudios', 0)}**", ""]

    motivos = cri.get("motivos_exclusion") or {}
    if motivos:
        lineas += ["### Motivos de exclusión (ítem 16b)", ""]
        for razon, n in motivos.items():
            lineas.append(f"- {razon}: {n}")
        lineas.append("")

    lineas += ["## 3. Lista de verificación PRISMA 2020 (27 ítems)", "",
               f"Rellenados automáticamente: {checklist['resumen'].get(AUTO, 0)} · "
               f"Declarados: {checklist['resumen'].get(DECLARADO, 0)} · "
               f"Manuales (requieren redacción): {checklist['resumen'].get(MANUAL, 0)}", "",
               "| # | Sección | Ítem | Estado | Evidencia |",
               "| :--- | :--- | :--- | :--- | :--- |"]
    for it in checklist["items"]:
        lineas.append(f"| {it['id']} | {it['seccion']} | {it['item']} | {it['estado']} | {_fmt(it['evidencia'])} |")

    lineas += [
        "",
        "## 4. Limitaciones declaradas de la plataforma",
        "",
        "- La búsqueda en vivo cubre OpenAlex, OpenAIRE Graph, Dialnet e importaciones propias; "
        "**no cubre Scopus ni Web of Science** (bases cerradas). Su exportación puede importarse "
        "vía CSV/RIS y queda registrada como fuente de identificación.",
        "- Los ítems marcados como `manual` requieren redacción del investigador: la plataforma no "
        "los inventa.",
        "",
    ]
    return "\n".join(lineas)
