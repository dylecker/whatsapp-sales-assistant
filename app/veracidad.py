"""Control de veracidad de las respuestas (RNF-05).

Recuperar documentos (RAG) reduce errores pero no garantiza que la respuesta sea correcta, asi que
el sistema NO confia en el texto del modelo: antes de enviarlo comprueba contra la base de datos
los tres datos que mas dano hacen si se inventan.

* Precios: todo valor en pesos debe ser el precio de un producto recuperado (o un multiplo, para totales).
* Stock: toda cantidad de unidades disponibles debe coincidir con el stock de un producto recuperado.
* Tallas: toda talla ofrecida debe existir en algun producto recuperado.

Limitaciones (se documentan en la validacion): la comprobacion no asocia cada dato a un producto concreto
cuando se recuperan varios, y no valida politicas en texto libre (envios, devoluciones).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import precios_en_texto

RE_STOCK = re.compile(
    r"(?:hay|quedan|tenemos|contamos con|solo quedan|disponibles?:?)\s+(\d+)\s+unidad\w*|"
    r"(\d+)\s+unidad\w*\s+disponibles?|unidad\w*\s*\((\d+)\)", re.I)
RE_TALLAS = re.compile(r"(?i:tallas?\s*(?:disponibles?)?\s*:?\s*)((?:(?:XXL|XL|XS|S|M|L|\d{2})\b[\s,y/]*)+)")
RE_TALLA_TOKEN = re.compile(r"\b(XXL|XL|XS|S|M|L|\d{2})\b")
# Cifra de 4+ digitos (con o sin separador de miles) que no lleva $ ni COP: "por 119900". Se ignoran anios y "#1234".
RE_MONTO_SUELTO = re.compile(r"(?<![\d.,#\w])(\d{1,3}(?:[.,]\d{3})+|\d{4,6})(?![\d]|[.,]\d)")
RE_NEGACION = re.compile(r"\b(no (?:est[aá] |esta |hay |tenemos |contamos |manejamos )|sin |agotad\w+)", re.I)


@dataclass
class Veredicto:
    ok: bool
    problemas: list[str] = field(default_factory=list)


def verificar(texto: str, productos: list[dict], borrador: dict | None = None,
              mensaje_cliente: str = "") -> Veredicto:
    problemas: list[str] = []

    permitidos_precio: set[int] = set()
    for p in productos:
        permitidos_precio.add(p["precio_cop"])
        permitidos_precio.update(p["precio_cop"] * q for q in range(2, 100))
    sueltos = [int(re.sub(r"[.,]", "", m)) for m in RE_MONTO_SUELTO.findall(texto)]
    montos = set(precios_en_texto(texto)) | {v for v in sueltos if not 1990 <= v <= 2100}
    for v in sorted(montos):
        if v not in permitidos_precio:
            problemas.append(f"precio_no_catalogo:{v}")

    permitidos_stock = {p["stock"] for p in productos}
    if borrador and isinstance(borrador.get("cantidad"), int):
        permitidos_stock.add(borrador["cantidad"])
    permitidos_stock.update(int(n) for n in re.findall(r"\d+", mensaje_cliente))
    for m in RE_STOCK.finditer(texto):
        n = int(next(g for g in m.groups() if g))
        if n not in permitidos_stock:
            problemas.append(f"stock_no_coincide:{n}")

    tallas_validas = {str(t).upper() for p in productos for t in p["tallas"]}
    # Una frase que NIEGA una talla ("La talla 40 no esta disponible") no la ofrece: no se marca.
    for frase in re.split(r"(?<=[.!?])\s+|\n", texto):
        if RE_NEGACION.search(frase):
            continue
        es_pregunta = "?" in frase or "¿" in frase
        for m in RE_TALLAS.finditer(frase):
            for t in RE_TALLA_TOKEN.findall(m.group(1)):
                if tallas_validas and t not in tallas_validas:
                    # una pregunta que repite la talla que el propio cliente pidio no ofrece nada
                    if es_pregunta and re.search(r"\b" + re.escape(t) + r"\b", mensaje_cliente, re.I):
                        continue
                    problemas.append(f"talla_inexistente:{t}")

    return Veredicto(not problemas, problemas)
