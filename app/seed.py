"""Datos de ejemplo: tienda de ropa ficticia (la misma del prototipo navegable)."""
from __future__ import annotations

import json
import sqlite3

from .db import utcnow
from .security import hash_password

PHONE_NUMBER_ID = "100200300400500"
OWNER = ("dueno@modacaribe.test", "demo1234")
SELLER = ("vendedor@modacaribe.test", "demo1234")

PRODUCTOS = [
    # nombre, descripcion, categoria, precio, tallas, stock
    ("Camiseta oversize negra", "Algodón pesado, corte holgado", "camiseta", 59900, ["S", "M", "L", "XL"], 14),
    ("Camiseta básica blanca", "Algodón peinado, cuello redondo", "camiseta", 39900, ["S", "M", "L"], 25),
    ("Jean slim azul", "Denim elástico, corte slim", "jean", 129900, ["28", "30", "32", "34"], 8),
    ("Vestido floral", "Vestido midi estampado", "vestido", 99900, ["S", "M", "L"], 0),
    ("Vestido lino beige", "Lino fresco, ideal para clima cálido", "vestido", 119900, ["S", "M", "L"], 5),
    ("Gorra clásica negra", "Ajustable, bordado frontal", "gorra", 34900, ["unica"], 3),
    ("Sudadera gris con capota", "Felpa suave, bolsillo canguro", "sudadera", 109900, ["S", "M", "L", "XL"], 10),
]

FAQS = [
    ("envios", "¿Hacen envíos?",
     "Hacemos envíos a todo el país con transportadora. En Cartagena el domicilio llega en 1 día hábil y a otras "
     "ciudades entre 2 y 4 días hábiles. El costo del envío lo confirma una persona del equipo según tu ciudad.",
     "envio,envios,enviar,domicilio,despacho,despachan,transportadora,demora,llega"),
    ("pagos", "¿Cómo puedo pagar?",
     "Aceptamos transferencia bancaria, Nequi y pago contra entrega en Cartagena. Por este chat no pedimos datos de "
     "tarjeta ni claves.",
     "pago,pagos,pagar,transferencia,nequi,contraentrega,tarjeta,efectivo"),
    ("horario", "¿Cuál es el horario de atención?",
     "Atendemos de lunes a sábado de 8:00 a. m. a 6:00 p. m. Fuera de ese horario te respondemos al abrir.",
     "horario,horarios,abren,abierto,atienden,atencion,cierran"),
    ("devoluciones", "¿Puedo cambiar o devolver una prenda?",
     "Aceptamos cambios de talla dentro de los 8 días siguientes a la entrega, con la prenda sin uso y con etiqueta.",
     "devolucion,devoluciones,devolver,cambio,cambios,cambiar,garantia"),
]


def seed(conn: sqlite3.Connection, tono: str = "cercano") -> dict:
    existente = conn.execute("SELECT id FROM negocio WHERE whatsapp_phone_number_id = ?", (PHONE_NUMBER_ID,)).fetchone()
    if existente:
        return {"negocio_id": existente["id"]}
    ahora = utcnow()
    cur = conn.execute(
        "INSERT INTO negocio (nombre, whatsapp_phone_number_id, tono, creado_en) VALUES (?,?,?,?)",
        ("Moda Caribe", PHONE_NUMBER_ID, tono, ahora))
    nid = cur.lastrowid
    for nombre, (correo, clave), rol in (("Laura Pérez", OWNER, "propietario"), ("Carlos Díaz", SELLER, "vendedor")):
        conn.execute("INSERT INTO usuario (negocio_id, nombre, correo, password_hash, rol, creado_en) VALUES (?,?,?,?,?,?)",
                     (nid, nombre, correo, hash_password(clave), rol, ahora))
    for nombre, desc, cat, precio, tallas, stock in PRODUCTOS:
        conn.execute("INSERT INTO producto (negocio_id, nombre, descripcion, categoria, precio_cop, tallas, stock, creado_en)"
                     " VALUES (?,?,?,?,?,?,?,?)", (nid, nombre, desc, cat, precio, json.dumps(tallas), stock, ahora))
    for tema, preg, resp, claves in FAQS:
        conn.execute("INSERT INTO pregunta_frecuente (negocio_id, tema, pregunta, respuesta, palabras_clave) VALUES (?,?,?,?,?)",
                     (nid, tema, preg, resp, claves))
    conn.commit()
    return {"negocio_id": nid}
