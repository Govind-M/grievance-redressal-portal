import hmac
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request, Response

from app.core.config import Settings
from app.core.security import csrf_token


def require_trusted_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    # Fail closed for absent Origin as well. CLI clients must explicitly supply a trusted Origin.
    if request.headers.get("origin") not in settings.trusted_origins:
        raise HTTPException(status_code=403, detail="Untrusted request origin.")


def require_csrf(request: Request, session_id: UUID, settings: Settings) -> None:
    require_trusted_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(supplied.encode(), csrf_token(session_id, settings).encode()):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def set_refresh_cookie(
    response: Response, token: str, expires_at: datetime, settings: Settings
) -> None:
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=settings.auth_cookie_path,
        domain=settings.auth_cookie_domain,
        expires=expires_at,
        max_age=max(0, int((expires_at - datetime.now(UTC)).total_seconds())),
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.auth_cookie_name,
        path=settings.auth_cookie_path,
        domain=settings.auth_cookie_domain,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
