"""Shared local/hosted engine construction for sessions, Alembic and explicit tooling."""

from pathlib import Path

import certifi
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool

from app.core.config import BACKEND_DIR, Settings


def connection_arguments(settings: Settings) -> dict:
    args = {"connect_timeout": settings.db_connect_timeout_seconds, "options": "-c timezone=UTC"}
    if settings.database_target == "supabase":
        url = settings.selected_database_url
        root = settings.supabase_sslrootcert or url.query.get("sslrootcert") or certifi.where()
        root = Path(root).expanduser()
        if not root.is_absolute():
            root = BACKEND_DIR / root
        if not root.is_file():
            raise ValueError("Supabase TLS CA file is missing; configure SUPABASE_SSLROOTCERT")
        args.update(sslmode="verify-full", sslrootcert=str(root.resolve()), prepare_threshold=None)
    return args


def _hosted_session(dbapi_connection, _record):
    # Session pooler only. Discover the existing vector namespace rather than moving it.
    with dbapi_connection.cursor() as cursor:
        cursor.execute("""
            SELECT n.nspname FROM pg_catalog.pg_extension e
            JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'
        """)
        row = cursor.fetchone()
        schemas = ["public"] + ([row[0]] if row and row[0] != "public" else [])
        path = ",".join('"' + name.replace('"', '""') + '"' for name in schemas)
        cursor.execute("SELECT pg_catalog.set_config('search_path', %s, false)", (path,))
    # Only session configuration/catalog reads occurred. No application data was changed.
    dbapi_connection.commit()


def build_engine(settings: Settings, *, migration: bool = False):
    kwargs = (
        {"poolclass": NullPool}
        if migration
        else {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout_seconds,
            "pool_recycle": settings.db_pool_recycle_seconds,
        }
    )
    engine = create_engine(
        settings.selected_database_url,
        connect_args=connection_arguments(settings),
        pool_pre_ping=True,
        hide_parameters=True,
        echo=False,
        **kwargs,
    )
    if settings.database_target == "supabase":
        event.listen(engine, "connect", _hosted_session)
    return engine
