import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _modulo_evaluar():
    spec = importlib.util.spec_from_file_location("evaluar_llm", RAIZ / "scripts" / "evaluar_llm.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _casos():
    return [
        {"id": "T01", "categoria": "precio", "variante": "formal", "autor": "equipo",
         "mensajes": ["cuanto vale la camiseta oversize negra?"], "espera": ["59.900"], "prohibe": [],
         "traspaso": False, "pedido": None},
        {"id": "T02", "categoria": "faq", "variante": "abreviado", "autor": "equipo",
         "mensajes": ["cual es el horario de atencion"], "espera": ["8:00"], "prohibe": [],
         "traspaso": False, "pedido": None},
    ]


def test_casos_json_se_cargan_y_se_evaluan(tmp_path):
    ev = _modulo_evaluar()
    ruta = tmp_path / "casos.json"
    ruta.write_text(json.dumps(_casos(), ensure_ascii=False), encoding="utf-8")
    casos, pedidos, extras = ev.cargar_casos(str(ruta))
    res = ev.correr(ev.build_provider("reglas"), "reglas", None, casos, pedidos, extras)
    assert res["resumen"]["aciertos"] == 2
    assert {f["variante"] for f in res["casos"]} == {"formal", "abreviado"}


def test_casos_json_rechaza_identificadores_repetidos(tmp_path):
    ev = _modulo_evaluar()
    repetidos = _casos() + [dict(_casos()[0])]
    ruta = tmp_path / "casos.json"
    ruta.write_text(json.dumps(repetidos, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AssertionError):
        ev.cargar_casos(str(ruta))