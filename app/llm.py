"""Capa de abstraccion del modelo de lenguaje (RNF-09).

El flujo principal solo conoce `LLMProvider.generate()`. Implementaciones:

* `RuleBasedProvider`: local, determinista y sin red. Redacta SOLO con el contexto
  recuperado (catalogo y preguntas frecuentes). Es lo que usan las pruebas y la demo.
* `AnthropicProvider`: llama a la API de Anthropic. Esta escrito pero NO se ejecuto en
  el entorno de desarrollo del avance (sin acceso a la red ni a clave de API).

Cualquier proveedor pasa por la misma validacion de veracidad en el servicio
(ningun precio puede salir de algo distinto al catalogo recuperado).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .textutil import cop, norm, tokens


@dataclass
class LLMRequest:
    negocio_nombre: str
    tono: str                       # 'cercano' | 'formal'
    mensaje: str
    historial: list[tuple[str, str]]  # (remitente, texto), del mas antiguo al mas reciente
    productos: list[dict]
    faqs: list[dict]
    borrador: dict                  # pedido en curso: producto_id, talla, cantidad, ciudad
    fuera_de_horario: bool = False
    horario: str = ""


@dataclass
class LLMResult:
    intencion: str                  # consulta | pedido | queja | solicitud_asesor | saludo | faq | otra
    respuesta: str
    borrador: dict = field(default_factory=dict)
    pedido_listo: bool = False
    requiere_humano: bool = False
    motivo: str | None = None
    sin_informacion: bool = False


class LLMProvider(Protocol):
    def generate(self, req: LLMRequest) -> LLMResult: ...


# ---------------------------------------------------------------- reglas (NLU simple)

CIUDADES = [
    "cartagena", "barranquilla", "bogota", "medellin", "cali", "santa marta", "bucaramanga",
    "monteria", "sincelejo", "valledupar", "cucuta", "pereira", "manizales", "armenia", "pasto",
    "villavicencio", "ibague", "neiva", "tunja", "riohacha", "popayan", "soledad", "turbaco",
]
NUMEROS = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
           "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
NUM_RE = r"(\d{1,2}|" + "|".join(NUMEROS) + r")"

RE_ASESOR = re.compile(
    r"\b(asesor\w*|agente humano|un humano|persona real)\b|"
    r"\b(hablar|comunicar\w*|pasar\w*|contactar\w*|atienda|atender)\b.{0,30}\b(persona|humano|vendedor\w*|encargad\w*|alguien|agente)\b")
RE_QUEJA = re.compile(
    r"\b(queja|reclamo|mal servicio|pesim\w+|no me llego|no llego|defectuos\w+|danad\w+|estafa|"
    r"inconform\w+|molest\w+|nadie responde|me enviaron mal|equivocad\w+|incumpl\w+)\b")
RE_COMPRA = re.compile(
    r"\b(quiero (comprar|pedir|llevar|ordenar|un|una|dos|tres|\d+|el|la|los|las)\b|me (lo |la |los |las )?llevo|"
    r"lo (quiero|compro)|la (quiero|compro)|los (quiero|compro)|voy a (comprar|llevar)|"
    r"hacer (un )?pedido|separ[ae]me|apartame|quisiera (comprar|pedir|llevar))\b")
RE_SALUDO = re.compile(r"^(hola|buenas|buenos dias|buen dia|buenas tardes|buenas noches|hey|ola)\b")
RE_DESPEDIDA = re.compile(r"\b(gracias|chao|hasta luego|listo gracias|ok gracias|vale gracias)\b")


def _extraer_talla(t: str, producto: dict | None, hay_borrador: bool) -> str | None:
    m = re.search(r"\b(?:talla|tll|en)\s+(xxl|xl|xs|s|m|l|\d{2})\b", t)
    if m:
        return m.group(1).upper()
    solo = t.strip()
    if re.fullmatch(r"(xxl|xl|xs|s|m|l)", solo):
        return solo.upper()
    if hay_borrador and re.fullmatch(r"\d{2}", solo) and producto and solo in producto["tallas"]:
        return solo
    return None


def _extraer_cantidad(t: str, producto: dict | None, hay_borrador: bool, talla: str | None) -> int | None:
    sin_talla = re.sub(r"\b(?:talla|tll)\s+\w+\b", " ", t)
    solo = sin_talla.strip()
    if hay_borrador and re.fullmatch(NUM_RE, solo):
        n = NUMEROS.get(solo) or int(solo)
        if not (talla and solo == talla):
            return n
    sustantivos = ["unidad\\w*", "und", "pares?"]
    if producto:
        sustantivos += [re.escape(tk) + r"\w*" for tk in tokens(producto["nombre"])]
    m = re.search(r"\b" + NUM_RE + r"\s+(?:" + "|".join(sustantivos) + r")\b", sin_talla)
    if not m:
        m = re.search(r"\b(?:quiero|llevo|pido|necesito|comprar|pedir)\s+" + NUM_RE + r"\b", sin_talla)
    if m:
        v = m.group(1)
        return NUMEROS.get(v) or int(v)
    return None


def _extraer_ciudad(t: str) -> str | None:
    for c in CIUDADES:
        if re.search(r"\b" + c + r"\b", t):
            return c.title()
    return None


class RuleBasedProvider:
    """Redacta respuestas solo con los datos recuperados (catalogo y FAQ)."""

    def generate(self, req: LLMRequest) -> LLMResult:
        t = norm(req.mensaje)
        formal = req.tono == "formal"

        def T(cercano: str, formal_txt: str) -> str:
            return formal_txt if formal else cercano

        if RE_ASESOR.search(t):
            return self._traspaso(req, "solicitud_asesor", "solicitud_cliente",
                                  T("Claro, te paso con una persona del equipo.",
                                    "Con gusto, lo comunico con una persona del equipo."))
        if RE_QUEJA.search(t):
            return self._traspaso(req, "queja", "queja",
                                  T("Lamento lo que pasó. Voy a pasar tu caso a una persona del equipo para que lo revise contigo.",
                                    "Lamento lo ocurrido. Trasladaré su caso a una persona del equipo para que lo revise con usted."))

        borrador = dict(req.borrador or {})
        hay_borrador = bool(borrador.get("producto_id"))
        candidatos = [p for p in req.productos if p["score"] > 0]
        candidatos.sort(key=lambda p: -p["score"])
        producto = None
        ambiguos: list[dict] = []
        if candidatos:
            if len(candidatos) == 1 or candidatos[0]["score"] > candidatos[1]["score"]:
                producto = candidatos[0]
            else:
                tope = candidatos[0]["score"]
                ambiguos = [p for p in candidatos if p["score"] == tope][:3]
        elif hay_borrador:
            producto = next((p for p in req.productos if p["id"] == borrador["producto_id"]), None)

        talla = _extraer_talla(t, producto, hay_borrador)
        cantidad = _extraer_cantidad(t, producto, hay_borrador, talla)
        ciudad = _extraer_ciudad(t)
        compra = bool(RE_COMPRA.search(t))
        hay_slots = any([talla, cantidad, ciudad])

        # --- flujo de pedido
        if (compra or (hay_borrador and hay_slots)) and (producto or ambiguos or hay_borrador):
            if ambiguos:
                return LLMResult("pedido", self._lista(ambiguos, T, "¿Cuál de estos quieres?",
                                                       "¿Cuál de estos desea?"), borrador)
            if producto is None:
                return LLMResult("pedido", T("¿Qué producto quieres pedir?", "¿Qué producto desea pedir?"), borrador)
            return self._pedido(req, producto, borrador, talla, cantidad, ciudad, T)

        partes: list[str] = []
        intencion = "otra"
        # --- consulta de producto
        if ambiguos:
            partes.append(self._lista(ambiguos, T, "¿Cuál te interesa?", "¿Cuál le interesa?"))
            intencion = "consulta"
        elif producto:
            partes.append(self._detalle(producto, req.productos, T))
            intencion = "consulta"
        # --- preguntas frecuentes
        faq = max(req.faqs, key=lambda f: f["score"]) if req.faqs else None
        if faq:
            partes.append(faq["respuesta"])
            intencion = intencion if intencion == "consulta" else "faq"
        if partes:
            return LLMResult(intencion, "\n\n".join(partes), borrador)

        if RE_SALUDO.search(t):
            return LLMResult("saludo", T(
                f"¡Hola! Soy el asistente virtual de {req.negocio_nombre}. Puedo ayudarte con precios, tallas, "
                "disponibilidad, envíos y pedidos. ¿Qué estás buscando?",
                f"Buenas. Soy el asistente virtual de {req.negocio_nombre}. Puedo ayudarle con precios, tallas, "
                "disponibilidad, envíos y pedidos. ¿Qué está buscando?"), borrador)
        if RE_DESPEDIDA.search(t):
            return LLMResult("otra", T("¡Con gusto! Aquí estoy si necesitas algo más.",
                                       "Con gusto. Quedo atento si necesita algo más."), borrador)
        return LLMResult("otra", T(
            "No encontré eso en nuestro catálogo ni en las preguntas frecuentes. ¿Me dices el nombre o el tipo de producto?",
            "No encontré eso en nuestro catálogo ni en las preguntas frecuentes. ¿Me indica el nombre o el tipo de producto?"),
            borrador, sin_informacion=True)

    # ---- piezas
    def _traspaso(self, req: LLMRequest, intencion: str, motivo: str, frase: str) -> LLMResult:
        extra = ""
        if req.fuera_de_horario:
            extra = f" Nuestro horario de atención es {req.horario}; te responderán apenas abramos."
        cola = " Mientras tanto no te responderé yo, para que no se crucen los mensajes."
        return LLMResult(intencion, frase + extra + cola, dict(req.borrador or {}),
                         requiere_humano=True, motivo=motivo)

    @staticmethod
    def _tallas(p: dict) -> str:
        return ", ".join(p["tallas"]) if p["tallas"] and p["tallas"] != ["unica"] else ""

    def _detalle(self, p: dict, todos: list[dict], T) -> str:
        if p["stock"] <= 0:
            alt = next((a for a in todos if a["id"] != p["id"] and a["categoria"] == p["categoria"] and a["stock"] > 0), None)
            txt = f"Por ahora {p['nombre']} está agotado."
            if alt:
                tallas = self._tallas(alt)
                txt += (f" Te puedo ofrecer {alt['nombre']} a {cop(alt['precio_cop'])}"
                        + (f" (tallas {tallas})" if tallas else "") + T(". ¿Te sirve?", ". ¿Le sirve?"))
            return txt
        tallas = self._tallas(p)
        txt = f"{p['nombre']}: {cop(p['precio_cop'])}"
        if tallas:
            txt += f". Tallas: {tallas}"
        txt += ". " + (f"Quedan pocas unidades ({p['stock']})." if p["stock"] <= 3 else f"Hay {p['stock']} unidades disponibles.")
        return txt

    def _lista(self, productos: list[dict], T, pregunta_c: str, pregunta_f: str) -> str:
        lineas = [f"- {p['nombre']}: {cop(p['precio_cop'])}" + ("" if p["stock"] > 0 else " (agotado)") for p in productos]
        return T("Tengo estas opciones:\n", "Contamos con estas opciones:\n") + "\n".join(lineas) + "\n" + T(pregunta_c, pregunta_f)

    def _pedido(self, req, p: dict, borrador: dict, talla, cantidad, ciudad, T) -> LLMResult:
        if borrador.get("producto_id") != p["id"]:
            borrador = {"ciudad": borrador.get("ciudad")} if borrador.get("ciudad") else {}
            borrador["producto_id"] = p["id"]
        if p["stock"] <= 0:
            return LLMResult("pedido", self._detalle(p, req.productos, T), {})
        if talla:
            if p["tallas"] and p["tallas"] != ["unica"] and talla not in p["tallas"]:
                return LLMResult("pedido", f"La talla {talla} no está disponible para {p['nombre']}. Tallas: {self._tallas(p)}.", borrador)
            borrador["talla"] = talla
        if cantidad:
            if cantidad > p["stock"]:
                return LLMResult("pedido", f"Solo quedan {p['stock']} unidades de {p['nombre']}. " +
                                 T("¿Quieres ajustar la cantidad?", "¿Desea ajustar la cantidad?"), borrador)
            borrador["cantidad"] = cantidad
        if ciudad:
            borrador["ciudad"] = ciudad
        sin_talla = p["tallas"] and p["tallas"] != ["unica"]
        faltan = []
        if sin_talla and not borrador.get("talla"):
            faltan.append(f"talla ({self._tallas(p)})")
        if not borrador.get("cantidad"):
            faltan.append("cantidad")
        if not borrador.get("ciudad"):
            faltan.append("ciudad de envío")
        if faltan:
            lista = ", ".join(faltan[:-1]) + (" y " if len(faltan) > 1 else "") + faltan[-1]
            return LLMResult("pedido", f"Perfecto, vamos con {p['nombre']} ({cop(p['precio_cop'])}). " +
                             T(f"Para registrar tu pedido me falta: {lista}.", f"Para registrar su pedido me falta: {lista}."),
                             borrador)
        total = p["precio_cop"] * borrador["cantidad"]
        det = f" talla {borrador['talla']}" if borrador.get("talla") else ""
        txt = (f"Listo, registré tu pedido preliminar: {borrador['cantidad']} x {p['nombre']}{det} = {cop(total)}, "
               f"envío a {borrador['ciudad']}. No necesitas dar datos de pago por aquí: una persona del equipo "
               "te contactará para confirmar el envío y el pago. ¿Algo más?")
        if req.tono == "formal":
            txt = txt.replace("tu pedido", "su pedido").replace("te contactará", "lo contactará").replace("necesitas", "necesita").replace("¿Algo más?", "¿Algo más en lo que pueda ayudarle?")
        return LLMResult("pedido", txt, borrador, pedido_listo=True)


# ---------------------------------------------------------------- Anthropic (no ejecutado en el avance)

SYSTEM_PROMPT = (
    "Eres el asistente de ventas por WhatsApp de un negocio pequeno en Colombia. Responde en espanol, corto y claro. "
    "Usa EXCLUSIVAMENTE los productos y preguntas frecuentes del contexto: nunca inventes precios, tallas, stock ni politicas. "
    "Si falta informacion, pon sin_informacion=true. Si el cliente pide un asesor o se queja, pon requiere_humano=true. "
    "Responde SOLO un JSON con las claves: intencion, respuesta, borrador, pedido_listo, requiere_humano, motivo, sin_informacion."
)


class AnthropicProvider:
    """Proveedor por API. Requiere ANTHROPIC_API_KEY. No se ejecuto en este avance."""

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: int = 20):
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self.model = model or os.getenv("WSA_LLM_MODEL", "claude-sonnet-5-5")
        self.timeout = timeout

    def generate(self, req: LLMRequest) -> LLMResult:
        contexto = {
            "negocio": req.negocio_nombre, "tono": req.tono, "mensaje_cliente": req.mensaje,
            "historial": req.historial[-8:], "borrador_pedido": req.borrador,
            "productos": [{k: p[k] for k in ("id", "nombre", "precio_cop", "tallas", "stock")} for p in req.productos],
            "preguntas_frecuentes": [{"tema": f["tema"], "respuesta": f["respuesta"]} for f in req.faqs],
        }
        cuerpo = json.dumps({"model": self.model, "max_tokens": 600, "system": SYSTEM_PROMPT,
                             "messages": [{"role": "user", "content": json.dumps(contexto, ensure_ascii=False)}]}).encode()
        http = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=cuerpo, method="POST",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(http, timeout=self.timeout) as r:
            data = json.loads(r.read())
        texto = "".join(b.get("text", "") for b in data.get("content", []))
        crudo = json.loads(texto[texto.index("{"): texto.rindex("}") + 1])
        return LLMResult(
            intencion=crudo.get("intencion", "otra"), respuesta=crudo["respuesta"],
            borrador=crudo.get("borrador") or {}, pedido_listo=bool(crudo.get("pedido_listo")),
            requiere_humano=bool(crudo.get("requiere_humano")), motivo=crudo.get("motivo"),
            sin_informacion=bool(crudo.get("sin_informacion")))


def build_provider(nombre: str) -> LLMProvider:
    if nombre == "anthropic":
        return AnthropicProvider()
    return RuleBasedProvider()
