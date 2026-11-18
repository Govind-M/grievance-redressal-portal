"""Configuration/tooling contract tests: no hosted network or real credentials."""

from unittest.mock import MagicMock

import certifi
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.engine import _hosted_session, build_engine, connection_arguments
from app.db.models import Department, User
from scripts.seed import seed, seed_departments
from scripts.supabase_db import HostedSafetyError, harden_application_objects, provision, safe_error

LOCAL = "postgresql+psycopg://test:local-only@localhost:5432/example"
HOSTED = "postgresql+psycopg://postgres.fixture:encoded%40pass%23%25@fixture.pooler.supabase.com:5432/postgres"


def hosted(**changes):
    return Settings(
        _env_file=None,
        database_url=LOCAL,
        database_target="supabase",
        supabase_database_url=HOSTED,
        supabase_sslrootcert=certifi.where(),
        **changes,
    )


def test_local_is_default_and_ignores_unused_hosted_configuration():
    settings = Settings(_env_file=None, database_url=LOCAL, supabase_database_url="unused-invalid")
    assert settings.database_target == "local"
    assert settings.selected_database_url.host == "localhost"
    assert "sslmode" not in connection_arguments(settings)


def test_explicit_supabase_target_preserves_password_encoding_and_local_url():
    settings = hosted()
    assert settings.selected_database_url.host == "fixture.pooler.supabase.com"
    assert settings.selected_database_url.password == "encoded@pass#%"
    assert settings.database_url.get_secret_value() == LOCAL
    args = connection_arguments(settings)
    assert args["sslmode"] == "verify-full"
    assert args["prepare_threshold"] is None
    assert args["sslrootcert"]


def test_bare_postgresql_url_is_normalized_only_for_hosted_target():
    settings = hosted().model_copy(
        update={
            "supabase_database_url": Settings(
                _env_file=None,
                supabase_database_url=HOSTED.replace("postgresql+psycopg:", "postgresql:"),
            ).supabase_database_url
        }
    )
    assert settings.selected_database_url.drivername == "postgresql+psycopg"


def test_missing_supabase_setting_cannot_fall_back_to_local():
    settings = Settings(_env_file=None, database_target="supabase", database_url=LOCAL)
    with pytest.raises(ValueError, match="SUPABASE_DATABASE_URL"):
        settings.selected_database_url


@pytest.mark.parametrize(
    "query",
    [
        "?sslmode=disable",
        "?sslmode=require",
        "?sslmode=verify-ca",
        "?host=other.example",
        "?hostaddr=127.0.0.1",
        "?dbname=other",
        "?service=other",
        "?options=-csearch_path=other",
    ],
)
def test_insecure_or_identity_overriding_url_rejected(query):
    settings = Settings(
        _env_file=None, database_target="supabase", supabase_database_url=HOSTED + query
    )
    with pytest.raises(ValueError):
        settings.selected_database_url


@pytest.mark.parametrize(
    "url",
    [
        HOSTED.replace(":5432/", ":6543/"),
        "sqlite:///example.db",
        "not-a-url",
        "postgresql://user@fixture.pooler.supabase.com/postgres",
    ],
)
def test_invalid_or_transaction_pooler_target_rejected(url):
    settings = Settings(_env_file=None, database_target="supabase", supabase_database_url=url)
    with pytest.raises(ValueError):
        settings.selected_database_url


def test_missing_ca_file_does_not_weaken_verification():
    settings = hosted().model_copy(update={"supabase_sslrootcert": "missing-test-ca.crt"})
    with pytest.raises(ValueError, match="CA file"):
        connection_arguments(settings)


def test_pool_sizes_bounded_and_engine_has_no_connect_side_effects():
    settings = hosted(db_pool_size=2, db_max_overflow=1)
    engine = build_engine(settings)
    try:
        assert engine.pool.size() == 2
        assert engine.pool.checkedout() == 0
        assert engine.hide_parameters is True and engine.echo is False
        assert engine.url.host == "fixture.pooler.supabase.com"
    finally:
        engine.dispose()


def test_extension_namespace_is_discovered_and_quoted_safely():
    dbapi = MagicMock()
    cursor = dbapi.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = ('odd"namespace',)
    _hosted_session(dbapi, None)
    calls = cursor.execute.call_args_list
    assert "pg_extension" in calls[0].args[0]
    assert calls[1].args[1] == ('"public","odd""namespace"',)
    dbapi.commit.assert_called_once()


def test_provision_requires_fingerprint_before_any_connection(monkeypatch):
    import scripts.supabase_db as tool

    connect = MagicMock()
    monkeypatch.setattr(tool, "build_engine", connect)
    with pytest.raises(HostedSafetyError, match="fingerprint"):
        provision(hosted(), "incorrect")
    connect.assert_not_called()


def test_error_reporting_does_not_echo_credentials():
    error = RuntimeError(
        "postgresql://secret:password@private.example/db certificate verify failed"
    )
    output = str(safe_error(error))
    assert "postgresql" not in output and "password" not in output
    assert "TLS certificate" in output


def test_security_changes_are_scoped_to_application_objects():
    db = MagicMock()
    db.scalars.return_value.all.return_value = ["anon", "authenticated", "service_role"]
    db.scalar.return_value = False
    db.dialect.identifier_preparer.quote.side_effect = lambda name: '"' + name + '"'
    harden_application_objects(db)
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert any("ENABLE ROW LEVEL SECURITY" in value for value in statements)
    assert all("auth." not in value and "storage." not in value for value in statements)
    assert all("DROP " not in value and "ALTER ROLE" not in value for value in statements)
    assert all("DEFAULT PRIVILEGES" not in value for value in statements)


def test_demo_seed_refuses_hosted_before_any_database_write():
    db = MagicMock()
    with pytest.raises(ValueError, match="reference-only"):
        seed(db, hosted())
    db.execute.assert_not_called()


@pytest.mark.postgres
def test_reference_seed_is_idempotent_without_users_or_passwords(pg_engine):
    with pg_engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                seed_departments(db)
                seed_departments(db)
                assert db.scalar(select(func.count()).select_from(Department)) == 7
                assert db.scalar(select(func.count()).select_from(User)) == 0
        finally:
            outer.rollback()
