"""Gestión de conexiones SQLite para el catálogo Thinkuy."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .. import config


def now_iso() -> str:
    """Devuelve la marca de tiempo UTC actual en formato ISO 8601 (segundos)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _active_field_id() -> str | None:
    """Id del campo activo (perfil cargado en runtime), o None si no se puede leer."""
    try:
        from .. import profile
        return profile.field_profile.id
    except Exception:
        return None


def db_path_for_field(field_id: str | None = None) -> Path:
    """Resuelve la ruta de la DB para un campo SIN mutar estado global."""
    if field_id and field_id != config.THINKUY_FIELD:
        return config.DATA_DIR / f"radar_{field_id}.db"
    return config.DB_PATH


def connect_for_field(field_id: str | None = None) -> sqlite3.Connection:
    """Abre conexión a la DB del campo indicado."""
    return connect(db_path_for_field(field_id))


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Abre una conexión SQLite en modo WAL con foreign keys activadas.

    Sin ruta explícita, usa la DB del **campo activo**: cambiar de campo en runtime
    (`POST /api/field/set`) redirige también las lecturas, no solo la inicialización.
    """
    if db_path is None:
        db_path = db_path_for_field(_active_field_id())
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
