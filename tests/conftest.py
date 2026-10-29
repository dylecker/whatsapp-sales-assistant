from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import connect, init_db  # noqa: E402
from app.seed import OWNER, PHONE_NUMBER_ID, SELLER, seed  # noqa: E402
from app.security import sign_body  # noqa: E402
from app.whatsapp import SimulatedSender, build_payload  # noqa: E402


class Harness:
    """Servidor real en un hilo + utilidades para simular a Meta y al panel."""

    def __init__(self, settings: Settings, sender: SimulatedSender, base: str):
        self.settings, self.sender, self.base = settings, sender, base
        self._n = 0

    # --- HTTP crudo
    def http(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def api(self, method: str, path: str, token: str | None = None, body: dict | None = None):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        status, raw = self.http(method, path, json.dumps(body).encode() if body is not None else None, h)
        return status, (json.loads(raw) if raw else {})

    def login(self, creds) -> str:
        status, data = self.api("POST", "/api/auth/login", body={"correo": creds[0], "password": creds[1]})
        assert status == 200, data
        return data["token"]

    # --- Meta
    def webhook(self, texto: str, wa_from: str = "573001112233", nombre: str = "Ana Torres",
                phone_number_id: str = PHONE_NUMBER_ID, wa_id: str | None = None):
        self._n += 1
        payload = build_payload(phone_number_id, wa_from, nombre, wa_id or f"wamid.TEST{self._n:05d}", texto)
        raw = json.dumps(payload).encode()
        status, resp = self.http("POST", "/webhook", raw, {
            "Content-Type": "application/json", "X-Hub-Signature-256": sign_body(self.settings.app_secret, raw)})
        assert status == 200, resp
        return json.loads(resp)["resultados"][0]

    def last_reply(self) -> str:
        return self.sender.outbox[-1]["text"]

    def db(self):
        return connect(self.settings.db_path)


def _start(tmp_path, settings_kw=None, llm=None):
    settings = Settings(db_path=str(tmp_path / "test.db"), **(settings_kw or {}))
    sender = SimulatedSender()
    app = create_app(settings, sender=sender, llm=llm)
    c = connect(settings.db_path)
    seed(c)
    c.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    hilo = threading.Thread(target=server.run, daemon=True)
    hilo.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    return Harness(settings, sender, f"http://127.0.0.1:{port}"), server, hilo


@pytest.fixture
def srv(tmp_path):
    h, server, hilo = _start(tmp_path, {"require_consent": False})
    yield h
    server.should_exit = True
    hilo.join(timeout=5)


@pytest.fixture
def srv_consent(tmp_path):
    h, server, hilo = _start(tmp_path, {"require_consent": True})
    yield h
    server.should_exit = True
    hilo.join(timeout=5)


@pytest.fixture
def make_srv(tmp_path):
    """Para pruebas que necesitan un proveedor de LLM distinto."""
    creados = []

    def _make(llm=None, **kw):
        h, server, hilo = _start(tmp_path, {"require_consent": False, **kw}, llm=llm)
        creados.append((server, hilo))
        return h
    yield _make
    for server, hilo in creados:
        server.should_exit = True
        hilo.join(timeout=5)


@pytest.fixture
def owner():
    return OWNER


@pytest.fixture
def seller():
    return SELLER
