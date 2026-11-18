"""Argon2id passwords, strict HS256 JWTs and identifier digests."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_hex
from uuid import UUID

import jwt
from argon2.exceptions import InvalidHashError, VerificationError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import Settings

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Passwords must contain 12 to 128 characters")
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    if not 1 <= len(password) <= 128 or not hashed.startswith("$argon2id$"):
        return False
    try:
        return _password_hash.verify(password, hashed)
    except (UnknownHashError, InvalidHashError, VerificationError, ValueError, TypeError):
        return False


def digest_jti(jti: str) -> str:
    return hashlib.sha256(jti.encode("ascii")).hexdigest()


def signing_key(settings: Settings) -> str:
    if not settings.jwt_secret_key or not settings.jwt_secret_key.get_secret_value():
        raise ValueError("Authentication is not configured")
    return settings.jwt_secret_key.get_secret_value()


def csrf_token(session_id: UUID, settings: Settings) -> str:
    return hmac.new(
        signing_key(settings).encode(), f"csrf:{session_id}".encode(), hashlib.sha256
    ).hexdigest()


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    session_id: UUID
    jti: str
    expires_at: datetime


def encode_token(
    user_id: UUID,
    session_id: UUID,
    token_type: str,
    issued_at: datetime,
    expires_at: datetime,
    settings: Settings,
) -> tuple[str, str]:
    if token_type not in ("access", "refresh"):
        raise ValueError("Unsupported token type")
    jti = token_hex(32)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "jti": jti,
        "type": token_type,
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, signing_key(settings), algorithm="HS256"), jti


def decode_token(token: str, expected_type: str, settings: Settings) -> TokenClaims:
    try:
        if len(token) > 8192:
            raise ValueError("Token too long")
        payload = jwt.decode(
            token,
            signing_key(settings),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "require": ["sub", "sid", "jti", "type", "iat", "nbf", "exp", "iss", "aud"],
                "strict_aud": True,
            },
        )
        if payload["type"] != expected_type:
            raise ValueError("Wrong token type")
        if not isinstance(payload["sub"], str) or not isinstance(payload["sid"], str):
            raise ValueError("Token subject and session must be UUID strings")
        for key in ("iat", "nbf", "exp"):
            if type(payload[key]) is not int or payload[key] < 0:
                raise ValueError("NumericDate must be an integer")
        if not payload["iat"] <= payload["nbf"] < payload["exp"]:
            raise ValueError("Invalid timestamp order")
        jti = payload["jti"]
        if (
            not isinstance(jti, str)
            or len(jti) != 64
            or any(character not in "0123456789abcdef" for character in jti)
        ):
            raise ValueError("Invalid token identifier")
        return TokenClaims(
            user_id=UUID(payload["sub"]),
            session_id=UUID(payload["sid"]),
            jti=jti,
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError, OverflowError, OSError) as exc:
        raise ValueError("Invalid or expired authentication") from exc
