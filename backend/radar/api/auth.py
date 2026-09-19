"""Autenticación y tokens criptográficos para Thinkuy (H3.2).

Implementación de tokens JWT estándar (HS256) usando la biblioteca estándar de Python
(hmac, hashlib, base64, json, time) sin dependencias externas pesadas.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from .. import config

router = APIRouter(tags=["auth"])


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64_decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def create_access_token(
    user_id: str,
    expires_in_seconds: int = 86400 * 30,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Crea un token JWT firmado criptográficamente con HMAC-SHA256."""
    clean_uid = str(user_id or "default").strip()
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": clean_uid,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    if metadata and isinstance(metadata, dict):
        payload["meta"] = metadata

    header_json = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    unsigned_token = f"{_b64_encode(header_json)}.{_b64_encode(payload_json)}"
    secret = config.SECRET_KEY.encode("utf-8")
    signature = hmac.new(secret, unsigned_token.encode("utf-8"), hashlib.sha256).digest()
    return f"{unsigned_token}.{_b64_encode(signature)}"


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Verifica y decodifica un token JWT. Retorna el payload si es válido, o None si expiró o está corrupto."""
    if not token or not isinstance(token, str):
        return None
    parts = token.strip().split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts
    unsigned_token = f"{header_b64}.{payload_b64}"
    secret = config.SECRET_KEY.encode("utf-8")
    expected_sig = hmac.new(secret, unsigned_token.encode("utf-8"), hashlib.sha256).digest()
    try:
        actual_sig = _b64_decode(sig_b64)
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, actual_sig):
        return None

    try:
        payload_raw = _b64_decode(payload_b64)
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return None

    # Verificar expiración
    exp = payload.get("exp")
    if exp and isinstance(exp, (int, float)):
        if time.time() > exp:
            return None

    return payload


def extract_user_from_request(request: Request) -> Dict[str, Any]:
    """Extrae el usuario autenticado desde cabeceras HTTP, token Bearer o query params."""
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:].strip()
        payload = verify_access_token(raw_token)
        if payload and payload.get("sub"):
            return {
                "user_id": payload["sub"],
                "authenticated": True,
                "auth_method": "bearer_jwt",
                "metadata": payload.get("meta", {}),
            }

    # Cabecera X-User-Id
    user_header = request.headers.get("X-User-Id")
    if user_header and user_header.strip():
        return {
            "user_id": user_header.strip(),
            "authenticated": True,
            "auth_method": "header_x_user_id",
            "metadata": {},
        }

    # Query param owner_id
    query_user = request.query_params.get("owner_id")
    if query_user and query_user.strip():
        return {
            "user_id": query_user.strip(),
            "authenticated": False,
            "auth_method": "query_param",
            "metadata": {},
        }

    # Default monousuario
    return {
        "user_id": "default",
        "authenticated": False,
        "auth_method": "default",
        "metadata": {},
    }


@router.post("/api/auth/token")
def issue_token_endpoint(payload: dict = Body(...)):
    """Genera un token de acceso firmado para un investigador o institución."""
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(400, "El campo 'user_id' es obligatorio.")
    expires_in = int(payload.get("expires_in_seconds") or (86400 * 30))
    metadata = payload.get("metadata") or {}
    token = create_access_token(user_id=user_id, expires_in_seconds=expires_in, metadata=metadata)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user_id,
        "expires_in_seconds": expires_in,
    }


@router.get("/api/auth/me")
def current_user_endpoint(request: Request):
    """Devuelve la información del usuario actual resolviendo token o cabeceras."""
    return extract_user_from_request(request)
