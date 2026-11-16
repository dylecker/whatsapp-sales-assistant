from types import SimpleNamespace

from app.llm import _contexto


def _req():
    return SimpleNamespace(
        negocio_nombre="Moda Caribe", tono="cercano", mensaje="cuanto cuesta la camiseta?",
        historial=[], borrador={},
        productos=[{"id": 1, "nombre": "Camiseta", "categoria": "ropa", "precio_cop": 59900,
                    "tallas": ["M"], "stock": {"M": 3}}],
        faqs=[{"tema": "envios", "respuesta": "Enviamos a todo el pais"}],
    )


def test_con_recuperacion_incluye_catalogo_y_faq(monkeypatch):
    monkeypatch.delenv("WSA_SIN_RECUPERACION", raising=False)
    ctx = _contexto(_req())
    assert ctx["productos"] and ctx["preguntas_frecuentes"]


def test_b1_sin_recuperacion_no_envia_catalogo_ni_faq(monkeypatch):
    monkeypatch.setenv("WSA_SIN_RECUPERACION", "1")
    ctx = _contexto(_req())
    assert ctx["productos"] == [] and ctx["preguntas_frecuentes"] == []
    assert "Camiseta" not in str(ctx) and "Enviamos" not in str(ctx)
