"""Pruebas herméticas de la sonda de medición de Kev (`tools/kev_eval.py`).

Sin red: el transporte HTTP se sustituye por una función falsa. La métrica (kappa de Cohen)
y los lectores se comparten con `tools/calcular_kappa.py`, la fuente de verdad del Gate 2.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOOL = RAIZ / "tools" / "kev_eval.py"


def cargar_tool():
    spec = importlib.util.spec_from_file_location("kev_eval", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kev = cargar_tool()


def _respuesta(choice_a, choice_b="NO_DECLARADA", choice_c="REPORT", conf=0.9):
    """Respuesta con la forma real de Kev (/v1/systemone)."""
    return {"answers": {
        "A": {"type": "choice", "choice": choice_a, "confidence": conf, "probabilities": {}},
        "B": {"type": "choice", "choice": choice_b, "confidence": 0.5, "probabilities": {}},
        "C": {"type": "choice", "choice": choice_c, "confidence": conf, "probabilities": {}},
    }}


def test_construir_estado_recorta_el_contexto():
    fila = {"oracion": "Oración X (Autor, 2020).", "parrafo": "y" * 5000}
    estado = kev.construir_estado(fila)
    assert "Oración X (Autor, 2020)." in estado
    assert len(estado) < 5000 + 60
    assert estado.count("y") == kev.MAX_PARRAFO_CHARS


def test_construir_preguntas_son_tres_choices_independientes():
    preguntas = kev.construir_preguntas()
    assert set(preguntas) == {"A", "B", "C"}
    assert all(p["type"] == "choice" for p in preguntas.values())
    assert list(preguntas["A"]["criteria"]) == kev.ETIQUETAS_A
    assert list(preguntas["B"]["criteria"]) == kev.ETIQUETAS_B
    assert list(preguntas["C"]["criteria"]) == kev.ETIQUETAS_C


def test_construir_peticion_omite_model_si_va_vacio():
    fila = {"oracion": "x", "parrafo": "y"}
    assert "model" not in kev.construir_peticion(fila, "")
    assert kev.construir_peticion(fila, "kev-latest")["model"] == "kev-latest"


def test_parse_respuesta_normaliza_y_descarta_lo_que_no_es_choice():
    crudo = {
        "answers": {
            "A": {"type": "choice", "choice": "support", "confidence": 0.8},
            "B": {"type": "noul", "noul": 0.7},
            "C": {"type": "choice", "confidence": 0.6},  # sin etiqueta -> fuera
        }
    }
    r = kev.parse_respuesta(crudo)
    assert r["A"] == {"etiqueta": "SUPPORT", "confianza": 0.8, "probabilidades": {}}
    assert "B" not in r and "C" not in r


def test_parse_respuesta_usa_max_probability_si_falta_confidence():
    crudo = {"answers": {"A": {"type": "choice", "choice": "NEUTRAL",
                               "probabilities": {"SUPPORT": 0.2, "NEUTRAL": 0.6, "CONFLICT": 0.2}}}}
    assert kev.parse_respuesta(crudo)["A"]["confianza"] == 0.6


def test_parse_respuesta_prefiere_la_probabilidad_de_la_respuesta():
    # Laya: `confidence` es 1 - entropía normalizada; la probabilidad de la respuesta va aparte.
    laya = {"answers": {"A": {"type": "choice", "choice": "NEUTRAL", "confidence": 0.31,
                              "answer_confidence": 0.62,
                              "probabilities": {"NEUTRAL": 0.62, "SUPPORT": 0.2, "CONFLICT": 0.18}}}}
    assert kev.parse_respuesta(laya)["A"]["confianza"] == 0.62

    # Kev/Jev-Style: sin `answer_confidence`, manda max(probabilities), no la fórmula de confidence.
    kev_style = {"answers": {"A": {"type": "choice", "choice": "NEUTRAL", "confidence": 0.21,
                                   "probabilities": {"NEUTRAL": 0.47, "SUPPORT": 0.28, "CONFLICT": 0.25}}}}
    assert kev.parse_respuesta(kev_style)["A"]["confianza"] == 0.47


def test_metricas_por_umbral_miden_cobertura_y_presupuesto():
    registros = [
        {"correcto": True, "confianza": 0.95},
        {"correcto": True, "confianza": 0.85},
        {"correcto": False, "confianza": 0.65},
    ]
    m = kev.metricas_por_umbral(registros)
    assert m["0.9"]["n_cubiertas"] == 1 and m["0.9"]["exactitud"] == 1.0
    assert m["0.8"]["n_cubiertas"] == 2 and m["0.8"]["errores"] == 0
    assert m["0.6"]["n_cubiertas"] == 3 and m["0.6"]["exactitud"] == round(2 / 3, 4)
    assert m["0.6"]["cumple_presupuesto_5pct"] is False


def test_evaluar_calcula_kappa_contra_humano_y_salta_vacios():
    filas = [
        {"control_id": "C-1", "idioma": "ES", "oracion": "uno", "parrafo": "p1"},
        {"control_id": "C-2", "idioma": "ES", "oracion": "dos", "parrafo": "p2"},
        {"control_id": "C-3", "idioma": "ES", "oracion": "tres", "parrafo": "p3"},
    ]
    humano = {
        "C-1": {"A_postura": "NEUTRAL", "B_certeza": "AMBIGUO", "C_funcion": "REPORT"},
        "C-2": {"A_postura": "SUPPORT", "B_certeza": "", "C_funcion": "REPORT"},
        "C-3": {"A_postura": "NEUTRAL", "B_certeza": "", "C_funcion": "REPORT"},
    }

    def transporte(_peticion):
        # A acierta en C-1 y C-3 (NEUTRAL), falla en C-2 (Kev dice NEUTRAL, humano SUPPORT)
        return _respuesta("NEUTRAL", conf=0.9)

    resumen = kev.evaluar(transporte, filas, humano, "kev-test", baseline={"A": 0.1, "B": -0.04, "C": 0.37})

    a = resumen["ejes"]["A"]
    assert a["n"] == 3
    assert a["po"] == round(2 / 3, 4)
    assert a["kappa"] is not None and a["baseline_motor_kappa"] == 0.1
    assert a["delta_vs_motor"] == round(a["kappa"] - 0.1, 4)
    assert [d["id"] for d in a["desacuerdos"]] == ["C-2"]

    # B: el humano marcó AMBIGUO en C-1 y vacío en C-2/C-3 -> sin pares, pero se cuenta el ambiguo
    assert resumen["ejes"]["B"]["n"] == 0
    assert resumen["ejes"]["B"]["humano_ambiguo"] == 1

    # C: 2 coincidencias exactas -> kappa 1.0
    assert resumen["ejes"]["C"]["kappa"] == 1.0


def test_evaluar_declara_fallos_de_transporte_sin_inventar():
    filas = [{"control_id": "C-1", "idioma": "ES", "oracion": "x", "parrafo": "y"}]
    humano = {"C-1": {"A_postura": "NEUTRAL", "B_certeza": "", "C_funcion": ""}}

    def transporte(_peticion):
        raise RuntimeError("boom de red")

    resumen = kev.evaluar(transporte, filas, humano, "kev-test", baseline={})
    assert len(resumen["errores_transporte"]) == 1
    assert resumen["ejes"]["A"]["kappa"] is None  # un fallo no se convierte en acierto ni en azar


def test_baseline_motor_lee_el_gate2_real():
    baseline = kev._baseline_motor(kev.D / "gate2_resultado.json")
    # Si el Gate 2 existe en el repo, sus tres ejes de stance deben aparecer.
    if baseline:
        assert set(baseline) == {"A", "B", "C"}
