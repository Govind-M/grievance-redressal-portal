"""Shared schema fixture. Only an EMPTY, explicitly selected *_test database is accepted."""

import os
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import BACKEND_DIR
from app.db.base import Base


@pytest.fixture(autouse=True)
def no_external_ai_network(monkeypatch):
    """Defense in depth: no test may send a provider, embedding or tracing request."""
    import ipaddress
    import socket

    original = socket.socket.connect

    def connect(sock, address):
        if isinstance(address, tuple):
            host = address[0]
            if host != "localhost":
                try:
                    if not ipaddress.ip_address(host).is_loopback:
                        raise AssertionError("External network access is forbidden during pytest")
                except ValueError:
                    raise AssertionError(
                        "External network access is forbidden during pytest"
                    ) from None
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture(scope="session")
def pg_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL integration tests")
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.host not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail(
            "Destructive PostgreSQL fixtures require a dedicated local test database, never Supabase"
        )
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
        vector_available = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')")
        )
    target_head = "head" if vector_available else "0005"
    engine._phase5_target = target_head
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
                    command.upgrade(config, target_head)
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
            expected = set(Base.metadata.tables)
            if not vector_available:
                expected.remove("grievance_embeddings")
            assert set(inspect(connection).get_table_names()) == expected | {
                "alembic_version",
            }
            command.downgrade(config, "base")
            assert inspect(connection).get_table_names() == ["alembic_version"]
            assert inspect(connection).get_enums() == []
            command.upgrade(config, target_head)
            if vector_available:
                command.check(config)
            else:
                from alembic.autogenerate import compare_metadata
                from alembic.migration import MigrationContext

                context = MigrationContext.configure(
                    connection,
                    opts={
                        "compare_type": True,
                        "include_object": lambda obj, name, kind, reflected, compare_to: (
                            name != "grievance_embeddings" if kind == "table" else True
                        ),
                    },
                )
                assert compare_metadata(context, Base.metadata) == []
        yield engine
    finally:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            connection.execute(text("DROP TABLE alembic_version"))
        engine.dispose()
