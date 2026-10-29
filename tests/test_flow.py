"""Pruebas de extremo a extremo: webhook firmado -> flujo 1 -> base de datos -> API del panel."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.llm import LLMResult
from app.seed import OWNER, PHONE_NUMBER_ID, SELLER
from app.security import hash_password
from app.service import ConversationService
from app.whatsapp import SimulatedSender


# ------------------------------------------------------------------ webhook y seguridad (RF-01, RNF-03)
def test_verificacion_del_webhook(srv):
    ok = srv.http("GET", "/webhook?hub.mode=subscribe&hub.verify_token=dev-verify-token&hub.challenge=12345")
    assert ok == (200, b"12345")
    assert srv.http("GET", "/webhook?hub.mode=subscribe&hub.verify_token=otro&hub.challenge=1")[0] == 403


def test_firma_invalida_se_rechaza_y_no_guarda_nada(srv):
    status, _ = srv.http("POST", "/webhook", b'{"object":"whatsapp_business_account","entry":[]}',
                         {"X-Hub-Signature-256": "sha256=" + "0" * 64})
    assert status == 403
    status, _ = srv.http("POST", "/webhook", b"{}", {})
    assert status == 403
    assert srv.db().execute("SELECT COUNT(*) FROM mensaje").fetchone()[0] == 0


def test_mensaje_duplicado_se_guarda_una_sola_vez(srv):
    a = srv.webhook("hola", wa_id="wamid.IGUAL")
    b = srv.webhook("hola", wa_id="wamid.IGUAL")
    assert a["estado"] == "respondido" and b["estado"] == "duplicado"
    assert srv.db().execute("SELECT COUNT(*) FROM mensaje WHERE remitente='cliente'").fetchone()[0] == 1
    assert len(srv.sender.outbox) == 1


def test_negocio_desconocido_se_ignora(srv):
    assert srv.webhook("hola", phone_number_id="999")["estado"] == "ignorado"
    assert srv.sender.outbox == []


# ------------------------------------------------------------------ consentimiento (RNF-04)
def test_sin_consentimiento_solo_se_envia_el_aviso(srv_consent):
    r = srv_consent.webhook("cuanto vale la camiseta oversize negra")
    assert r["estado"] == "aviso_enviado"
    assert "Ley 1581" in srv_consent.last_reply() and "$" not in srv_consent.last_reply()
    r = srv_consent.webhook("ACEPTO")
    assert r["estado"] == "consentimiento_registrado"
    cli = srv_consent.db().execute("SELECT consentimiento_datos, consentimiento_en FROM cliente").fetchone()
    assert cli["consentimiento_datos"] == 1 and cli["consentimiento_en"]
    r = srv_consent.webhook("cuanto vale la camiseta oversize negra")
    assert r["estado"] == "respondido" and "$59.900" in srv_consent.last_reply()


# ------------------------------------------------------------------ CU-01 / HU-01 / HU-02
def test_consulta_precio_y_disponibilidad_mueve_a_interesado(srv):
    r = srv.webhook("Hola, cuánto vale la camiseta oversize negra?")
    assert r["intencion"] == "consulta"
    resp = srv.last_reply()
    assert "$59.900" in resp and "S, M, L, XL" in resp and "14 unidades" in resp
    c = srv.db().execute("SELECT etapa FROM conversacion").fetchone()
    assert c["etapa"] == "interesado"
    ev = srv.db().execute("SELECT etapa_anterior, etapa_nueva, origen FROM evento_embudo").fetchone()
    assert tuple(ev) == ("nuevo", "interesado", "ia")
    quien = [r[0] for r in srv.db().execute("SELECT remitente FROM mensaje ORDER BY id")]
    assert quien == ["cliente", "ia"]
    intent = srv.db().execute("SELECT intencion FROM mensaje WHERE remitente='cliente'").fetchone()[0]
    assert intent == "consulta"


def test_producto_agotado_ofrece_alternativa(srv):
    srv.webhook("tienen el vestido floral?")
    resp = srv.last_reply()
    assert "agotado" in resp and "Vestido lino beige" in resp and "$119.900" in resp


def test_faq_envios_y_pagos_sin_cambiar_de_etapa(srv):
    srv.webhook("cómo son los envíos a Bogotá?")
    assert "transportadora" in srv.last_reply()
    srv.webhook("se puede pagar por nequi?")
    assert "Nequi" in srv.last_reply()
    assert srv.db().execute("SELECT etapa FROM conversacion").fetchone()["etapa"] == "nuevo"


def test_precio_actualizado_se_refleja_en_la_siguiente_respuesta(srv, owner):
    tk = srv.login(owner)
    status, data = srv.api("GET", "/api/productos", tk)
    pid = next(p["id"] for p in data["productos"] if p["nombre"] == "Gorra clásica negra")
    srv.webhook("precio de la gorra clasica")
    assert "$34.900" in srv.last_reply()
    assert srv.api("PATCH", f"/api/productos/{pid}", tk, {"precio_cop": 39900})[0] == 200
    srv.webhook("precio de la gorra clasica")
    assert "$39.900" in srv.last_reply() and "$34.900" not in srv.last_reply()


# ------------------------------------------------------------------ flujo principal: pedido de punta a punta (HU-03)
def test_flujo_de_pedido_de_extremo_a_extremo(srv, owner):
    srv.webhook("hola buenas")
    assert "asistente virtual" in srv.last_reply()
    srv.webhook("quiero la camiseta oversize negra")
    assert "talla" in srv.last_reply() and "cantidad" in srv.last_reply() and "ciudad" in srv.last_reply()
    srv.webhook("talla M")
    assert "cantidad" in srv.last_reply() and "talla (" not in srv.last_reply()
    srv.webhook("2")
    assert "ciudad" in srv.last_reply()
    r = srv.webhook("Cartagena")
    assert r["intencion"] == "pedido" and r["pedido_id"]
    assert "$119.800" in srv.last_reply() and "datos de pago" in srv.last_reply()

    tk = srv.login(owner)
    _, ped = srv.api("GET", "/api/pedidos", tk)
    p = ped["pedidos"][0]
    assert p["estado"] == "preliminar" and p["ciudad"] == "Cartagena" and p["total_cop"] == 119800
    assert p["items"] == [{"producto": "Camiseta oversize negra", "talla": "M", "cantidad": 2, "precio_unitario_cop": 59900}]
    _, emb = srv.api("GET", "/api/embudo", tk)
    assert emb["totales"]["negociando"] == 1
    # el borrador se limpia: otra pregunta no vuelve a registrar el pedido
    srv.webhook("gracias")
    assert srv.db().execute("SELECT COUNT(*) FROM pedido").fetchone()[0] == 1


def test_pedido_con_cantidad_mayor_al_stock_no_se_registra(srv):
    srv.webhook("quiero 5 gorras clasicas")
    assert "Solo quedan 3" in srv.last_reply()
    assert srv.db().execute("SELECT COUNT(*) FROM pedido").fetchone()[0] == 0


def test_talla_inexistente_se_rechaza(srv):
    srv.webhook("quiero la camiseta basica blanca talla XL")
    assert "no está disponible" in srv.last_reply()


# ------------------------------------------------------------------ CU-04 / HU-04..06: traspaso a humano
def test_traspaso_y_atencion_humana_completa(srv, owner, seller):
    srv.webhook("quiero la camiseta oversize negra talla L")
    n_antes = len(srv.sender.outbox)
    r = srv.webhook("esto es un desastre, tengo una queja")
    assert r["estado"] == "traspasado" and r["motivo"] == "queja"
    assert "persona del equipo" in srv.last_reply()
    # mientras esta en modo humano la IA no responde, pero el panel se entera
    enviados = len(srv.sender.outbox)
    r = srv.webhook("hola? alguien?")
    assert r["estado"] == "notificado_asesor" and len(srv.sender.outbox) == enviados > n_antes

    tk = srv.login(seller)
    _, lista = srv.api("GET", "/api/conversaciones?atencion=1", tk)
    assert lista["pendientes_asesor"] == 1
    cid = lista["conversaciones"][0]["id"]
    # no se puede responder sin tomar el control
    assert srv.api("POST", f"/api/conversaciones/{cid}/responder", tk, {"texto": "hola"})[0] == 409
    assert srv.api("POST", f"/api/conversaciones/{cid}/tomar-control", tk)[0] == 200
    assert srv.api("POST", f"/api/conversaciones/{cid}/responder", tk, {"texto": "Hola Ana, soy Carlos. Cuéntame qué pasó."})[0] == 200
    assert srv.last_reply().startswith("Hola Ana, soy Carlos")
    # el humano mueve al cliente de etapa a mano; queda el registro
    assert srv.api("PATCH", f"/api/conversaciones/{cid}/etapa", tk, {"etapa": "interesado"})[0] == 200
    assert srv.api("POST", f"/api/conversaciones/{cid}/devolver-ia", tk)[0] == 200

    r = srv.webhook("cuánto vale la gorra clásica negra")
    assert r["estado"] == "respondido" and "$34.900" in srv.last_reply()
    _, det = srv.api("GET", f"/api/conversaciones/{cid}", tk)
    quien = [m["remitente"] for m in det["mensajes"]]
    assert quien.count("humano") == 1 and quien.count("ia") >= 3 and quien.count("cliente") == 4
    assert any(e["origen"] == "manual" and e["etapa_anterior"] == "negociando" and e["etapa_nueva"] == "interesado" for e in det["eventos_embudo"])


def test_solicitud_de_asesor(srv):
    r = srv.webhook("quiero hablar con un asesor por favor")
    assert r["estado"] == "traspasado" and r["motivo"] == "solicitud_cliente"
    assert srv.db().execute("SELECT modo, requiere_atencion FROM conversacion").fetchone()["modo"] == "humano"


def test_sin_informacion_dos_veces_pasa_a_una_persona(srv):
    srv.webhook("tienen bicicletas?")
    assert "catálogo" in srv.last_reply()
    r = srv.webhook("y motos?")
    assert r["estado"] == "traspasado" and r["motivo"] == "sin_informacion"


def test_aviso_de_espera_si_nadie_atiende(srv):
    srv.webhook("quiero un asesor")
    c = srv.db()
    svc = ConversationService(c, srv.sender, None, srv.settings)
    assert svc.procesar_esperas(datetime.now(timezone.utc) + timedelta(minutes=5)) == 0
    assert svc.procesar_esperas(datetime.now(timezone.utc) + timedelta(minutes=11)) == 1
    assert "Seguimos buscando" in srv.last_reply()
    assert svc.procesar_esperas(datetime.now(timezone.utc) + timedelta(minutes=30)) == 0  # solo una vez


def test_ia_desactivada_deja_todo_en_modo_humano(srv, owner):
    tk = srv.login(owner)
    assert srv.api("PATCH", "/api/negocio", tk, {"ia_activa": 0})[0] == 200
    r = srv.webhook("hola")
    assert r["estado"] == "notificado_asesor" and srv.sender.outbox == []


def test_tono_formal(srv, owner):
    tk = srv.login(owner)
    srv.api("PATCH", "/api/negocio", tk, {"tono": "formal"})
    srv.webhook("hola")
    assert "Puedo ayudarle" in srv.last_reply()


# ------------------------------------------------------------------ RNF-05: la IA no inventa
class MentirosoProvider:
    def generate(self, req):
        return LLMResult("consulta", "Esa camiseta cuesta solo $1.000 y es tuya.")


class CaidoProvider:
    def generate(self, req):
        raise TimeoutError("sin red")


def test_precio_inventado_por_el_modelo_se_bloquea(make_srv):
    h = make_srv(llm=MentirosoProvider())
    r = h.webhook("cuanto vale la camiseta oversize negra")
    assert r["estado"] == "traspasado" and r["motivo"] == "respuesta_no_verificada"
    assert "$1.000" not in h.last_reply()


def test_si_el_modelo_falla_se_pasa_a_una_persona(make_srv):
    h = make_srv(llm=CaidoProvider())
    r = h.webhook("hola")
    assert r["estado"] == "traspasado" and r["motivo"] == "falla_llm"


def test_en_50_mensajes_de_catalogo_ningun_precio_se_aparta_del_catalogo(srv):
    productos = srv.db().execute("SELECT nombre, precio_cop FROM producto WHERE stock > 0").fetchall()
    validos = {p["precio_cop"] for p in productos} | {p["precio_cop"] * q for p in productos for q in range(2, 100)}
    from app.textutil import precios_en_texto
    for i in range(50):
        p = productos[i % len(productos)]
        srv.webhook(f"cuanto cuesta {p['nombre']}", wa_from=f"57300000{i:04d}")
        assert all(v in validos for v in precios_en_texto(srv.last_reply()))
        assert f"${p['precio_cop']:,}".replace(",", ".") in srv.last_reply()


# ------------------------------------------------------------------ RF-10 / RNF-07: autenticacion y aislamiento por negocio
def test_endpoints_exigen_autenticacion(srv):
    assert srv.api("GET", "/api/conversaciones")[0] == 401
    assert srv.api("GET", "/api/conversaciones", "token-falso")[0] == 401
    assert srv.api("POST", "/api/auth/login", body={"correo": OWNER[0], "password": "mala"})[0] == 401


def test_un_negocio_no_ve_los_datos_de_otro(srv):
    srv.webhook("hola")
    c = srv.db()
    cur = c.execute("INSERT INTO negocio (nombre, whatsapp_phone_number_id, creado_en) VALUES ('Otro','555','2026-01-01')")
    c.execute("INSERT INTO usuario (negocio_id, nombre, correo, password_hash, rol, creado_en) VALUES (?,?,?,?,?,?)",
              (cur.lastrowid, "Otro Dueño", "otro@x.test", hash_password("clave12345"), "propietario", "2026-01-01"))
    c.commit()
    tk = srv.login(("otro@x.test", "clave12345"))
    assert srv.api("GET", "/api/conversaciones", tk)[1]["conversaciones"] == []
    cid = srv.db().execute("SELECT id FROM conversacion").fetchone()["id"]
    assert srv.api("GET", f"/api/conversaciones/{cid}", tk)[0] == 404
    assert srv.api("POST", f"/api/conversaciones/{cid}/tomar-control", tk)[0] == 404
    assert srv.api("GET", "/api/productos", tk)[1]["productos"] == []


def test_solo_el_propietario_cambia_la_configuracion(srv, seller):
    tk = srv.login(seller)
    assert srv.api("PATCH", "/api/negocio", tk, {"tono": "formal"})[0] == 403


# ------------------------------------------------------------------ RNF-11: trazabilidad
def test_los_mensajes_no_se_pueden_modificar_ni_borrar(srv):
    srv.webhook("hola")
    c = srv.db()
    with pytest.raises(sqlite3.DatabaseError, match="inmutable"):
        c.execute("UPDATE mensaje SET texto = 'editado' WHERE id = 1")
    with pytest.raises(sqlite3.DatabaseError, match="inmutable"):
        c.execute("UPDATE mensaje SET remitente = 'humano', usuario_id = 1 WHERE id = 1")
    with pytest.raises(sqlite3.DatabaseError, match="inmutable"):
        c.execute("DELETE FROM mensaje WHERE id = 1")


def test_una_sola_conversacion_abierta_por_cliente_y_se_cierra_con_la_etapa(srv, owner):
    srv.webhook("precio de la gorra clasica")
    tk = srv.login(owner)
    cid = srv.api("GET", "/api/conversaciones", tk)[1]["conversaciones"][0]["id"]
    c = srv.db()
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO conversacion (negocio_id, cliente_id, creada_en) SELECT negocio_id, cliente_id, '2026' FROM conversacion")
    c.rollback()
    c.close()
    srv.api("PATCH", f"/api/conversaciones/{cid}/etapa", tk, {"etapa": "cerrado"})
    srv.webhook("hola otra vez")
    n = srv.db().execute("SELECT COUNT(*) FROM conversacion").fetchone()[0]
    assert n == 2  # la cerrada y una nueva


def test_metricas_del_panel(srv, owner):
    srv.webhook("precio de la gorra clasica", wa_from="573000000001")
    srv.webhook("quiero un asesor", wa_from="573000000002")
    tk = srv.login(owner)
    _, m = srv.api("GET", "/api/metricas", tk)
    assert m["conversaciones"] == 2 and m["leads_en_seguimiento"] == 1 and m["pendientes_asesor"] == 1
    assert m["tiempo_respuesta_promedio_seg"] is not None and m["tiempo_respuesta_promedio_seg"] < 8
