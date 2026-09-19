"""Configuración común de la suite de pruebas de Thinkuy.

Dos garantías:

1. **Importabilidad:** tanto `radar.*` (raíz `backend/`) como `backend.radar.*`
   (raíz del proyecto) resuelven, sin depender del directorio desde el que se
   invoque pytest.
2. **Aislamiento de datos:** `THINKUY_DATA_DIR` apunta a un directorio temporal,
   de modo que las pruebas **nunca escriben en el catálogo real del investigador**
   (regla de oro de `AGENTS.md`: una herramienta de verificación no debe poder
   alterar los datos de producción). Se respeta `THINKUY_DATA_DIR` si ya venía
   definido por el entorno.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

for _path in (str(PROJECT_ROOT), str(BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_SRC_DATA = PROJECT_ROOT / "data"
_TMP_DATA: Path | None = None
if not os.environ.get("THINKUY_DATA_DIR"):
    _TMP_DATA = Path(tempfile.mkdtemp(prefix="thinkuy_test_data_"))
    # Se copian los catálogos para que las pruebas que leen datos reales sigan
    # funcionando, pero TODA escritura ocurre en la copia temporal.
    if _SRC_DATA.is_dir():
        for _src in sorted(_SRC_DATA.glob("*.db")):
            try:
                shutil.copy2(_src, _TMP_DATA / _src.name)
            except OSError:
                pass
    os.environ["THINKUY_DATA_DIR"] = str(_TMP_DATA)


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    if _TMP_DATA is not None:
        shutil.rmtree(_TMP_DATA, ignore_errors=True)
