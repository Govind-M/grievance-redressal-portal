from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import decode_token
from app.db.session import get_db
from app.modules.auth.errors import AuthenticationError
from app.modules.auth.service import AuthContext, authenticate
from app.modules.enums import UserRole
from app.modules.users.models import User

bearer = HTTPBearer(auto_error=False)


def get_auth_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    if not settings.jwt_secret_key or not settings.jwt_secret_key.get_secret_value():
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    return settings


def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_auth_settings)],
) -> AuthContext:
    if credentials is None:
        raise AuthenticationError()
    try:
        claims = decode_token(credentials.credentials, "access", settings)
    except ValueError:
        raise AuthenticationError() from None
    return authenticate(db, claims)


def get_current_user(context: Annotated[AuthContext, Depends(get_auth_context)]) -> User:
    return context.user


# Every current-user lookup already enforces active user AND active server-side session.
get_current_active_user = get_current_user


def require_roles(*roles: UserRole) -> Callable:
    def role_dependency(user: Annotated[User, Depends(get_current_active_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return user

    return role_dependency


require_cmo_admin = require_roles(UserRole.CMO_ADMIN)
require_department_officer = require_roles(UserRole.DEPARTMENT_OFFICER)
require_citizen = require_roles(UserRole.CITIZEN)
