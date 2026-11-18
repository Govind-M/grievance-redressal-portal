"""API/security integration tests use real PostgreSQL commits and independent request sessions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from secrets import token_hex
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.dependencies import require_citizen, require_cmo_admin, require_department_officer
from app.core.permissions import (
    is_active_department_officer,
    is_designated_officer,
    may_modify_assignment,
    may_view_assignment,
    officer_belongs_to_department,
    require_assignment_permission,
)
from app.core.security import digest_jti, signing_key, verify_password
from app.db.models import Department, DepartmentAssignment, RevokedToken, User, UserSession
from app.db.session import get_db
from app.main import create_app
from app.modules.auth import service
from app.modules.enums import UserRole
from scripts.seed import seed

pytestmark = pytest.mark.postgres
ORIGIN = "http://localhost:5173"
PASSWORD = "Synthetic-auth-test-password"
KEY = token_hex(48)
PREFIX = "/api/v1"


@pytest.fixture
def auth(pg_engine):
    settings = Settings(
        _env_file=None,
        app_env="test",
        jwt_secret_key=KEY,
        seed_citizen_password=PASSWORD,
        seed_cmo_password=PASSWORD,
        seed_officer_password=PASSWORD,
    )
    with Session(pg_engine) as db:
        seed(db, settings)
        db.commit()
    app = create_app(settings)

    def request_db():
        with Session(pg_engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = request_db
    # Dependency probes live only in the test application, never in production routing.
    for path, dependency in (
        ("cmo", require_cmo_admin),
        ("officer", require_department_officer),
        ("citizen", require_citizen),
    ):

        def probe(user=Depends(dependency)):
            return {"role": user.role}

        app.add_api_route(f"/test/{path}", probe, methods=["GET"])
    try:
        with TestClient(app, headers={"Origin": ORIGIN}) as client:
            yield SimpleNamespace(
                client=client, app=app, engine=pg_engine, settings=settings, request_db=request_db
            )
    finally:
        # These tables contain only this fixture's committed records in the dedicated empty test DB.
        with pg_engine.begin() as connection:
            for model in (RevokedToken, UserSession, User, Department):
                connection.execute(delete(model))


def login(auth, email="citizen@example.test"):
    response = auth.client.post(f"{PREFIX}/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def refresh_headers(auth, response, raw=None):
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Cookie": f"{auth.settings.auth_cookie_name}={raw or auth.client.cookies.get(auth.settings.auth_cookie_name)}",
    }


def logout_headers(response):
    return {**bearer(response), "X-CSRF-Token": response.json()["csrf_token"]}


def registration(**overrides):
    return {
        "name": "Fictional New Citizen",
        "email": "new-citizen@example.test",
        "mobile_number": "+919876543210",
        "password": PASSWORD,
        **overrides,
    }


def test_registration_normalization_and_safe_response(auth):
    response = auth.client.post(
        f"{PREFIX}/auth/register", json=registration(email=" NEW-CITIZEN@EXAMPLE.TEST ")
    )
    assert response.status_code == 201
    result = response.json()
    assert result["email"] == "new-citizen@example.test"
    assert result["role"] == "CITIZEN" and result["department_id"] is None
    assert "password_hash" not in result
    assert "password" not in result
    with Session(auth.engine) as db:
        user = db.get(User, UUID(result["id"]))
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(PASSWORD, user.password_hash)
    duplicate = auth.client.post(f"{PREFIX}/auth/register", json=registration())
    assert duplicate.status_code == 409
    result = auth.client.post(
        f"{PREFIX}/auth/login", json={"email": "new-citizen@example.test", "password": PASSWORD}
    )
    assert result.status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "bad"},
        {"password": "short"},
        {"password": "x" * 129},
        {"name": " "},
        {"name": "Name\nInjected"},
        {"mobile_number": "abc"},
        {"mobile_number": "123"},
        {"mobile_number": "+123456789012345"},
        {"role": "CMO_ADMIN"},
        {"role": "DEPARTMENT_OFFICER"},
        {"department_id": str(uuid4())},
        {"is_active": False},
    ],
)
def test_registration_validation_and_no_escalation(auth, overrides):
    response = auth.client.post(f"{PREFIX}/auth/register", json=registration(**overrides))
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert '"input"' not in response.text


def test_registration_missing_fields(auth):
    response = auth.client.post(f"{PREFIX}/auth/register", json={})
    assert response.status_code == 422
    assert len(response.json()["detail"]) == 4


@pytest.mark.parametrize(
    ("email", "role"),
    [
        ("citizen@example.test", "CITIZEN"),
        ("cmo@example.test", "CMO_ADMIN"),
        ("officer@example.test", "DEPARTMENT_OFFICER"),
    ],
)
def test_all_seed_roles_login_and_safe_profile(auth, email, role):
    response = login(auth, email)
    data = response.json()
    raw_refresh = auth.client.cookies.get(auth.settings.auth_cookie_name)
    assert raw_refresh not in response.text
    assert data["user"]["role"] == role
    assert data["expires_in"] == 900
    claims = jwt.decode(
        data["access_token"],
        signing_key(auth.settings),
        algorithms=["HS256"],
        audience=auth.settings.jwt_audience,
        issuer=auth.settings.jwt_issuer,
    )
    refresh = jwt.decode(
        raw_refresh,
        signing_key(auth.settings),
        algorithms=["HS256"],
        audience=auth.settings.jwt_audience,
        issuer=auth.settings.jwt_issuer,
    )
    assert claims["exp"] - claims["iat"] == 900
    assert refresh["exp"] - refresh["iat"] == 7 * 24 * 3600
    assert claims["sid"] == refresh["sid"]
    assert claims["jti"] != refresh["jti"]
    assert all(type(claims[key]) is int for key in ("iat", "nbf", "exp"))
    assert "role" not in claims
    profile = auth.client.get(f"{PREFIX}/auth/me", headers=bearer(response))
    assert profile.status_code == 200 and profile.json() == data["user"]
    assert set(profile.json()) == {
        "id",
        "name",
        "email",
        "mobile_number",
        "role",
        "department_id",
        "is_active",
        "created_at",
    }
    with Session(auth.engine) as db:
        session = db.get(UserSession, UUID(claims["sid"]))
        assert session.current_refresh_jti_hash == digest_jti(refresh["jti"])
        assert raw_refresh != session.current_refresh_jti_hash
        assert len(session.user.sessions) == 1
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert "path=/api/v1/auth" in cookie
    assert "; secure" not in cookie
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("unknown@example.test", PASSWORD),
        ("citizen@example.test", "wrong"),
    ],
)
def test_generic_login_failures(auth, email, password):
    response = auth.client.post(f"{PREFIX}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}
    assert response.headers["www-authenticate"] == "Bearer"


def test_inactive_login_and_corrupt_password_hash(auth):
    with Session(auth.engine) as db:
        citizen = db.scalar(select(User).where(User.email == "citizen@example.test"))
        citizen.is_active = False
        db.commit()
    response = auth.client.post(
        f"{PREFIX}/auth/login", json={"email": "citizen@example.test", "password": PASSWORD}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}
    with Session(auth.engine) as db:
        citizen = db.scalar(select(User).where(User.email == "citizen@example.test"))
        citizen.is_active = True
        citizen.password_hash = "$argon2id$broken"
        db.commit()
    assert (
        auth.client.post(
            f"{PREFIX}/auth/login", json={"email": "citizen@example.test", "password": PASSWORD}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "kind", ["missing", "bad-signature", "expired", "refresh", "issuer", "audience", "sub", "sid"]
)
def test_invalid_access_rejected(auth, kind):
    result = login(auth)
    token = result.json()["access_token"]
    payload = jwt.decode(
        token,
        KEY,
        algorithms=["HS256"],
        issuer=auth.settings.jwt_issuer,
        audience=auth.settings.jwt_audience,
    )
    if kind == "missing":
        headers = {}
    else:
        if kind == "expired":
            payload.update(iat=1, nbf=1, exp=2)
        elif kind == "refresh":
            payload["type"] = "refresh"
        elif kind == "issuer":
            payload["iss"] = "wrong"
        elif kind == "audience":
            payload["aud"] = "wrong"
        elif kind == "sub":
            payload["sub"] = "not-a-uuid"
        elif kind == "sid":
            payload["sid"] = "not-a-uuid"
        key = token_hex(48) if kind == "bad-signature" else KEY
        headers = {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='HS256')}"}
    response = auth.client.get(f"{PREFIX}/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired authentication."}
    assert "set-cookie" not in response.headers  # An expired access token must not destroy refresh.


def test_refresh_rotation_and_replay_commits_revocation(auth):
    first = login(auth)
    old_refresh = auth.client.cookies.get(auth.settings.auth_cookie_name)
    rotated = auth.client.post(
        f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, old_refresh)
    )
    assert rotated.status_code == 200
    new_refresh = auth.client.cookies.get(auth.settings.auth_cookie_name)
    assert new_refresh != old_refresh
    assert rotated.json()["access_token"] != first.json()["access_token"]
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(first)).status_code == 200
    replay = auth.client.post(
        f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, old_refresh)
    )
    assert replay.status_code == 401
    assert "max-age=0" in replay.headers["set-cookie"].lower()
    with Session(auth.engine) as db:
        session = db.scalar(select(UserSession))
        assert session.revoked_at is not None
        assert session.revocation_reason == "refresh_token_reuse"
        assert len(session.revoked_tokens) == 1
        assert session.revoked_tokens[0].reason == "refresh_rotation"
    for token_response in (first, rotated):
        assert (
            auth.client.get(f"{PREFIX}/auth/me", headers=bearer(token_response)).status_code == 401
        )
    assert (
        auth.client.post(
            f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, rotated, new_refresh)
        ).status_code
        == 401
    )


@pytest.mark.parametrize("kind", ["missing", "access", "expired", "invalid"])
def test_invalid_refresh_rejected(auth, kind):
    first = login(auth)
    raw = auth.client.cookies.get(auth.settings.auth_cookie_name)
    headers = refresh_headers(auth, first, raw)
    if kind == "missing":
        headers["Cookie"] = ""
    elif kind == "access":
        headers["Cookie"] = f"{auth.settings.auth_cookie_name}={first.json()['access_token']}"
    elif kind == "invalid":
        headers["Cookie"] = f"{auth.settings.auth_cookie_name}=malformed"
    else:
        payload = jwt.decode(
            raw,
            KEY,
            algorithms=["HS256"],
            issuer=auth.settings.jwt_issuer,
            audience=auth.settings.jwt_audience,
        )
        payload.update(iat=1, nbf=1, exp=2)
        headers["Cookie"] = (
            f"{auth.settings.auth_cookie_name}={jwt.encode(payload, KEY, algorithm='HS256')}"
        )
    assert auth.client.post(f"{PREFIX}/auth/refresh", headers=headers).status_code == 401


@pytest.mark.parametrize("condition", ["inactive_user", "expired_session", "revoked_session"])
def test_server_side_state_rejects_access_and_refresh(auth, condition):
    first = login(auth)
    raw = auth.client.cookies.get(auth.settings.auth_cookie_name)
    with Session(auth.engine) as db:
        session = db.scalar(select(UserSession))
        if condition == "inactive_user":
            session.user.is_active = False
        elif condition == "expired_session":
            session.created_at = datetime.now(UTC) - timedelta(days=8)
            session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            session.revoked_at = datetime.now(UTC)
            session.revocation_reason = "test"
        db.commit()
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(first)).status_code == 401
    assert (
        auth.client.post(
            f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, raw)
        ).status_code
        == 401
    )


def test_current_logout_is_immediate_and_keeps_other_sessions(auth):
    first = login(auth)
    refresh = auth.client.cookies.get(auth.settings.auth_cookie_name)
    other = login(auth)
    response = auth.client.post(f"{PREFIX}/auth/logout", headers=logout_headers(first))
    assert response.status_code == 204 and response.content == b""
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(first)).status_code == 401
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(other)).status_code == 200
    assert (
        auth.client.post(
            f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, refresh)
        ).status_code
        == 401
    )
    # A repeated logout must pass authentication again, so it returns 401.
    assert (
        auth.client.post(f"{PREFIX}/auth/logout", headers=logout_headers(first)).status_code == 401
    )


def test_logout_all_only_affects_current_user(auth):
    first, second, unrelated = login(auth), login(auth), login(auth, "cmo@example.test")
    assert (
        auth.client.post(f"{PREFIX}/auth/logout-all", headers=logout_headers(first)).status_code
        == 204
    )
    for response in (first, second):
        assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(response)).status_code == 401
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(unrelated)).status_code == 200


@pytest.mark.parametrize(
    ("email", "accepted", "denied"),
    [
        ("citizen@example.test", "citizen", ["cmo", "officer"]),
        ("officer@example.test", "officer", ["cmo", "citizen"]),
        ("cmo@example.test", "cmo", ["officer", "citizen"]),
    ],
)
def test_role_dependencies(auth, email, accepted, denied):
    response = login(auth, email)
    assert auth.client.get(f"/test/{accepted}", headers=bearer(response)).status_code == 200
    for path in denied:
        assert auth.client.get(f"/test/{path}", headers=bearer(response)).status_code == 403


def test_roles_and_session_owner_are_loaded_from_database(auth):
    result = login(auth)
    data = jwt.decode(
        result.json()["access_token"],
        KEY,
        algorithms=["HS256"],
        issuer=auth.settings.jwt_issuer,
        audience=auth.settings.jwt_audience,
    )
    data["role"] = "CMO_ADMIN"
    forged_role = jwt.encode(data, KEY, algorithm="HS256")
    assert (
        auth.client.get("/test/cmo", headers={"Authorization": f"Bearer {forged_role}"}).status_code
        == 403
    )
    with Session(auth.engine) as db:
        user = db.get(User, UUID(data["sub"]))
        user.role = UserRole.CMO_ADMIN
        db.commit()
    assert auth.client.get("/test/cmo", headers=bearer(result)).status_code == 200
    unrelated = login(auth, "officer@example.test")
    other_claims = jwt.decode(
        unrelated.json()["access_token"],
        KEY,
        algorithms=["HS256"],
        issuer=auth.settings.jwt_issuer,
        audience=auth.settings.jwt_audience,
    )
    data["sid"] = other_claims["sid"]
    assert (
        auth.client.get(
            f"{PREFIX}/auth/me",
            headers={"Authorization": f"Bearer {jwt.encode(data, KEY, algorithm='HS256')}"},
        ).status_code
        == 401
    )


def test_self_profile_updates_only_permitted_fields(auth):
    first = login(auth)
    response = auth.client.patch(
        f"{PREFIX}/users/me",
        headers=bearer(first),
        json={"name": " Updated Fictional Citizen ", "mobile_number": "+919999999999"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Fictional Citizen"
    with Session(auth.engine) as db:
        assert (
            db.scalar(select(User).where(User.email == "cmo@example.test")).name
            == "Demo CMO Administrator"
        )
    assert (
        auth.client.patch(
            f"{PREFIX}/users/{uuid4()}", headers=bearer(first), json={"name": "Other user"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "field", ["role", "department_id", "is_active", "password_hash", "email", "id", "user_id"]
)
def test_profile_cannot_change_privileged_or_ownership_fields(auth, field):
    result = login(auth)
    response = auth.client.patch(
        f"{PREFIX}/users/me", headers=bearer(result), json={field: "forbidden"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "updates", [{"name": None}, {"mobile_number": None}, {"name": " "}, {"mobile_number": "abc"}]
)
def test_profile_validation(auth, updates):
    result = login(auth)
    assert (
        auth.client.patch(f"{PREFIX}/users/me", headers=bearer(result), json=updates).status_code
        == 422
    )


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost:5173.evil.test", "null", ""]
)
def test_origins_fail_closed(auth, origin):
    result = login(auth)
    headers = {**refresh_headers(auth, result), "Origin": origin}
    assert auth.client.post(f"{PREFIX}/auth/refresh", headers=headers).status_code == 403
    headers = {**logout_headers(result), "Origin": origin}
    assert auth.client.post(f"{PREFIX}/auth/logout", headers=headers).status_code == 403
    assert (
        auth.client.post(
            f"{PREFIX}/auth/login",
            headers={"Origin": origin},
            json={"email": "citizen@example.test", "password": PASSWORD},
        ).status_code
        == 403
    )
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(result)).status_code == 200


def test_csrf_is_required_and_session_bound(auth):
    first = login(auth)
    refresh = auth.client.cookies.get(auth.settings.auth_cookie_name)
    second = login(auth)
    for csrf in ("", "invalid", second.json()["csrf_token"]):
        headers = {**refresh_headers(auth, first, refresh), "X-CSRF-Token": csrf}
        assert auth.client.post(f"{PREFIX}/auth/refresh", headers=headers).status_code == 403
        headers = {**logout_headers(first), "X-CSRF-Token": csrf}
        assert auth.client.post(f"{PREFIX}/auth/logout", headers=headers).status_code == 403
    assert (
        auth.client.post(
            f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, refresh)
        ).status_code
        == 200
    )


def test_production_cookie_flags_and_deletion(auth):
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key=KEY,
        auth_cookie_secure=True,
        auth_cookie_samesite="none",
        cors_origins="https://app.example.test",
        auth_trusted_origins="https://app.example.test",
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = auth.request_db
    with TestClient(
        app, base_url="https://api.example.test", headers={"Origin": "https://app.example.test"}
    ) as client:
        result = client.post(
            f"{PREFIX}/auth/login", json={"email": "citizen@example.test", "password": PASSWORD}
        )
        assert result.status_code == 200
        cookie = result.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=none" in cookie
        assert (
            client.post(
                f"{PREFIX}/auth/refresh", headers={"X-CSRF-Token": result.json()["csrf_token"]}
            ).status_code
            == 200
        )
        logout = client.post(f"{PREFIX}/auth/logout", headers=logout_headers(result))
        assert logout.status_code == 204
        assert "secure" in logout.headers["set-cookie"].lower()


def test_cors_is_explicit_and_credential_aware(auth):
    result = auth.client.options(
        f"{PREFIX}/auth/refresh",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token,authorization",
        },
    )
    assert result.status_code == 200
    assert result.headers["access-control-allow-origin"] == ORIGIN
    assert result.headers["access-control-allow-credentials"] == "true"
    denied = auth.client.options(
        f"{PREFIX}/auth/refresh",
        headers={
            "Origin": "https://evil.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_concurrent_refresh_single_success_and_durable_replay_revocation(auth):
    first = login(auth)
    raw = auth.client.cookies.get(auth.settings.auth_cookie_name)
    barrier = Barrier(2)

    def attempt():
        with TestClient(auth.app, headers={"Origin": ORIGIN}) as client:
            barrier.wait(timeout=10)
            return client.post(f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, raw))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(response.status_code for response in results) == [200, 401]
    with Session(auth.engine) as db:
        session = db.scalar(select(UserSession))
        assert session.revocation_reason == "refresh_token_reuse"
        assert db.scalar(select(func.count()).select_from(RevokedToken)) == 1
    winner = next(response for response in results if response.status_code == 200)
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(winner)).status_code == 401


def test_concurrent_registration_unique_constraint(auth, monkeypatch):
    barrier = Barrier(2)
    original = service.hash_password

    def synchronized_hash(value):
        barrier.wait(timeout=10)  # Both duplicate-email checks complete before either insert.
        return original(value)

    monkeypatch.setattr(service, "hash_password", synchronized_hash)

    def attempt():
        with TestClient(auth.app, headers={"Origin": ORIGIN}) as client:
            return client.post(f"{PREFIX}/auth/register", json=registration())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(result.status_code for result in results) == [201, 409]
    with Session(auth.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.email == "new-citizen@example.test")
            )
            == 1
        )


def test_failed_rotation_rolls_back_but_never_leaks_internals(auth, monkeypatch, capsys):
    first = login(auth)
    raw = auth.client.cookies.get(auth.settings.auth_cookie_name)
    original = service._issue

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive synthetic value")

    monkeypatch.setattr(service, "_issue", fail)
    with TestClient(auth.app, headers={"Origin": ORIGIN}, raise_server_exceptions=False) as client:
        result = client.post(f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, raw))
    assert result.status_code == 500
    assert result.headers["cache-control"] == "no-store"
    assert result.json() == {"detail": "Internal server error"}
    assert "sensitive synthetic value" not in capsys.readouterr().err
    with Session(auth.engine) as db:
        assert db.scalar(select(func.count()).select_from(RevokedToken)) == 0
        assert db.scalar(select(UserSession)).revoked_at is None
    monkeypatch.setattr(service, "_issue", original)
    assert (
        auth.client.post(
            f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, raw)
        ).status_code
        == 200
    )


def test_seed_reset_is_explicit_development_only_and_revokes_demo_sessions(auth):
    result = login(auth)
    with Session(auth.engine) as db:
        before = db.scalar(select(User).where(User.email == "citizen@example.test")).password_hash
        seed(db, auth.settings)
        db.commit()
        assert (
            db.scalar(select(User).where(User.email == "citizen@example.test")).password_hash
            == before
        )
        with pytest.raises(ValueError):
            seed(db, auth.settings, reset_passwords=True)
        db.rollback()
        development = auth.settings.model_copy(update={"app_env": "development"})
        seed(db, development, reset_passwords=True)
        db.commit()
        user = db.scalar(select(User).where(User.email == "citizen@example.test"))
        assert user.password_hash != before and verify_password(PASSWORD, user.password_hash)
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(result)).status_code == 401


def test_auth_constraints_indexes_and_foreign_keys(auth):
    inspector = inspect(auth.engine)
    for table in ("user_sessions", "revoked_tokens"):
        assert inspector.get_foreign_keys(table)[0]["options"]["ondelete"] == "RESTRICT"
        assert inspector.get_unique_constraints(table)
        assert any(
            index["column_names"] == ["expires_at"] for index in inspector.get_indexes(table)
        )
    names = {index["name"] for index in inspector.get_indexes("user_sessions")}
    assert "ix_user_sessions_active_user" in names


def test_individual_access_blacklist_is_honored(auth):
    first = login(auth)
    payload = jwt.decode(
        first.json()["access_token"],
        KEY,
        algorithms=["HS256"],
        issuer=auth.settings.jwt_issuer,
        audience=auth.settings.jwt_audience,
    )
    with Session(auth.engine) as db:
        db.add(
            RevokedToken(
                session_id=UUID(payload["sid"]),
                token_jti_hash=digest_jti(payload["jti"]),
                token_type="access",
                expires_at=datetime.fromtimestamp(payload["exp"], UTC),
                reason="targeted_test",
            )
        )
        db.commit()
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(first)).status_code == 401


def test_hybrid_department_authorization_helpers(auth):
    with Session(auth.engine) as db:
        officer = db.scalar(select(User).where(User.role == UserRole.DEPARTMENT_OFFICER))
        citizen = db.scalar(select(User).where(User.role == UserRole.CITIZEN))
        other_department = db.scalar(select(Department).where(Department.name == "Health"))
        colleague = User(
            id=uuid4(),
            name="Fictional Colleague",
            email="colleague@example.test",
            role=UserRole.DEPARTMENT_OFFICER,
            department=officer.department,
            department_id=officer.department_id,
            is_active=True,
            password_hash="unused-in-memory",
        )
        assignment = DepartmentAssignment(
            department=officer.department,
            department_id=officer.department_id,
            officer_id=None,
            closed_at=None,
        )
        assert is_active_department_officer(officer)
        assert officer_belongs_to_department(officer, officer.department_id)
        assert may_view_assignment(officer, assignment) and may_modify_assignment(
            officer, assignment
        )
        assignment.officer_id = officer.id
        assert is_designated_officer(officer, assignment)
        assert may_modify_assignment(officer, assignment)
        assert may_view_assignment(colleague, assignment) and not may_modify_assignment(
            colleague, assignment
        )
        with pytest.raises(HTTPException) as exc:
            require_assignment_permission(colleague, assignment, modify=True)
        assert exc.value.status_code == 403
        assert not may_view_assignment(citizen, assignment)
        colleague.department = other_department
        colleague.department_id = other_department.id
        assert not may_view_assignment(colleague, assignment)
        officer.department.is_active = False
        assert not may_view_assignment(officer, assignment)
        officer.department.is_active = True
        officer.is_active = False
        assert not may_modify_assignment(officer, assignment)
        officer.is_active = True
        assignment.closed_at = datetime.now(UTC)
        assert not may_view_assignment(officer, assignment)


def test_independent_app_instance_uses_same_key_and_shared_revocation_state(auth):
    first = login(auth)
    raw = auth.client.cookies.get(auth.settings.auth_cookie_name)
    restarted_settings = Settings(
        _env_file=None,
        app_env="test",
        jwt_secret_key=KEY,
    )
    restarted_app = create_app(restarted_settings)
    restarted_app.dependency_overrides[get_db] = auth.request_db
    with TestClient(restarted_app, headers={"Origin": ORIGIN}) as other_worker:
        assert other_worker.get(f"{PREFIX}/auth/me", headers=bearer(first)).status_code == 200
        rotated = other_worker.post(
            f"{PREFIX}/auth/refresh", headers=refresh_headers(auth, first, raw)
        )
        assert rotated.status_code == 200
        assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(rotated)).status_code == 200
        assert (
            other_worker.post(f"{PREFIX}/auth/logout", headers=logout_headers(rotated)).status_code
            == 204
        )
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(first)).status_code == 401
    assert auth.client.get(f"{PREFIX}/auth/me", headers=bearer(rotated)).status_code == 401
