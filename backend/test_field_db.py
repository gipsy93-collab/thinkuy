"""El campo activo debe mandar sobre las lecturas, no solo sobre la inicialización.

Regresión del bug medido: `POST /api/field/set` inicializaba `radar_<campo>.db`,
pero `db.connect()` seguía abriendo `config.DB_PATH`, de modo que cambiar de campo
no cambiaba los datos leídos.
"""
from pathlib import Path

from radar import config, db, profile


def _db_name(conn) -> str:
    return Path(conn.execute("PRAGMA database_list").fetchone()[2]).name


def test_connect_usa_la_db_del_campo_activo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "radar.db")

    monkeypatch.setattr(profile, "field_profile", profile.FieldProfile(id="general", name="General"))
    assert _db_name(db.connect()) == "radar.db"

    monkeypatch.setattr(profile, "field_profile", profile.FieldProfile(id="salud_publica", name="Salud"))
    assert _db_name(db.connect()) == "radar_salud_publica.db"


def test_ruta_explicita_gana(tmp_path):
    explicit = tmp_path / "explicita.db"
    assert _db_name(db.connect(explicit)) == "explicita.db"
