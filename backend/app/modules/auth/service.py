"""Synchronous transactions. Never return a token pair until its state is committed."""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_hex
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import (
    TokenClaims,
    csrf_token,
    digest_jti,
    encode_token,
    hash_password,
    verify_password,
)
from app.db.models import RevokedToken, User, UserSession
from app.modules.auth.errors import AuthenticationError
from app.modules.auth.schemas import LoginRequest, RegistrationRequest, TokenResponse
from app.modules.enums import UserRole
from app.modules.users.schemas import UserResponse

# Equalize the unknown-user path with a real Argon2 verification.
_DUMMY_HASH = hash_password(token_hex(32))


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: UserSession
    claims: TokenClaims


@dataclass(frozen=True)
class IssuedTokens:
    response: TokenResponse
    refresh_token: str
    refresh_expires_at: datetime


def register_user(db: Session, data: RegistrationRequest) -> User:
    if db.scalar(select(User.id).where(User.email == data.email)):
        raise HTTPException(status_code=409, detail="Email is already registered.")
    user = User(
        name=data.name,
        email=data.email,
        mobile_number=data.mobile_number,
        password_hash=hash_password(data.password.get_secret_value()),
        role=UserRole.CITIZEN,
        department_id=None,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_users_email":
            raise HTTPException(status_code=409, detail="Email is already registered.") from None
        raise
    db.refresh(user)
    return user


def _issue(user: User, session: UserSession, settings: Settings, now: datetime) -> IssuedTokens:
    access_expiry = min(
        now + timedelta(minutes=settings.access_token_expire_minutes), session.expires_at
    )
    access, _ = encode_token(user.id, session.id, "access", now, access_expiry, settings)
    refresh, refresh_jti = encode_token(
        user.id, session.id, "refresh", now, session.expires_at, settings
    )
    session.current_refresh_jti_hash = digest_jti(refresh_jti)
    session.last_used_at = now
    return IssuedTokens(
        response=TokenResponse(
            access_token=access,
            expires_in=int(access_expiry.timestamp()) - int(now.timestamp()),
            csrf_token=csrf_token(session.id, settings),
            user=UserResponse.model_validate(user),
        ),
        refresh_token=refresh,
        refresh_expires_at=session.expires_at,
    )


def login(db: Session, data: LoginRequest, settings: Settings) -> IssuedTokens:
    # User-first locking also serializes login against logout-all.
    user = db.scalar(select(User).where(User.email == data.email).with_for_update())
    valid = verify_password(
        data.password.get_secret_value(), user.password_hash if user else _DUMMY_HASH
    )
    if not valid or user is None or not user.is_active:
        raise AuthenticationError("Invalid email or password.")
    now = datetime.now(UTC)
    session = UserSession(
        id=uuid4(),
        user=user,
        created_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    issued = _issue(user, session, settings, now)
    db.add(session)
    db.commit()
    return issued


def _valid_session(session: UserSession | None, user_id: UUID, now: datetime) -> bool:
    return bool(
        session is not None
        and session.user_id == user_id
        and session.revoked_at is None
        and session.expires_at > now
    )


def authenticate(db: Session, claims: TokenClaims) -> AuthContext:
    user = db.get(User, claims.user_id)
    session = db.get(UserSession, claims.session_id)
    if (
        user is None
        or not user.is_active
        or not _valid_session(session, claims.user_id, datetime.now(UTC))
        or db.scalar(
            select(RevokedToken.id).where(RevokedToken.token_jti_hash == digest_jti(claims.jti))
        )
        is not None
    ):
        raise AuthenticationError()
    return AuthContext(user=user, session=session, claims=claims)


def rotate(db: Session, claims: TokenClaims, settings: Settings) -> IssuedTokens:
    user = db.scalar(
        select(User)
        .where(User.id == claims.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    session = db.scalar(
        select(UserSession)
        .where(UserSession.id == claims.session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = datetime.now(UTC)  # Re-check expiration AFTER any lock wait.
    if (
        user is None
        or not user.is_active
        or claims.expires_at <= now
        or not _valid_session(session, claims.user_id, now)
    ):
        raise AuthenticationError(clear_cookie=True)
    supplied_hash = digest_jti(claims.jti)
    consumed = db.scalar(
        select(RevokedToken.id).where(RevokedToken.token_jti_hash == supplied_hash)
    )
    if consumed is not None or not hmac.compare_digest(
        supplied_hash, session.current_refresh_jti_hash
    ):
        session.revoked_at = now
        session.revocation_reason = "refresh_token_reuse"
        # Commit this security decision before raising the 401; request cleanup must not undo it.
        db.commit()
        raise AuthenticationError(clear_cookie=True)
    db.add(
        RevokedToken(
            session_id=session.id,
            token_jti_hash=supplied_hash,
            token_type="refresh",
            expires_at=claims.expires_at,
            revoked_at=now,
            reason="refresh_rotation",
        )
    )
    issued = _issue(user, session, settings, now)
    db.commit()
    return issued


def logout(db: Session, context: AuthContext) -> None:
    session = db.scalar(
        select(UserSession)
        .where(UserSession.id == context.session.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = datetime.now(UTC)
    if not _valid_session(session, context.user.id, now):
        raise AuthenticationError(clear_cookie=True)
    session.revoked_at = now
    session.revocation_reason = "logout"
    db.commit()


def logout_all(db: Session, context: AuthContext) -> None:
    db.execute(select(User.id).where(User.id == context.user.id).with_for_update())
    now = datetime.now(UTC)
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == context.user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now, revocation_reason="logout_all")
    )
    db.commit()
