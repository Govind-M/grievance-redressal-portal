import time
from datetime import UTC, datetime, timedelta
from secrets import token_hex
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import (
    csrf_token,
    decode_token,
    digest_jti,
    encode_token,
    hash_password,
    verify_password,
)
from app.main import create_app

KEY = token_hex(48)


def settings(**overrides):
    return Settings(_env_file=None, jwt_secret_key=KEY, **overrides)


def payload():
    now = int(time.time())
    return {
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "jti": token_hex(32),
        "type": "access",
        "iat": now,
        "nbf": now,
        "exp": now + 900,
        "iss": "cm-kerala-grievance-api",
        "aud": "cm-kerala-grievance-client",
    }


def test_password_hashing_and_invalid_hash_handling():
    value = "Only-a-synthetic-test-password"
    hashed = hash_password(value)
    assert hashed.startswith("$argon2id$")
    assert verify_password(value, hashed)
    assert not verify_password("incorrect", hashed)
    for invalid in ("", "plain text", "$argon2id$broken", "$argon2id$v=19$m=bad"):
        assert not verify_password(value, invalid)
    for bad in ("short", "x" * 129):
        with pytest.raises(ValueError):
            hash_password(bad)


def test_token_claims_types_digests_and_stable_signing():
    user_id, sid = uuid4(), uuid4()
    now = datetime.now(UTC)
    first, jti = encode_token(user_id, sid, "access", now, now + timedelta(minutes=15), settings())
    claims = decode_token(first, "access", settings())
    assert claims.user_id == user_id and claims.session_id == sid
    assert claims.jti == jti
    assert len(jti) == 64 and len(digest_jti(jti)) == 64
    assert digest_jti(jti) != jti
    assert csrf_token(sid, settings()) == csrf_token(sid, settings())
    assert csrf_token(sid, settings()) != csrf_token(uuid4(), settings())


@pytest.mark.parametrize("claim", ["sub", "sid", "jti", "type", "iat", "nbf", "exp", "iss", "aud"])
def test_required_claims(claim):
    data = payload()
    del data[claim]
    token = jwt.encode(data, KEY, algorithm="HS256")
    with pytest.raises(ValueError):
        decode_token(token, "access", settings())


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("sub", "not-a-uuid"),
        ("sub", 42),
        ("sid", "bad"),
        ("sid", 42),
        ("type", "refresh"),
        ("iss", "wrong"),
        ("aud", "wrong"),
        ("aud", ["cm-kerala-grievance-client"]),
        ("jti", "small"),
        ("jti", "Z" * 64),
        ("iat", "123"),
        ("iat", True),
        ("exp", 1),
        ("exp", float(time.time() + 900)),
        ("nbf", int(time.time()) + 5000),
    ],
)
def test_invalid_claims_are_rejected(key, value):
    data = payload()
    data[key] = value
    with pytest.raises(ValueError):
        decode_token(jwt.encode(data, KEY, algorithm="HS256"), "access", settings())


@pytest.mark.parametrize("algorithm", ["HS512", "none"])
def test_untrusted_algorithms_are_rejected(algorithm):
    token = jwt.encode(payload(), KEY if algorithm != "none" else "", algorithm=algorithm)
    with pytest.raises(ValueError):
        decode_token(token, "access", settings())


def test_invalid_signature_and_malformed_token():
    for token in ("not.a.jwt", jwt.encode(payload(), token_hex(48), algorithm="HS256")):
        with pytest.raises(ValueError):
            decode_token(token, "access", settings())


@pytest.mark.parametrize(
    "overrides",
    [
        {"jwt_secret_key": "short"},
        {"jwt_secret_key": "x" * 64},
        {"jwt_algorithm": "HS512"},
        {"auth_cookie_samesite": "none", "auth_cookie_secure": False},
        {"cors_origins": "*"},
        {"auth_trusted_origins": "*"},
        {"auth_trusted_origins": ""},
        {"auth_trusted_origins": "https://example.test/path"},
        {"access_token_expire_minutes": 0},
    ],
)
def test_insecure_configuration_rejected(overrides):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **overrides)


def test_production_requires_stable_secret_secure_cookies_and_https():
    base = {
        "app_env": "production",
        "cors_origins": "https://app.example.test",
        "auth_trusted_origins": "https://app.example.test",
    }
    with pytest.raises(ValueError):
        Settings(_env_file=None, **base)
    with pytest.raises(ValueError):
        Settings(_env_file=None, jwt_secret_key=KEY, **base)
    configured = Settings(_env_file=None, jwt_secret_key=KEY, auth_cookie_secure=True, **base)
    assert configured.jwt_algorithm == "HS256"
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            jwt_secret_key=KEY,
            auth_cookie_secure=True,
            **{**base, "cors_origins": "http://app.example.test"},
        )


def test_health_survives_missing_dev_auth_secret():
    app = create_app(Settings(_env_file=None, jwt_secret_key=None))
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:5173"},
            json={"email": "citizen@example.test", "password": "any"},
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "Authentication is not configured."}


def test_invalid_configuration_does_not_expose_signing_secret():
    sensitive = "private-but-too-short"
    with pytest.raises(ValueError) as failure:
        Settings(_env_file=None, jwt_secret_key=sensitive)
    assert sensitive not in str(failure.value)
