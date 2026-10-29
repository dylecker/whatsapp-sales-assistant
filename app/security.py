"""Seguridad: firma del webhook, hash de contrasenas y tokens JWT (RNF-03)."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """Valida X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app_secret, cuerpo)."""
    if not header or not header.startswith("sha256="):
        return False
    esperado = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, header[len("sha256="):])


def sign_body(app_secret: str, raw_body: bytes) -> str:
    return "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()


_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def create_token(secret: str, ttl_min: int, usuario_id: int, negocio_id: int, rol: str) -> str:
    ahora = datetime.now(timezone.utc)
    payload = {"sub": str(usuario_id), "negocio_id": negocio_id, "rol": rol,
               "iat": ahora, "exp": ahora + timedelta(minutes=ttl_min)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(secret: str, token: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
