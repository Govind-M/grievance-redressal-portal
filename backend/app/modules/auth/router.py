from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.dependencies import get_auth_context, get_auth_settings, get_current_active_user
from app.core.security import decode_token
from app.db.session import get_db
from app.modules.auth import service
from app.modules.auth.cookies import (
    clear_refresh_cookie,
    require_csrf,
    require_trusted_origin,
    set_refresh_cookie,
)
from app.modules.auth.errors import AuthenticationError
from app.modules.auth.schemas import LoginRequest, RegistrationRequest, TokenResponse
from app.modules.auth.service import AuthContext
from app.modules.users.models import User
from app.modules.users.schemas import UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])
DB = Annotated[Session, Depends(get_db)]
AuthSettings = Annotated[Settings, Depends(get_auth_settings)]
Context = Annotated[AuthContext, Depends(get_auth_context)]


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(require_trusted_origin)],
)
def register(data: RegistrationRequest, db: DB) -> User:
    return service.register_user(db, data)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(require_trusted_origin)])
def login(data: LoginRequest, response: Response, db: DB, settings: AuthSettings) -> TokenResponse:
    issued = service.login(db, data, settings)
    set_refresh_cookie(response, issued.refresh_token, issued.refresh_expires_at, settings)
    return issued.response


@router.post(
    "/refresh", response_model=TokenResponse, dependencies=[Depends(require_trusted_origin)]
)
def refresh(request: Request, response: Response, db: DB, settings: AuthSettings) -> TokenResponse:
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise AuthenticationError(clear_cookie=True)
    try:
        claims = decode_token(token, "refresh", settings)
    except ValueError:
        raise AuthenticationError(clear_cookie=True) from None
    require_csrf(request, claims.session_id, settings)
    issued = service.rotate(db, claims, settings)
    set_refresh_cookie(response, issued.refresh_token, issued.refresh_expires_at, settings)
    return issued.response


@router.post("/logout", status_code=204)
def logout(
    request: Request, response: Response, context: Context, db: DB, settings: AuthSettings
) -> None:
    require_csrf(request, context.session.id, settings)
    service.logout(db, context)
    clear_refresh_cookie(response, settings)


@router.post("/logout-all", status_code=204)
def logout_all(
    request: Request, response: Response, context: Context, db: DB, settings: AuthSettings
) -> None:
    require_csrf(request, context.session.id, settings)
    service.logout_all(db, context)
    clear_refresh_cookie(response, settings)


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_active_user)]) -> User:
    return user
