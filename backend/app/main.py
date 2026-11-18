import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import get_db, get_engine
from app.modules.ai.router import router as ai_router
from app.modules.ai.runtime import AIRuntime
from app.modules.auth.cookies import clear_refresh_cookie
from app.modules.auth.errors import AuthenticationError
from app.modules.auth.router import router as auth_router
from app.modules.cmo.router import router as cmo_router
from app.modules.departments.router import router as departments_router
from app.modules.grievances.router import router as grievances_router
from app.modules.officer.router import router as officer_router
from app.modules.users.router import router as users_router

logger = logging.getLogger("app")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class DatabaseHealthResponse(BaseModel):
    status: str
    database: str


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    configure_logging(debug=config.app_debug)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logger.info("Application started")
        yield
        application.state.ai_runtime.provider.close()
        if get_engine.cache_info().currsize:
            get_engine().dispose()
        logger.info("Application stopped")

    # Even in development, API errors never include internal stack traces.
    application = FastAPI(
        title=config.app_name, version=config.version, debug=False, lifespan=lifespan
    )
    application.state.settings = config
    application.state.ai_runtime = AIRuntime(config)
    application.include_router(ai_router, prefix=config.api_prefix)
    application.include_router(auth_router, prefix=config.api_prefix)
    application.include_router(users_router, prefix=config.api_prefix)
    application.include_router(grievances_router, prefix=config.api_prefix)
    application.include_router(departments_router, prefix=config.api_prefix)
    application.include_router(cmo_router, prefix=config.api_prefix)
    application.include_router(officer_router, prefix=config.api_prefix)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )

    @application.middleware("http")
    async def prevent_auth_caching(request: Request, call_next):
        response = await call_next(request)
        if (
            request.url.path.startswith(f"{config.api_prefix}/auth")
            or (request.url.path == f"{config.api_prefix}/users/me")
            or request.url.path.startswith(f"{config.api_prefix}/grievances")
            or request.url.path.startswith(f"{config.api_prefix}/cmo")
            or request.url.path.startswith(f"{config.api_prefix}/officer")
            or request.url.path.startswith(f"{config.api_prefix}/ai")
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @application.exception_handler(AuthenticationError)
    async def authentication_error(request: Request, exc: AuthenticationError) -> JSONResponse:
        response = JSONResponse(
            status_code=401,
            content={"detail": exc.detail},
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
        if exc.clear_cookie:
            clear_refresh_cookie(response, config)
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default includes raw input, which can contain passwords or tokens.
        errors = [
            {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled application error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers={"Cache-Control": "no-store"},
        )

    @application.exception_handler(OperationalError)
    async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
        logger.warning("Database operation unavailable")
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable"},
            headers={"Cache-Control": "no-store"},
        )

    @application.get(f"{config.api_prefix}/health", response_model=HealthResponse, tags=["Health"])
    def health() -> HealthResponse:
        return HealthResponse(status="healthy", service=config.app_name, version=config.version)

    @application.get(
        f"{config.api_prefix}/health/db",
        response_model=DatabaseHealthResponse,
        tags=["Health"],
        responses={503: {"description": "Database unavailable"}},
    )
    def database_health(db: Session = Depends(get_db)) -> JSONResponse | DatabaseHealthResponse:
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.warning("Database connectivity check failed")
            return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
        return DatabaseHealthResponse(status="healthy", database="connected")

    return application


app = create_app()
