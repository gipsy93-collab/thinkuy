"""Pruebas unitarias para extracción de tablas y figuras desde PDFs (text_extractor.py)."""
import os
import tempfile

import pymupdf as fitz
from radar import text_extractor


def test_extract_paper_to_markdown_with_tables():
    # Crear un PDF sintético temporal con fitz
    doc = fitz.open()
    page = doc.new_page()

    # Escribir texto de sección
    page.insert_text((50, 50), "Introducción a la Ciencia Abierta\nEste es un texto introductorio.")
    page.insert_text((50, 100), "Tabla 1: Distribución de publicaciones en América Latina")

    # Dibujar una tabla rectangular
    rect = fitz.Rect(50, 120, 400, 220)
    page.draw_rect(rect)
    page.draw_line((50, 150), (400, 150))
    page.draw_line((200, 120), (200, 220))
    page.insert_text((60, 140), "País")
    page.insert_text((210, 140), "Artículos")
    page.insert_text((60, 180), "Colombia")
    page.insert_text((210, 180), "450")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        doc.save(tmp_path)
        doc.close()

        res = text_extractor.extract_paper_to_markdown(tmp_path)
        assert res is not None
        assert "full_text" in res
        assert "tables" in res
        assert "figures" in res
        assert "tables_count" in res
        assert "figures_count" in res
        assert res["page_count"] == 1
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
