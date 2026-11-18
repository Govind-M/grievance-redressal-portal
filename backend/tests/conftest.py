"""Shared schema fixture. Only an EMPTY, explicitly selected *_test database is accepted."""

import os
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import BACKEND_DIR
from app.db.base import Base


@pytest.fixture(scope="session")
def pg_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL integration tests")
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg" or not (parsed.database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must use psycopg and a dedicated database ending in _test")
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-c timezone=UTC"},
    )
    with engine.connect() as connection:
        if inspect(connection).get_table_names():
            pytest.fail("Tests require an empty test database; existing data will not be removed")
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
            # Verify an incremental up/down leaves original users/grievances/departments untouched.
            department_id, user_id, grievance_id, history_id = uuid4(), uuid4(), uuid4(), uuid4()
            connection.execute(
                text("""
                INSERT INTO departments (id, name, description)
                VALUES (:id, 'Migration probe', 'Synthetic test department')
            """),
                {"id": department_id},
            )
            connection.execute(
                text("""
                INSERT INTO users (id, name, email, password_hash, role)
                VALUES (:id, 'Migration probe', 'migration@example.test', 'not-a-login-hash', 'CITIZEN')
            """),
                {"id": user_id},
            )
            connection.execute(
                text("""
                INSERT INTO grievances
                (id, reference_number, citizen_id, district, category, subject, description)
                VALUES (:id, 'CMK-MIGRATION-PROBE', :user_id, 'Test', 'Test', 'Probe', 'Synthetic')
            """),
                {"id": grievance_id, "user_id": user_id},
            )
            connection.execute(
                text("""
                INSERT INTO grievance_history
                (id, grievance_id, from_status, to_status, changed_by, remarks)
                VALUES (:id, :grievance_id, NULL, 'SUBMITTED', :user_id, 'Legacy private note')
            """),
                {"id": history_id, "grievance_id": grievance_id, "user_id": user_id},
            )
            for target in ("head", "0002", "head", "0001", "head"):
                if target in ("0001", "0002"):
                    command.downgrade(config, target)
                else:
                    command.upgrade(config, target)
                for table, identifier in (
                    ("users", user_id),
                    ("departments", department_id),
                    ("grievances", grievance_id),
                    ("grievance_history", history_id),
                ):
                    assert (
                        connection.scalar(
                            text(f"SELECT id FROM {table} WHERE id = :id"), {"id": identifier}
                        )
                        == identifier
                    )
                assert (
                    connection.scalar(
                        text("SELECT remarks FROM grievance_history WHERE id = :id"),
                        {"id": history_id},
                    )
                    == "Legacy private note"
                )
                if target == "head":
                    assert (
                        connection.scalar(
                            text("SELECT remarks_visibility FROM grievance_history WHERE id = :id"),
                            {"id": history_id},
                        )
                        == "INTERNAL"
                    )
            assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {
                "alembic_version",
            }
            command.downgrade(config, "base")
            assert inspect(connection).get_table_names() == ["alembic_version"]
            assert inspect(connection).get_enums() == []
            command.upgrade(config, "head")
            command.check(config)
        yield engine
    finally:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            connection.execute(text("DROP TABLE alembic_version"))
        engine.dispose()
