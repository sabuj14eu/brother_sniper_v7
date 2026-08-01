"""Password hashing, session JWTs, TOTP 2FA, OTP codes, credential encryption.

Standard-library crypto only (scrypt, HMAC) plus PyJWT — no heavyweight deps.
MT5 credentials are encrypted at rest with an HMAC-derived stream keyed off
BB_SECRET_KEY (swap for KMS/Fernet in production without touching callers).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings

# --- passwords -------------------------------------------------------------

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# --- session tokens (JWT cookies) -----------------------------------------


def create_session_token(user_id: int, role: str, session_id: str) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "role": role,
        "sid": session_id,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=s.session_ttl_hours),
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_session_token(token: str) -> dict | None:
    for key in get_settings().all_secret_keys:
        try:
            return jwt.decode(token, key, algorithms=["HS256"])
        except jwt.PyJWTError:
            continue
    return None


# --- OTP codes -------------------------------------------------------------


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(phone: str, code: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


# --- TOTP (RFC 6238) -------------------------------------------------------


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp_code(secret: str, at: int | None = None, step: int = 30) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((at or time.time()) // step)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    now = int(time.time())
    return any(hmac.compare_digest(totp_code(secret, now + drift * 30), code) for drift in range(-window, window + 1))


def totp_uri(secret: str, label: str) -> str:
    return f"otpauth://totp/BrotherBot:{label}?secret={secret}&issuer=BrotherBot"


# --- API keys --------------------------------------------------------------


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, key_hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    full = f"bb_{raw}"
    return full, full[:11], hashlib.sha256(full.encode()).hexdigest()


def hash_api_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


# --- symmetric credential encryption ---------------------------------------


def _keystream(key: str, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(key.encode(), nonce + struct.pack(">I", counter), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def encrypt_secret(plaintext: str) -> str:
    key = get_settings().secret_key
    nonce = os.urandom(12)
    data = plaintext.encode()
    ct = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
    mac = hmac.new(key.encode(), nonce + ct, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + mac + ct).decode()


def decrypt_secret(token: str) -> str:
    """Tries the current key, then rotated-out keys (BB_OLD_SECRET_KEYS), so
    stored credentials survive a rotation. Re-save re-encrypts with the new key."""
    raw = base64.b64decode(token)
    nonce, mac, ct = raw[:12], raw[12:28], raw[28:]
    for key in get_settings().all_secret_keys:
        expected = hmac.new(key.encode(), nonce + ct, hashlib.sha256).digest()[:16]
        if hmac.compare_digest(mac, expected):
            return bytes(a ^ b for a, b in zip(ct, _keystream(key, nonce, len(ct)))).decode()
    raise ValueError("credential MAC mismatch (no key matches)")


def mask_secret(value: str, keep: int = 3) -> str:
    if len(value) <= keep:
        return "•" * len(value)
    return value[:keep] + "•" * 6
