"""A missing server extension must not block mandatory AI at revision 0005."""

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from app.core.config import BACKEND_DIR

pytestmark = pytest.mark.postgres


def test_missing_pgvector_has_actionable_failure_and_preserves_core(pg_engine):
    if pg_engine._phase5_target != "0005":
        pytest.skip("Server has pgvector; full head up/down/check is covered by the shared fixture")
    with pg_engine.connect() as connection:
        before = set(inspect(connection).get_table_names())
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="Mandatory AI analysis works at revision 0005"):
            with connection.begin_nested():
                command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == before
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
        assert "report_id" in {x["name"] for x in inspect(connection).get_columns("ai_analyses")}
