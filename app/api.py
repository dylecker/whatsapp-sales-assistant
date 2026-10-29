"""API HTTP (Starlette): webhook de WhatsApp y endpoints del panel."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import anyio
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from .config import Settings
from .db import connect, init_db, utcnow
from .llm import LLMProvider, build_provider
from .security import create_token, decode_token, verify_password, verify_signature
from .service import ETAPAS, ConversationService
from .whatsapp import WhatsAppSender, build_sender, parse_webhook

log = logging.getLogger("wsa.api")


def create_app(settings: Settings | None = None, sender: WhatsAppSender | None = None,
               llm: LLMProvider | None = None) -> Starlette:
    settings = settings or Settings()
    init_db(settings.db_path)
    sender = sender or build_sender(settings.sender)
    llm = llm or build_provider(settings.llm_provider)

    def servicio(conn) -> ConversationService:
        return ConversationService(conn, sender, llm, settings)

    def err(status: int, msg: str) -> JSONResponse:
        return JSONResponse({"error": msg}, status_code=status)

    def autenticado(handler):
        """Exige JWT valido; el negocio sale del token, nunca de la peticion (RF-10)."""
        async def wrapper(request: Request):
            h = request.headers.get("authorization", "")
            claims = decode_token(settings.jwt_secret, h[7:]) if h.lower().startswith("bearer ") else None
            if not claims:
                return err(401, "No autenticado")
            request.state.claims = claims
            return await handler(request)
        return wrapper

    async def en_hilo(fn, *args):
        return await anyio.to_thread.run_sync(fn, *args)

    # ------------------------------------------------------------------ salud
    async def health(request: Request):
        return JSONResponse({"estado": "ok", "hora": utcnow()})

    # ------------------------------------------------------------------ webhook
    async def webhook_verify(request: Request):
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.verify_token:
            return PlainTextResponse(q.get("hub.challenge", ""))
        return err(403, "Token de verificacion invalido")

    async def webhook_receive(request: Request):
        raw = await request.body()
        if not verify_signature(settings.app_secret, raw, request.headers.get("x-hub-signature-256")):
            return err(403, "Firma invalida")
        try:
            mensajes = parse_webhook(json.loads(raw))
        except json.JSONDecodeError:
            return err(400, "JSON invalido")

        def procesar():
            conn = connect(settings.db_path)
            try:
                svc = servicio(conn)
                resultados = []
                for m in mensajes:
                    try:
                        resultados.append(svc.handle_inbound(m))
                    except Exception:  # noqa: BLE001
                        conn.rollback()
                        log.exception("Error procesando mensaje %s", m.wa_message_id)
                        resultados.append({"estado": "error"})
                return resultados
            finally:
                conn.close()

        # Meta espera 200 rapido; si hay errores internos se registran y no se reintenta
        return JSONResponse({"ok": True, "resultados": await en_hilo(procesar)})

    # ------------------------------------------------------------------ auth
    async def login(request: Request):
        body = await request.json()

        def run():
            conn = connect(settings.db_path)
            try:
                u = conn.execute("SELECT * FROM usuario WHERE correo = ? AND activo = 1",
                                 (str(body.get("correo", "")).lower(),)).fetchone()
                if not u or not verify_password(str(body.get("password", "")), u["password_hash"]):
                    return None
                return {"token": create_token(settings.jwt_secret, settings.jwt_ttl_min, u["id"], u["negocio_id"], u["rol"]),
                        "usuario": {"id": u["id"], "nombre": u["nombre"], "rol": u["rol"]}}
            finally:
                conn.close()

        res = await en_hilo(run)
        return JSONResponse(res) if res else err(401, "Credenciales invalidas")

    # ------------------------------------------------------------------ helper de consultas con conexion
    def con_db(fn):
        """Ejecuta fn(conn, claims, request, body) en un hilo con su propia conexion."""
        async def wrapper(request: Request):
            claims = request.state.claims
            body = {}
            if request.method in ("POST", "PATCH", "PUT"):
                try:
                    body = await request.json()
                except json.JSONDecodeError:
                    body = {}

            def run():
                conn = connect(settings.db_path)
                try:
                    return fn(conn, claims, request, body)
                finally:
                    conn.close()
            return await en_hilo(run)
        return wrapper

    def conv_del_negocio(conn, claims, conv_id: int):
        return conn.execute("SELECT * FROM conversacion WHERE id = ? AND negocio_id = ?",
                            (conv_id, claims["negocio_id"])).fetchone()

    # ------------------------------------------------------------------ conversaciones
    def _listar(conn, claims, request, body):
        q = request.query_params
        sql = ("SELECT c.id, c.etapa, c.modo, c.abierta, c.requiere_atencion, c.espera_notificada, c.motivo_traspaso, "
               "c.asignado_a, c.ultimo_mensaje_en, cl.nombre AS cliente, cl.telefono, "
               "(SELECT texto FROM mensaje m WHERE m.conversacion_id = c.id ORDER BY m.id DESC LIMIT 1) AS ultimo_mensaje "
               "FROM conversacion c JOIN cliente cl ON cl.id = c.cliente_id WHERE c.negocio_id = ?")
        args: list = [claims["negocio_id"]]
        if q.get("etapa"):
            sql += " AND c.etapa = ?"; args.append(q["etapa"])
        if q.get("modo"):
            sql += " AND c.modo = ?"; args.append(q["modo"])
        if q.get("atencion") == "1":
            sql += " AND c.requiere_atencion = 1"
        if q.get("desde"):
            sql += " AND c.ultimo_mensaje_en >= ?"; args.append(q["desde"])
        if q.get("q"):
            sql += " AND (cl.nombre LIKE ? OR cl.telefono LIKE ?)"; args += [f"%{q['q']}%"] * 2
        sql += " ORDER BY c.requiere_atencion DESC, c.ultimo_mensaje_en DESC"
        filas = [dict(r) for r in conn.execute(sql, args)]
        return JSONResponse({"conversaciones": filas, "pendientes_asesor": sum(f["requiere_atencion"] for f in filas)})

    def _detalle(conn, claims, request, body):
        conv = conv_del_negocio(conn, claims, int(request.path_params["id"]))
        if not conv:
            return err(404, "Conversacion no encontrada")
        msgs = [dict(r) for r in conn.execute(
            "SELECT id, remitente, usuario_id, texto, intencion, creado_en FROM mensaje WHERE conversacion_id = ? ORDER BY id",
            (conv["id"],))]
        eventos = [dict(r) for r in conn.execute(
            "SELECT etapa_anterior, etapa_nueva, origen, usuario_id, creado_en FROM evento_embudo WHERE conversacion_id = ? ORDER BY id",
            (conv["id"],))]
        return JSONResponse({"conversacion": dict(conv), "mensajes": msgs, "eventos_embudo": eventos})

    def _tomar(conn, claims, request, body):
        conv = conv_del_negocio(conn, claims, int(request.path_params["id"]))
        if not conv:
            return err(404, "Conversacion no encontrada")
        servicio(conn).tomar_control(conv["id"], int(claims["sub"]))
        return JSONResponse({"ok": True, "modo": "humano"})

    def _responder(conn, claims, request, body):
        conv = conv_del_negocio(conn, claims, int(request.path_params["id"]))
        if not conv:
            return err(404, "Conversacion no encontrada")
        texto = str(body.get("texto", "")).strip()
        if not texto:
            return err(400, "El texto es obligatorio")
        if conv["modo"] != "humano" or conv["asignado_a"] != int(claims["sub"]):
            return err(409, "Primero toma el control de la conversacion")
        servicio(conn).responder_humano(conv["id"], int(claims["sub"]), texto)
        return JSONResponse({"ok": True})

    def _devolver(conn, claims, request, body):
        conv = conv_del_negocio(conn, claims, int(request.path_params["id"]))
        if not conv:
            return err(404, "Conversacion no encontrada")
        servicio(conn).devolver_a_ia(conv["id"])
        return JSONResponse({"ok": True, "modo": "ia"})

    def _etapa(conn, claims, request, body):
        conv = conv_del_negocio(conn, claims, int(request.path_params["id"]))
        if not conv:
            return err(404, "Conversacion no encontrada")
        if body.get("etapa") not in ETAPAS:
            return err(400, f"Etapa invalida. Opciones: {', '.join(ETAPAS)}")
        servicio(conn).cambiar_etapa(conv["id"], body["etapa"], "manual", int(claims["sub"]))
        conn.commit()
        return JSONResponse({"ok": True, "etapa": body["etapa"]})

    # ------------------------------------------------------------------ embudo, pedidos, metricas
    def _embudo(conn, claims, request, body):
        salida = {e: [] for e in ETAPAS}
        for r in conn.execute(
                "SELECT c.id, c.etapa, cl.nombre AS cliente, cl.telefono FROM conversacion c "
                "JOIN cliente cl ON cl.id = c.cliente_id WHERE c.negocio_id = ? ORDER BY c.id", (claims["negocio_id"],)):
            salida[r["etapa"]].append({"conversacion_id": r["id"], "cliente": r["cliente"], "telefono": r["telefono"]})
        return JSONResponse({"embudo": salida, "totales": {e: len(v) for e, v in salida.items()}})

    def _pedidos(conn, claims, request, body):
        filas = []
        for p in conn.execute(
                "SELECT p.id, p.estado, p.ciudad, p.creado_en, cl.nombre AS cliente, cl.telefono FROM pedido p "
                "JOIN cliente cl ON cl.id = p.cliente_id WHERE p.negocio_id = ? ORDER BY p.id DESC", (claims["negocio_id"],)):
            items = [dict(i) for i in conn.execute(
                "SELECT pr.nombre AS producto, i.talla, i.cantidad, i.precio_unitario_cop FROM item_pedido i "
                "JOIN producto pr ON pr.id = i.producto_id WHERE i.pedido_id = ?", (p["id"],))]
            d = dict(p)
            d["items"] = items
            d["total_cop"] = sum(i["cantidad"] * i["precio_unitario_cop"] for i in items)
            filas.append(d)
        return JSONResponse({"pedidos": filas})

    def _metricas(conn, claims, request, body):
        nid = claims["negocio_id"]
        total = conn.execute("SELECT COUNT(*) FROM conversacion WHERE negocio_id = ?", (nid,)).fetchone()[0]
        por_etapa = {r["etapa"]: r["n"] for r in conn.execute(
            "SELECT etapa, COUNT(*) AS n FROM conversacion WHERE negocio_id = ? GROUP BY etapa", (nid,))}
        # tiempo de respuesta: del mensaje del cliente a la primera respuesta (IA o persona)
        deltas, pendiente, conv_actual = [], None, None
        for r in conn.execute("SELECT conversacion_id, remitente, creado_en FROM mensaje WHERE negocio_id = ? "
                              "ORDER BY conversacion_id, id", (nid,)):
            if r["conversacion_id"] != conv_actual:
                conv_actual, pendiente = r["conversacion_id"], None
            t = datetime.fromisoformat(r["creado_en"])
            if r["remitente"] == "cliente":
                pendiente = pendiente or t
            elif pendiente is not None:
                deltas.append((t - pendiente).total_seconds())
                pendiente = None
        envios = {r["remitente"]: r["n"] for r in conn.execute(
            "SELECT remitente, COUNT(*) AS n FROM mensaje WHERE negocio_id = ? GROUP BY remitente", (nid,))}
        pend = conn.execute("SELECT COUNT(*) FROM conversacion WHERE negocio_id = ? AND requiere_atencion = 1", (nid,)).fetchone()[0]
        return JSONResponse({
            "conversaciones": total,
            "tiempo_respuesta_promedio_seg": round(sum(deltas) / len(deltas), 1) if deltas else None,
            "leads_en_seguimiento": por_etapa.get("interesado", 0) + por_etapa.get("negociando", 0),
            "tasa_conversion_pct": round(100 * por_etapa.get("cerrado", 0) / total, 1) if total else 0.0,
            "por_etapa": por_etapa, "mensajes_por_remitente": envios, "pendientes_asesor": pend})

    # ------------------------------------------------------------------ catalogo, FAQ, negocio
    def _prod_row(r):
        d = dict(r)
        d["tallas"] = json.loads(d["tallas"] or "[]")
        d.pop("embedding", None)
        return d

    def _productos(conn, claims, request, body):
        nid = claims["negocio_id"]
        if request.method == "GET":
            return JSONResponse({"productos": [_prod_row(r) for r in conn.execute(
                "SELECT * FROM producto WHERE negocio_id = ? ORDER BY id", (nid,))]})
        for campo in ("nombre", "categoria", "precio_cop"):
            if body.get(campo) in (None, ""):
                return err(400, f"Falta el campo {campo}")
        cur = conn.execute(
            "INSERT INTO producto (negocio_id, nombre, descripcion, categoria, precio_cop, tallas, stock, creado_en) VALUES (?,?,?,?,?,?,?,?)",
            (nid, body["nombre"], body.get("descripcion"), body["categoria"], int(body["precio_cop"]),
             json.dumps(body.get("tallas", [])), int(body.get("stock", 0)), utcnow()))
        conn.commit()
        return JSONResponse({"id": cur.lastrowid}, status_code=201)

    def _producto_patch(conn, claims, request, body):
        pid = int(request.path_params["id"])
        if not conn.execute("SELECT 1 FROM producto WHERE id = ? AND negocio_id = ?", (pid, claims["negocio_id"])).fetchone():
            return err(404, "Producto no encontrado")
        editables = {"nombre", "descripcion", "categoria", "precio_cop", "tallas", "stock", "activo"}
        cambios = {k: v for k, v in body.items() if k in editables}
        if "tallas" in cambios:
            cambios["tallas"] = json.dumps(cambios["tallas"])
        if not cambios:
            return err(400, "Nada que actualizar")
        try:
            conn.execute(f"UPDATE producto SET {', '.join(k + ' = ?' for k in cambios)} WHERE id = ?", (*cambios.values(), pid))
        except Exception:  # noqa: BLE001 - violacion de CHECK (precio/stock negativos)
            return err(400, "Valores invalidos")
        conn.commit()
        return JSONResponse({"ok": True})

    def _faqs(conn, claims, request, body):
        nid = claims["negocio_id"]
        if request.method == "GET":
            return JSONResponse({"preguntas": [dict(r) for r in conn.execute(
                "SELECT id, tema, pregunta, respuesta, palabras_clave, activo FROM pregunta_frecuente WHERE negocio_id = ?", (nid,))]})
        for campo in ("tema", "pregunta", "respuesta", "palabras_clave"):
            if not body.get(campo):
                return err(400, f"Falta el campo {campo}")
        cur = conn.execute("INSERT INTO pregunta_frecuente (negocio_id, tema, pregunta, respuesta, palabras_clave) VALUES (?,?,?,?,?)",
                           (nid, body["tema"], body["pregunta"], body["respuesta"], body["palabras_clave"]))
        conn.commit()
        return JSONResponse({"id": cur.lastrowid}, status_code=201)

    def _negocio(conn, claims, request, body):
        nid = claims["negocio_id"]
        if request.method == "PATCH":
            if claims["rol"] != "propietario":
                return err(403, "Solo el propietario puede cambiar la configuracion")
            editables = {"tono", "horario_inicio", "horario_fin", "ia_activa", "espera_asesor_min"}
            cambios = {k: v for k, v in body.items() if k in editables}
            if not cambios:
                return err(400, "Nada que actualizar")
            try:
                conn.execute(f"UPDATE negocio SET {', '.join(k + ' = ?' for k in cambios)} WHERE id = ?", (*cambios.values(), nid))
            except Exception:  # noqa: BLE001
                return err(400, "Valores invalidos")
            conn.commit()
        n = conn.execute("SELECT id, nombre, tono, horario_inicio, horario_fin, ia_activa, espera_asesor_min FROM negocio WHERE id = ?", (nid,)).fetchone()
        return JSONResponse(dict(n))

    def _esperas(conn, claims, request, body):
        return JSONResponse({"avisos_enviados": servicio(conn).procesar_esperas()})

    def ruta(path, fn, methods):
        return Route(path, autenticado(con_db(fn)), methods=methods)

    return Starlette(routes=[
        Route("/health", health),
        Route("/webhook", webhook_verify, methods=["GET"]),
        Route("/webhook", webhook_receive, methods=["POST"]),
        Route("/api/auth/login", login, methods=["POST"]),
        ruta("/api/conversaciones", _listar, ["GET"]),
        ruta("/api/conversaciones/{id:int}", _detalle, ["GET"]),
        ruta("/api/conversaciones/{id:int}/tomar-control", _tomar, ["POST"]),
        ruta("/api/conversaciones/{id:int}/responder", _responder, ["POST"]),
        ruta("/api/conversaciones/{id:int}/devolver-ia", _devolver, ["POST"]),
        ruta("/api/conversaciones/{id:int}/etapa", _etapa, ["PATCH"]),
        ruta("/api/embudo", _embudo, ["GET"]),
        ruta("/api/pedidos", _pedidos, ["GET"]),
        ruta("/api/metricas", _metricas, ["GET"]),
        ruta("/api/productos", _productos, ["GET", "POST"]),
        ruta("/api/productos/{id:int}", _producto_patch, ["PATCH"]),
        ruta("/api/preguntas-frecuentes", _faqs, ["GET", "POST"]),
        ruta("/api/negocio", _negocio, ["GET", "PATCH"]),
        ruta("/api/esperas/procesar", _esperas, ["POST"]),
    ])
