"""Pruebas del proveedor compatible con OpenAI (NVIDIA / Ollama) contra un servidor simulado,
y de la validacion ampliada de precio, stock y tallas (RNF-05)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.llm import LLMRequest, LLMResult, MeteredProvider, OpenAICompatProvider, _extraer_json
from app.veracidad import verificar

PRODUCTOS = [
    {"id": 1, "nombre": "Camiseta oversize negra", "categoria": "camiseta", "precio_cop": 59900,
     "tallas": ["S", "M", "L", "XL"], "stock": 14, "score": 2.0},
    {"id": 2, "nombre": "Gorra clásica negra", "categoria": "gorra", "precio_cop": 34900,
     "tallas": ["unica"], "stock": 3, "score": 0.0},
]


def _req(msg="cuanto vale la camiseta?"):
    return LLMRequest("Moda Caribe", "cercano", msg, [], PRODUCTOS, [], {})


class _Fake(BaseHTTPRequestHandler):
    contenido = ""
    visto: dict = {}

    def do_POST(self):  # noqa: N802
        n = int(self.headers["Content-Length"])
        _Fake.visto = {"path": self.path, "auth": self.headers.get("Authorization"),
                       "body": json.loads(self.rfile.read(n))}
        out = json.dumps({"choices": [{"message": {"content": _Fake.contenido}}],
                          "usage": {"prompt_tokens": 120, "completion_tokens": 30}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_llm():
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_proveedor_compat_parsea_json_y_mide_tokens(fake_llm):
    _Fake.contenido = ("<think>pienso</think>```json\n"
                       '{"intencion":"consulta","respuesta":"Camiseta oversize negra: $59.900.",'
                       '"borrador":{},"pedido_listo":false,"requiere_humano":false,"motivo":null,'
                       '"sin_informacion":false}\n```')
    prov = MeteredProvider(OpenAICompatProvider(fake_llm, "clave-x", "modelo-x"))
    res = prov.generate(_req())
    assert res.intencion == "consulta" and "$59.900" in res.respuesta
    assert _Fake.visto["path"] == "/v1/chat/completions"
    assert _Fake.visto["auth"] == "Bearer clave-x"
    assert _Fake.visto["body"]["temperature"] == 0
    assert prov.calls[0]["prompt_tokens"] == 120 and prov.calls[0]["completion_tokens"] == 30


def test_proveedor_compat_falla_con_texto_sin_json(fake_llm):
    _Fake.contenido = "Lo siento, no puedo."
    prov = MeteredProvider(OpenAICompatProvider(fake_llm, "k", "m"))
    with pytest.raises(ValueError):
        prov.generate(_req())
    assert prov.calls[0]["ok"] is False


def test_extraer_json_con_texto_alrededor():
    assert _extraer_json('Claro: {"a": 1} listo')["a"] == 1


@pytest.mark.parametrize("texto,problema", [
    ("Camiseta oversize negra: $59.900. Hay 14 unidades disponibles.", None),
    ("Gorra clásica negra: $34.900. Quedan pocas unidades (3).", None),
    ("La camiseta cuesta $49.900.", "precio_no_catalogo:49900"),
    ("Camiseta oversize negra. Hay 20 unidades disponibles.", "stock_no_coincide:20"),
    ("Camiseta oversize negra. Tallas: S, M, L, XXL.", "talla_inexistente:XXL"),
])
def test_verificar_precio_stock_talla(texto, problema):
    v = verificar(texto, PRODUCTOS)
    assert v.ok == (problema is None)
    if problema:
        assert problema in v.problemas


def test_stock_inventado_se_traspasa_a_una_persona(make_srv):
    class Mentiroso:
        def generate(self, req):
            return LLMResult("consulta", "Camiseta oversize negra: $59.900. Hay 99 unidades disponibles.")
    h = make_srv(llm=Mentiroso())
    r = h.webhook("cuanto vale la camiseta oversize negra?")
    assert r["estado"] == "traspasado" and r["motivo"] == "respuesta_no_verificada"


def test_negar_una_talla_no_se_marca_como_inventada():
    ok = verificar("La talla 40 no está disponible para Jean slim azul. Tallas: S, M, L, XL.", PRODUCTOS)
    assert ok.ok
    mal = verificar("Tenemos la camiseta en talla XXL. Tallas: S, M, L, XXL.", PRODUCTOS)
    assert not mal.ok and "talla_inexistente:XXL" in mal.problemas


@pytest.mark.parametrize("texto,esperado", [
    ("El precio es $59,900 COP.", [59900]),
    ("Cuesta $129.900.", [129900]),
    ("El precio es COP 39,900.", [39900]),
    ("Son 34.900 COP.", [34900]),
    ("Total $119,800.00", [119800]),
    ("Tallas 28, 30, 32. Hay 14 unidades.", []),
])
def test_precios_con_cualquier_separador_de_miles(texto, esperado):
    from app.textutil import precios_en_texto
    assert precios_en_texto(texto) == esperado


def test_respuesta_con_coma_de_miles_correcta_no_se_bloquea():
    assert verificar("El precio de la camiseta oversize negra es de $59,900 COP.", PRODUCTOS).ok
    assert not verificar("El precio es de $49,900 COP.", PRODUCTOS).ok
