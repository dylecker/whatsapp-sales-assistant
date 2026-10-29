"""Recuperacion de contexto (la R de RAG).

El prototipo usa busqueda lexica sobre el catalogo y las preguntas frecuentes del
negocio. La interfaz `Retriever` permite reemplazarla por busqueda vectorial
(embeddings + pgvector) sin tocar el resto del flujo.
"""
from __future__ import annotations

import json
from typing import Protocol

from .textutil import tokens


class Retriever(Protocol):
    def productos(self, negocio_id: int, consulta: str, forzar_ids: list[int] | None = None) -> list[dict]: ...
    def faqs(self, negocio_id: int, consulta: str) -> list[dict]: ...


def _producto_dict(row, score: float, forzado: bool = False) -> dict:
    d = dict(row)
    d["tallas"] = json.loads(d["tallas"] or "[]")
    d["score"] = score
    d["forzado"] = forzado
    return d


class LexicalRetriever:
    def __init__(self, conn):
        self.conn = conn

    def productos(self, negocio_id: int, consulta: str, forzar_ids: list[int] | None = None) -> list[dict]:
        q = set(tokens(consulta))
        rows = self.conn.execute(
            "SELECT * FROM producto WHERE negocio_id = ? AND activo = 1", (negocio_id,)).fetchall()
        puntuados = []
        for r in rows:
            nombre = set(tokens(r["nombre"]))
            otros = set(tokens((r["categoria"] or "") + " " + (r["descripcion"] or "")))
            # el nombre pesa mas que la categoria/descripcion
            score = 2.0 * len(q & nombre) + 1.0 * len((q & otros) - nombre)
            if score > 0:
                puntuados.append((score, r))
        puntuados.sort(key=lambda x: (-x[0], x[1]["id"]))
        resultado = [_producto_dict(r, s) for s, r in puntuados[:5]]
        # productos del borrador de pedido: se incluyen aunque el mensaje no los nombre
        for r in rows:
            if forzar_ids and r["id"] in forzar_ids and r["id"] not in {p["id"] for p in resultado}:
                resultado.append(_producto_dict(r, 0.0, forzado=True))
        # alternativas de la misma categoria que el mejor resultado (para ofrecer si esta agotado)
        if resultado:
            cat = resultado[0]["categoria"]
            ya = {p["id"] for p in resultado}
            for r in rows:
                if r["categoria"] == cat and r["id"] not in ya and len(resultado) < 7:
                    resultado.append(_producto_dict(r, 0.0))
        return resultado

    def faqs(self, negocio_id: int, consulta: str) -> list[dict]:
        q = set(tokens(consulta))
        rows = self.conn.execute(
            "SELECT * FROM pregunta_frecuente WHERE negocio_id = ? AND activo = 1", (negocio_id,)).fetchall()
        puntuadas = []
        for r in rows:
            claves = set(tokens(r["palabras_clave"].replace(",", " ")))
            score = float(len(q & claves))
            if score > 0:
                d = dict(r)
                d["score"] = score
                puntuadas.append(d)
        puntuadas.sort(key=lambda d: -d["score"])
        return puntuadas[:3]
