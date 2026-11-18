from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base

config = context.config
target_metadata = Base.metadata
# Tests can inject their dedicated connection without changing application settings.
connection = config.attributes.get("connection")


def run_with_connection(conn):
    context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif connection is not None:
    run_with_connection(connection)
else:
    engine = create_engine(
        get_settings().database_url.get_secret_value(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 3, "options": "-c timezone=UTC"},
        hide_parameters=True,
    )
    try:
        with engine.connect() as conn:
            run_with_connection(conn)
    finally:
        engine.dispose()
