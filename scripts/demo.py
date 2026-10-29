"""Demostracion de extremo a extremo.

Levanta el servidor real, simula los webhooks firmados que enviaria Meta y usa la API del
panel como lo haria el propietario o el vendedor. Imprime la conversacion completa.

    python scripts/demo.py            # usa una base temporal
    python scripts/demo.py > docs/evidencia_demo.txt
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.seed import OWNER, PHONE_NUMBER_ID, SELLER, seed  # noqa: E402
from app.security import sign_body  # noqa: E402
from app.whatsapp import SimulatedSender, build_payload  # noqa: E402

ANCHO = 100


def linea(txt: str = "") -> None:
    print(txt, flush=True)


def titulo(txt: str) -> None:
    linea()
    linea("=" * ANCHO)
    linea(txt)
    linea("=" * ANCHO)


def envuelto(prefijo: str, texto: str) -> None:
    sangria = " " * len(prefijo)
    primero = True
    for parte in texto.split("\n"):
        palabras, actual = parte.split(" "), ""
        for p in palabras:
            if len(actual) + len(p) + 1 + len(prefijo) > ANCHO and actual:
                linea((prefijo if primero else sangria) + actual)
                primero, actual = False, p
            else:
                actual = (actual + " " + p).strip()
        linea((prefijo if primero else sangria) + actual)
        primero = False


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="wsa-demo-")
    settings = Settings(db_path=f"{tmp}/demo.db", require_consent=True)
    sender = SimulatedSender()
    app = create_app(settings, sender=sender)
    c = connect(settings.db_path)
    seed(c)
    c.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    contador = {"n": 0, "visto": 0}

    def http(method, path, body=None, headers=None):
        req = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def cliente(nombre: str, tel: str, texto: str) -> dict:
        contador["n"] += 1
        raw = json.dumps(build_payload(PHONE_NUMBER_ID, tel, nombre, f"wamid.DEMO{contador['n']:04d}", texto)).encode()
        envuelto(f"  {nombre.split()[0].upper()} (WhatsApp)  > ", texto)
        status, data = http("POST", "/webhook", raw, {"Content-Type": "application/json",
                                                      "X-Hub-Signature-256": sign_body(settings.app_secret, raw)})
        assert status == 200, data
        res = data["resultados"][0]
        while contador["visto"] < len(sender.outbox):
            envuelto("  ASISTENTE / EQUIPO < ", sender.outbox[contador["visto"]]["text"])
            contador["visto"] += 1
        linea(f"      [sistema] estado={res['estado']}" + "".join(
            f" {k}={res[k]}" for k in ("intencion", "motivo", "pedido_id") if res.get(k)))
        return res

    def panel(token, method, path, body=None):
        h = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        return http(method, path, json.dumps(body).encode() if body is not None else None, h)

    ana, luis = ("Ana Torres", "573001112233"), ("Luis Ortega", "573004445566")

    titulo("0. Seguridad del webhook: una peticion sin firma valida se rechaza")
    status, data = http("POST", "/webhook", b'{"object":"whatsapp_business_account","entry":[]}',
                        {"X-Hub-Signature-256": "sha256=" + "0" * 64})
    linea(f"  POST /webhook con firma falsa -> HTTP {status} {data}")

    titulo("1. Flujo 1 - Primer contacto, consentimiento (Ley 1581) y consulta de producto")
    cliente(*ana, "Hola, buenas tardes")
    cliente(*ana, "ACEPTO")
    cliente(*ana, "Hola! cuanto vale la camiseta oversize negra?")
    cliente(*ana, "y tienen el vestido floral?")
    cliente(*ana, "como son los envios?")

    titulo("2. Flujo 1 - Pedido preliminar completado en varios mensajes")
    cliente(*ana, "quiero la camiseta oversize negra")
    cliente(*ana, "talla M")
    cliente(*ana, "2")
    cliente(*ana, "Cartagena")

    titulo("3. Flujo 1 - Una queja pasa la conversacion a una persona (CU-04)")
    cliente(*luis, "hola")
    cliente(*luis, "ACEPTO")
    cliente(*luis, "tengo una queja, la ultima compra llego danada")
    linea("  (el cliente insiste mientras nadie ha tomado el chat: la IA no responde)")
    cliente(*luis, "hola? alguien me puede atender?")

    titulo("4. Flujo 2 - El vendedor atiende desde el panel")
    _, login = http("POST", "/api/auth/login", json.dumps({"correo": SELLER[0], "password": SELLER[1]}).encode(),
                    {"Content-Type": "application/json"})
    tk_v = login["token"]
    linea(f"  Login vendedor: {login['usuario']['nombre']} ({login['usuario']['rol']}), JWT de {len(tk_v)} caracteres")
    _, lista = panel(tk_v, "GET", "/api/conversaciones?atencion=1")
    linea(f"  Conversaciones que necesitan una persona: {lista['pendientes_asesor']}")
    for cv in lista["conversaciones"]:
        linea(f"    #{cv['id']} {cv['cliente']} ({cv['telefono']}) modo={cv['modo']} motivo={cv['motivo_traspaso']}"
              f" ultimo='{cv['ultimo_mensaje']}'")
    cid = lista["conversaciones"][0]["id"]
    linea(f"  POST /api/conversaciones/{cid}/tomar-control -> {panel(tk_v, 'POST', f'/api/conversaciones/{cid}/tomar-control')[0]}")
    texto = "Hola Luis, soy Carlos de Moda Caribe. Lamento lo ocurrido, cuentame que paso con la prenda."
    panel(tk_v, "POST", f"/api/conversaciones/{cid}/responder", {"texto": texto})
    contador["visto"] = len(sender.outbox) - 1
    while contador["visto"] < len(sender.outbox):
        envuelto("  CARLOS (humano) < ", sender.outbox[contador["visto"]]["text"])
        contador["visto"] += 1
    linea(f"  POST /api/conversaciones/{cid}/devolver-ia -> {panel(tk_v, 'POST', f'/api/conversaciones/{cid}/devolver-ia')[0]}")
    cliente(*luis, "gracias, cuanto cuesta la gorra clasica?")

    titulo("5. Panel del propietario - embudo, pedidos e indicadores")
    _, login = http("POST", "/api/auth/login", json.dumps({"correo": OWNER[0], "password": OWNER[1]}).encode(),
                    {"Content-Type": "application/json"})
    tk_o = login["token"]
    _, emb = panel(tk_o, "GET", "/api/embudo")
    linea("  Embudo (clientes por etapa): " + ", ".join(f"{k}={v}" for k, v in emb["totales"].items()))
    _, ped = panel(tk_o, "GET", "/api/pedidos")
    for p in ped["pedidos"]:
        its = "; ".join(f"{i['cantidad']} x {i['producto']} talla {i['talla']} a ${i['precio_unitario_cop']:,}".replace(",", ".")
                        for i in p["items"])
        linea(f"  Pedido #{p['id']} [{p['estado']}] {p['cliente']} -> {p['ciudad']}: {its} = ${p['total_cop']:,}".replace(",", "."))
    _, met = panel(tk_o, "GET", "/api/metricas")
    linea("  Indicadores: " + json.dumps(met, ensure_ascii=False))

    titulo("6. Trazabilidad - quien escribio cada mensaje (RNF-11), conversacion de Luis")
    _, det = panel(tk_o, "GET", f"/api/conversaciones/{cid}")
    for m in det["mensajes"]:
        quien = {"cliente": "cliente", "ia": "IA", "humano": f"humano(usuario {m['usuario_id']})"}[m["remitente"]]
        envuelto(f"  {m['creado_en'][11:19]} {quien:<18}| ", m["texto"])

    titulo("7. Datos guardados en la base")
    c = connect(settings.db_path)
    for tabla in ("negocio", "usuario", "cliente", "conversacion", "mensaje", "evento_embudo",
                  "producto", "pregunta_frecuente", "pedido", "item_pedido"):
        linea(f"  {tabla:<20}{c.execute(f'SELECT COUNT(*) FROM {tabla}').fetchone()[0]:>4} filas")
    c.close()
    server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
