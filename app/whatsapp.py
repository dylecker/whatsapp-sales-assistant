"""Integracion con WhatsApp Business Platform (Cloud API de Meta)."""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Inbound:
    phone_number_id: str
    wa_from: str
    wa_name: str | None
    wa_message_id: str
    tipo: str
    texto: str | None


def parse_webhook(payload: dict) -> list[Inbound]:
    """Extrae los mensajes entrantes del JSON del webhook. Ignora los 'statuses'."""
    salida: list[Inbound] = []
    if payload.get("object") != "whatsapp_business_account":
        return salida
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            valor = change.get("value", {})
            pid = valor.get("metadata", {}).get("phone_number_id")
            nombres = {c.get("wa_id"): c.get("profile", {}).get("name") for c in valor.get("contacts", [])}
            for m in valor.get("messages", []):
                tipo = m.get("type", "")
                texto = m.get("text", {}).get("body") if tipo == "text" else None
                salida.append(Inbound(pid, m.get("from", ""), nombres.get(m.get("from")), m.get("id", ""), tipo, texto))
    return salida


def build_payload(phone_number_id: str, wa_from: str, name: str, wa_id: str, texto: str) -> dict:
    """Arma un webhook con el mismo formato que envia Meta (para pruebas y demo)."""
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA-DEMO", "changes": [{
        "field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "573000000000", "phone_number_id": phone_number_id},
            "contacts": [{"profile": {"name": name}, "wa_id": wa_from}],
            "messages": [{"from": wa_from, "id": wa_id, "timestamp": "1761690000",
                          "type": "text", "text": {"body": texto}}]}}]}]}


class WhatsAppSender(Protocol):
    def send_text(self, phone_number_id: str, to: str, text: str) -> str: ...


class SimulatedSender:
    """Guarda los mensajes salientes en memoria (pruebas y demo sin cuenta de Meta)."""

    def __init__(self) -> None:
        self.outbox: list[dict] = []

    def send_text(self, phone_number_id: str, to: str, text: str) -> str:
        wa_id = f"wamid.SIM{len(self.outbox) + 1:05d}"
        self.outbox.append({"phone_number_id": phone_number_id, "to": to, "text": text, "wa_id": wa_id})
        return wa_id


class CloudApiSender:
    """Envio real por la Cloud API. Requiere WHATSAPP_TOKEN. No se ejecuto en este avance."""

    def __init__(self, token: str | None = None, version: str | None = None) -> None:
        self.token = token or os.environ["WHATSAPP_TOKEN"]
        self.version = version or os.getenv("WSA_WA_API_VERSION", "v21.0")

    def send_text(self, phone_number_id: str, to: str, text: str) -> str:
        cuerpo = json.dumps({"messaging_product": "whatsapp", "to": to, "type": "text",
                             "text": {"body": text}}).encode()
        req = urllib.request.Request(
            f"https://graph.facebook.com/{self.version}/{phone_number_id}/messages", data=cuerpo, method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())["messages"][0]["id"]


def build_sender(nombre: str) -> WhatsAppSender:
    return CloudApiSender() if nombre == "cloud_api" else SimulatedSender()
