from alembic import context
from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.engine import build_engine

config = context.config
target_metadata = Base.metadata
# Tests can inject their dedicated connection without changing application settings.
connection = config.attributes.get("connection")


def run_with_connection(conn):
    # A hosted database contains managed objects. Drift checks own only our metadata tables.
    def application_object(obj, name, kind, reflected, compare_to):
        return kind != "table" or name in target_metadata.tables

    context.configure(
        connection=conn,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=application_object,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=get_settings().selected_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif connection is not None:
    run_with_connection(connection)
else:
    engine = build_engine(get_settings(), migration=True)
    try:
        with engine.connect() as conn:
            run_with_connection(conn)
    finally:
        engine.dispose()
