from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "CM Kerala Grievance API"
    app_env: Literal["development", "test", "production"] = "development"
    # Avoid the host's unrelated DEBUG environment variable (often "release").
    app_debug: bool = False
    version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://cm_user:change_me@localhost:5432/cm_kerala"
    )
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = Field(default="cm-kerala-grievance-api", min_length=1)
    jwt_audience: str = Field(default="cm-kerala-grievance-client", min_length=1)
    access_token_expire_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=30)
    auth_cookie_name: str = Field(default="cmk_refresh_token", pattern=r"^[A-Za-z0-9_-]+$")
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_path: str = "/api/v1/auth"
    auth_cookie_domain: str | None = None
    auth_trusted_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    gemini_api_key: SecretStr | None = None
    default_resolution_days: int = Field(default=14, ge=1, le=365)
    seed_citizen_password: SecretStr | None = None
    seed_cmo_password: SecretStr | None = None
    seed_officer_password: SecretStr | None = None

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        secret = self.jwt_secret_key.get_secret_value() if self.jwt_secret_key else ""
        if secret and (
            len(secret.encode()) < 32
            or len(set(secret)) < 8
            or secret.lower().startswith(("change", "your_", "replace", "example"))
        ):
            raise ValueError("JWT_SECRET_KEY must be a strong random secret of at least 32 bytes")
        if self.app_env == "production" and not secret:
            raise ValueError("JWT_SECRET_KEY is required in production")
        if self.app_env == "production" and not self.auth_cookie_secure:
            raise ValueError("Production requires AUTH_COOKIE_SECURE=true")
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("SameSite=None requires Secure cookies")
        if not self.auth_cookie_path.startswith("/") or any(
            char in self.auth_cookie_path for char in (";", "\r", "\n")
        ):
            raise ValueError("AUTH_COOKIE_PATH must be an absolute cookie path")
        for origin in self.allowed_origins + self.trusted_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise ValueError(
                    "Configure explicit full HTTP(S) origins without paths or wildcards"
                )
            if self.app_env == "production" and parsed.scheme != "https":
                raise ValueError("Production browser origins must use HTTPS")
        if not self.trusted_origins:
            raise ValueError("At least one AUTH_TRUSTED_ORIGINS entry is required")
        return self

    @property
    def trusted_origins(self) -> list[str]:
        return [item.strip() for item in self.auth_trusted_origins.split(",") if item.strip()]

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            driver = make_url(value.get_secret_value()).drivername
        except Exception:
            raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
        if driver != "postgresql+psycopg":
            raise ValueError("Use the synchronous postgresql+psycopg driver")
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
