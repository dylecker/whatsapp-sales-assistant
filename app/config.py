from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("WSA_DB_PATH", "wsa.db"))
    # Secreto de la app de Meta: firma X-Hub-Signature-256 del webhook
    app_secret: str = field(default_factory=lambda: os.getenv("WSA_APP_SECRET", "dev-app-secret"))
    # Token que se configura en el panel de Meta para verificar el webhook (GET)
    verify_token: str = field(default_factory=lambda: os.getenv("WSA_VERIFY_TOKEN", "dev-verify-token"))
    jwt_secret: str = field(default_factory=lambda: os.getenv("WSA_JWT_SECRET", "dev-jwt-secret-change-me-0123456789"))
    jwt_ttl_min: int = 60
    require_consent: bool = True
    timezone: str = "America/Bogota"
    # Proveedor de LLM: "reglas" (local, sin red) o "anthropic" (API, requiere clave)
    llm_provider: str = field(default_factory=lambda: os.getenv("WSA_LLM_PROVIDER", "reglas"))
    # Envio a WhatsApp: "simulado" (bandeja en memoria) o "cloud_api"
    sender: str = field(default_factory=lambda: os.getenv("WSA_SENDER", "simulado"))
