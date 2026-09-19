"""Corrige el ejemplo de mojibake incrustado por error en cuatro documentos.

Al documentar que el dataset NO tenia mojibake, se incrusto el ejemplo corrupto
(secuencia de dos U+FFFD). Este corrector reescribe esos bytes como texto ASCII
inequivoco y verifica que no quede ninguno.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FFFD = chr(0xFFFD)

ARCHIVOS = [
    "BITACORA_METODOLOGICA_HALLAZGOS.md",
    "docs/BITACORA_METODOLOGICA_HALLAZGOS.md",
    "data/auditorias_y_benchmarks/INFORME_FORENSE_DATASET_V3.md",
    "data/_LEGACY/MANIFIESTO.md",
]

OBJETIVO = '"S' + FFFD * 2 + 'ntesis_Review"'
REEMPLAZO = '"S[U+FFFD][U+FFFD]ntesis_Review"'


def main() -> None:
    for rel in ARCHIVOS:
        p = RAIZ / rel
        if not p.exists():
            print(f"AUSENTE  {rel}")
            continue
        t = p.read_text(encoding="utf-8")
        antes = t.count(FFFD)
        t = t.replace(OBJETIVO, REEMPLAZO)
        t = t.replace(FFFD, "[U+FFFD]")
        p.write_text(t, encoding="utf-8", newline="")
        despues = p.read_text(encoding="utf-8").count(FFFD)
        print(f"{rel:62} antes={antes}  despues={despues}")


if __name__ == "__main__":
    main()
