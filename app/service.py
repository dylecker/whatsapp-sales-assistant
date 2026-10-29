"""Servicio de conversacion: implementa el flujo 1 (mensaje entrante) y el traspaso a humano."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import Settings
from .db import utcnow
from .llm import LLMProvider, LLMRequest, LLMResult
from .retrieval import LexicalRetriever, Retriever
from .textutil import norm, precios_en_texto
from .whatsapp import Inbound, WhatsAppSender

log = logging.getLogger("wsa.service")

ETAPAS = ["nuevo", "interesado", "negociando", "cerrado", "perdido"]
RE_ACEPTO = re.compile(r"\b(acepto|autorizo|de acuerdo)\b")

MSG_FALLA = ("Tuve un inconveniente para responderte. Voy a pasar tu mensaje a una persona del equipo "
             "para que te atienda.")
MSG_NO_INFO = ("No tengo esa información, así que paso tu consulta a una persona del equipo. "
               "Mientras tanto no te responderé yo, para que no se crucen los mensajes.")
MSG_NO_TEXTO = "Por ahora solo puedo leer mensajes de texto. ¿Me escribes qué necesitas?"
MSG_ESPERA = "Seguimos buscando a una persona del equipo para atenderte. Gracias por tu paciencia."


class ConversationService:
    def __init__(self, conn: sqlite3.Connection, sender: WhatsAppSender, llm: LLMProvider,
                 settings: Settings, retriever: Retriever | None = None):
        self.conn = conn
        self.sender = sender
        self.llm = llm
        self.settings = settings
        self.retriever = retriever or LexicalRetriever(conn)

    # ------------------------------------------------------------------ utilidades de datos
    def _negocio(self, phone_number_id: str):
        return self.conn.execute("SELECT * FROM negocio WHERE whatsapp_phone_number_id = ?",
                                 (phone_number_id,)).fetchone()

    def _cliente(self, negocio_id: int, telefono: str, nombre: str | None):
        row = self.conn.execute("SELECT * FROM cliente WHERE negocio_id = ? AND telefono = ?",
                                (negocio_id, telefono)).fetchone()
        if row:
            if nombre and not row["nombre"]:
                self.conn.execute("UPDATE cliente SET nombre = ? WHERE id = ?", (nombre, row["id"]))
            return row
        cur = self.conn.execute(
            "INSERT INTO cliente (negocio_id, telefono, nombre, creado_en) VALUES (?,?,?,?)",
            (negocio_id, telefono, nombre, utcnow()))
        return self.conn.execute("SELECT * FROM cliente WHERE id = ?", (cur.lastrowid,)).fetchone()

    def _conversacion(self, negocio, cliente):
        row = self.conn.execute("SELECT * FROM conversacion WHERE cliente_id = ? AND abierta = 1",
                                (cliente["id"],)).fetchone()
        if row:
            return row
        modo = "ia" if negocio["ia_activa"] else "humano"
        cur = self.conn.execute(
            "INSERT INTO conversacion (negocio_id, cliente_id, modo, requiere_atencion, creada_en) VALUES (?,?,?,?,?)",
            (negocio["id"], cliente["id"], modo, 0 if modo == "ia" else 1, utcnow()))
        return self.conn.execute("SELECT * FROM conversacion WHERE id = ?", (cur.lastrowid,)).fetchone()

    def guardar_mensaje(self, conv, remitente: str, texto: str, usuario_id: int | None = None,
                        wa_id: str | None = None, intencion: str | None = None) -> int:
        ahora = utcnow()
        cur = self.conn.execute(
            "INSERT INTO mensaje (conversacion_id, negocio_id, remitente, usuario_id, texto, intencion, wa_message_id, creado_en)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (conv["id"], conv["negocio_id"], remitente, usuario_id, texto, intencion, wa_id, ahora))
        self.conn.execute("UPDATE conversacion SET ultimo_mensaje_en = ? WHERE id = ?", (ahora, conv["id"]))
        return cur.lastrowid

    def _update_conv(self, conv_id: int, **campos) -> None:
        permitidos = {"modo", "abierta", "asignado_a", "requiere_atencion", "motivo_traspaso", "handoff_en",
                      "espera_notificada", "borrador_pedido", "fallos_consecutivos"}
        assert set(campos) <= permitidos, set(campos) - permitidos
        sets = ", ".join(f"{k} = ?" for k in campos)
        self.conn.execute(f"UPDATE conversacion SET {sets} WHERE id = ?", (*campos.values(), conv_id))

    def cambiar_etapa(self, conv_id: int, nueva: str, origen: str, usuario_id: int | None = None) -> bool:
        conv = self.conn.execute("SELECT * FROM conversacion WHERE id = ?", (conv_id,)).fetchone()
        if nueva not in ETAPAS or conv["etapa"] == nueva:
            return False
        self.conn.execute(
            "INSERT INTO evento_embudo (conversacion_id, etapa_anterior, etapa_nueva, origen, usuario_id, creado_en)"
            " VALUES (?,?,?,?,?,?)", (conv_id, conv["etapa"], nueva, origen, usuario_id, utcnow()))
        self.conn.execute("UPDATE conversacion SET etapa = ?, abierta = ? WHERE id = ?",
                          (nueva, 0 if nueva in ("cerrado", "perdido") else 1, conv_id))
        return True

    def _avanzar_etapa(self, conv, minima: str) -> None:
        actual = conv["etapa"]
        if actual in ("cerrado", "perdido"):
            return
        if ETAPAS.index(minima) > ETAPAS.index(actual):
            self.cambiar_etapa(conv["id"], minima, "ia")

    # ------------------------------------------------------------------ horario
    def _fuera_de_horario(self, negocio) -> bool:
        ahora = datetime.now(ZoneInfo(self.settings.timezone)).strftime("%H:%M")
        return not (negocio["horario_inicio"] <= ahora <= negocio["horario_fin"])

    # ------------------------------------------------------------------ envio
    def _enviar(self, negocio, conv, cliente, texto: str, intencion: str | None = None) -> None:
        wa_id = self.sender.send_text(negocio["whatsapp_phone_number_id"], cliente["telefono"], texto)
        self.guardar_mensaje(conv, "ia", texto, wa_id=wa_id, intencion=intencion)

    def _traspasar(self, negocio, conv, cliente, motivo: str, texto: str, intencion: str | None) -> None:
        self._update_conv(conv["id"], modo="humano", requiere_atencion=1, motivo_traspaso=motivo,
                          handoff_en=utcnow(), espera_notificada=0)
        self._enviar(negocio, conv, cliente, texto, intencion)

    # ------------------------------------------------------------------ flujo 1
    def handle_inbound(self, msg: Inbound) -> dict:
        negocio = self._negocio(msg.phone_number_id)
        if negocio is None:
            log.warning("Webhook para un phone_number_id desconocido: %s", msg.phone_number_id)
            return {"estado": "ignorado", "motivo": "negocio_desconocido"}
        if msg.wa_message_id and self.conn.execute(
                "SELECT 1 FROM mensaje WHERE wa_message_id = ?", (msg.wa_message_id,)).fetchone():
            return {"estado": "duplicado"}

        cliente = self._cliente(negocio["id"], msg.wa_from, msg.wa_name)
        conv = self._conversacion(negocio, cliente)
        texto = msg.texto if msg.texto is not None else f"[mensaje {msg.tipo or 'no soportado'}]"
        msg_id = self.guardar_mensaje(conv, "cliente", texto, wa_id=msg.wa_message_id or None)
        self.conn.commit()

        # Paso 2 del flujo: conversacion en modo humano -> solo se avisa al asesor
        if conv["modo"] == "humano":
            self._update_conv(conv["id"], requiere_atencion=1)
            self.conn.commit()
            return {"estado": "notificado_asesor", "conversacion_id": conv["id"]}

        if msg.texto is None:
            self._enviar(negocio, conv, cliente, MSG_NO_TEXTO, "otra")
            self.conn.commit()
            return {"estado": "respondido", "intencion": "otra", "conversacion_id": conv["id"]}

        # Consentimiento (Ley 1581 de 2012): sin autorizacion no se procesa el mensaje
        if self.settings.require_consent and not cliente["consentimiento_datos"]:
            return self._consentimiento(negocio, conv, cliente, msg_id, texto)

        # Paso 3: contexto recuperado (catalogo, FAQ, historial, borrador)
        borrador = json.loads(conv["borrador_pedido"] or "{}")
        forzar = [borrador["producto_id"]] if borrador.get("producto_id") else None
        productos = self.retriever.productos(negocio["id"], texto, forzar)
        faqs = self.retriever.faqs(negocio["id"], texto)
        historial = [(r["remitente"], r["texto"]) for r in self.conn.execute(
            "SELECT remitente, texto FROM mensaje WHERE conversacion_id = ? ORDER BY id DESC LIMIT 9", (conv["id"],))][::-1][:-1]
        req = LLMRequest(
            negocio_nombre=negocio["nombre"], tono=negocio["tono"], mensaje=texto, historial=historial,
            productos=productos, faqs=faqs, borrador=borrador,
            fuera_de_horario=self._fuera_de_horario(negocio),
            horario=f"{negocio['horario_inicio']} a {negocio['horario_fin']}")

        # Paso 4: el modelo identifica la intencion y redacta
        try:
            res = self.llm.generate(req)
        except Exception:  # noqa: BLE001 - cualquier falla del proveedor degrada a traspaso
            log.exception("Fallo del proveedor de LLM")
            res = LLMResult("otra", MSG_FALLA, requiere_humano=True, motivo="falla_llm")

        # Control de veracidad (RNF-05): ningun precio puede salir de fuera del catalogo recuperado
        if not res.requiere_humano and not self._respuesta_verificada(res.respuesta, productos):
            log.warning("Respuesta con precio no verificado; se traspasa a una persona: %r", res.respuesta)
            res = LLMResult(res.intencion, MSG_FALLA, requiere_humano=True, motivo="respuesta_no_verificada")

        self.conn.execute("UPDATE mensaje SET intencion = ? WHERE id = ?", (res.intencion, msg_id))

        # Paso 5: traspaso a humano
        if res.requiere_humano:
            self._traspasar(negocio, conv, cliente, res.motivo or "otro", res.respuesta, res.intencion)
            self.conn.commit()
            return {"estado": "traspasado", "intencion": res.intencion, "motivo": res.motivo,
                    "conversacion_id": conv["id"]}

        fallos = (conv["fallos_consecutivos"] + 1) if res.sin_informacion else 0
        if fallos >= 2:
            self._traspasar(negocio, conv, cliente, "sin_informacion", MSG_NO_INFO, res.intencion)
            self._update_conv(conv["id"], fallos_consecutivos=0)
            self.conn.commit()
            return {"estado": "traspasado", "intencion": res.intencion, "motivo": "sin_informacion",
                    "conversacion_id": conv["id"]}
        self._update_conv(conv["id"], fallos_consecutivos=fallos)

        # Paso 6: guardar datos detectados y actualizar el embudo
        pedido_id = None
        if res.pedido_listo:
            pedido_id, error = self._registrar_pedido(negocio, conv, cliente, res.borrador)
            if error:
                self._traspasar(negocio, conv, cliente, "pedido_invalido", MSG_FALLA, "pedido")
                self.conn.commit()
                return {"estado": "traspasado", "intencion": "pedido", "motivo": error,
                        "conversacion_id": conv["id"]}
            self._update_conv(conv["id"], borrador_pedido=None)
        else:
            self._update_conv(conv["id"], borrador_pedido=json.dumps(res.borrador) if res.borrador else None)

        if res.intencion == "consulta":
            self._avanzar_etapa(conv, "interesado")
        elif res.intencion == "pedido":
            self._avanzar_etapa(conv, "negociando")

        # Paso 7: enviar y guardar quien escribio la respuesta
        self._enviar(negocio, conv, cliente, res.respuesta, res.intencion)
        self.conn.commit()
        return {"estado": "respondido", "intencion": res.intencion, "pedido_id": pedido_id,
                "conversacion_id": conv["id"]}

    # ------------------------------------------------------------------ piezas del flujo
    def _consentimiento(self, negocio, conv, cliente, msg_id: int, texto: str) -> dict:
        if RE_ACEPTO.search(norm(texto)):
            self.conn.execute("UPDATE cliente SET consentimiento_datos = 1, consentimiento_en = ? WHERE id = ?",
                              (utcnow(), cliente["id"]))
            self.conn.execute("UPDATE mensaje SET intencion = 'consentimiento' WHERE id = ?", (msg_id,))
            self._enviar(negocio, conv, cliente, "Gracias, ya puedo ayudarte. ¿Qué estás buscando?", "consentimiento")
            self.conn.commit()
            return {"estado": "consentimiento_registrado", "conversacion_id": conv["id"]}
        aviso = (f"Hola, soy el asistente virtual de {negocio['nombre']}. Para atenderte necesito tu autorización "
                 "para tratar tus datos personales (nombre y número de teléfono) con el único fin de atender tu "
                 "solicitud, según la Ley 1581 de 2012. Puedes pedir que los eliminemos cuando quieras. "
                 "Responde ACEPTO para continuar.")
        self.conn.execute("UPDATE mensaje SET intencion = 'aviso_datos' WHERE id = ?", (msg_id,))
        self._enviar(negocio, conv, cliente, aviso, "aviso_datos")
        self.conn.commit()
        return {"estado": "aviso_enviado", "conversacion_id": conv["id"]}

    @staticmethod
    def _respuesta_verificada(texto: str, productos: list[dict]) -> bool:
        permitidos: set[int] = set()
        for p in productos:
            permitidos.add(p["precio_cop"])
            permitidos.update(p["precio_cop"] * q for q in range(2, 100))
        return all(v in permitidos for v in precios_en_texto(texto))

    def _registrar_pedido(self, negocio, conv, cliente, b: dict) -> tuple[int | None, str | None]:
        prod = self.conn.execute("SELECT * FROM producto WHERE id = ? AND negocio_id = ? AND activo = 1",
                                 (b.get("producto_id"), negocio["id"])).fetchone()
        cantidad = b.get("cantidad")
        if prod is None or not isinstance(cantidad, int) or cantidad < 1 or cantidad > prod["stock"]:
            return None, "pedido_invalido"
        tallas = json.loads(prod["tallas"] or "[]")
        if tallas and tallas != ["unica"] and b.get("talla") not in tallas:
            return None, "pedido_invalido"
        cur = self.conn.execute(
            "INSERT INTO pedido (negocio_id, conversacion_id, cliente_id, ciudad, creado_en) VALUES (?,?,?,?,?)",
            (negocio["id"], conv["id"], cliente["id"], b.get("ciudad"), utcnow()))
        self.conn.execute(
            "INSERT INTO item_pedido (pedido_id, producto_id, talla, cantidad, precio_unitario_cop) VALUES (?,?,?,?,?)",
            (cur.lastrowid, prod["id"], b.get("talla"), cantidad, prod["precio_cop"]))
        return cur.lastrowid, None

    # ------------------------------------------------------------------ atencion humana
    def tomar_control(self, conv_id: int, usuario_id: int) -> None:
        self._update_conv(conv_id, modo="humano", asignado_a=usuario_id, requiere_atencion=0)
        self.conn.commit()

    def responder_humano(self, conv_id: int, usuario_id: int, texto: str) -> None:
        conv = self.conn.execute("SELECT * FROM conversacion WHERE id = ?", (conv_id,)).fetchone()
        negocio = self.conn.execute("SELECT * FROM negocio WHERE id = ?", (conv["negocio_id"],)).fetchone()
        cliente = self.conn.execute("SELECT * FROM cliente WHERE id = ?", (conv["cliente_id"],)).fetchone()
        wa_id = self.sender.send_text(negocio["whatsapp_phone_number_id"], cliente["telefono"], texto)
        self.guardar_mensaje(conv, "humano", texto, usuario_id=usuario_id, wa_id=wa_id)
        self._update_conv(conv_id, requiere_atencion=0)
        self.conn.commit()

    def devolver_a_ia(self, conv_id: int) -> None:
        self._update_conv(conv_id, modo="ia", asignado_a=None, requiere_atencion=0, fallos_consecutivos=0,
                          motivo_traspaso=None)
        self.conn.commit()

    def procesar_esperas(self, ahora: datetime | None = None) -> int:
        """Flujo alterno de CU-04: si nadie atiende en el tiempo definido, avisa al cliente y escala la alerta."""
        ahora = ahora or datetime.now(timezone.utc)
        n = 0
        filas = self.conn.execute(
            "SELECT c.*, n.espera_asesor_min FROM conversacion c JOIN negocio n ON n.id = c.negocio_id "
            "WHERE c.modo = 'humano' AND c.requiere_atencion = 1 AND c.espera_notificada = 0 "
            "AND c.handoff_en IS NOT NULL").fetchall()
        for c in filas:
            if datetime.fromisoformat(c["handoff_en"]) + timedelta(minutes=c["espera_asesor_min"]) <= ahora:
                negocio = self.conn.execute("SELECT * FROM negocio WHERE id = ?", (c["negocio_id"],)).fetchone()
                cliente = self.conn.execute("SELECT * FROM cliente WHERE id = ?", (c["cliente_id"],)).fetchone()
                self._enviar(negocio, c, cliente, MSG_ESPERA, "espera")
                self._update_conv(c["id"], espera_notificada=1)
                n += 1
        self.conn.commit()
        return n
