"""No network or server-vector dependency: exercise caching, validation and SQL contracts."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.integrations.embeddings import ensure_embedding, fingerprint, source_content
from app.modules.ai import repository
from app.modules.ai.embedding_models import GrievanceEmbedding
from app.modules.ai.runtime import AIRuntime


def row():
    return SimpleNamespace(
        id=uuid4(),
        district="Ernakulam",
        category="Other",
        subject="Fictional road damage",
        description="Fictional reported damage.",
    )


def runtime():
    provider = SimpleNamespace(embed=Mock(return_value=[1.0] + [0.0] * 767))
    return AIRuntime(Settings(_env_file=None, ai_enabled=True), provider)


def test_unchanged_embedding_does_not_call_provider(monkeypatch):
    source = row()
    cached = SimpleNamespace(
        source_fingerprint=fingerprint(source_content(source)), embedding=[1.0] + [0.0] * 767
    )
    monkeypatch.setattr(repository, "vectors_ready", lambda db: True)
    monkeypatch.setattr(repository, "embedding", lambda *args: cached)
    state = runtime()
    result = ensure_embedding(object(), source, state)
    assert len(result) == 768
    state.provider.embed.assert_not_called()


def test_changed_source_uses_idempotent_upsert_and_fingerprint(monkeypatch):
    source = row()
    state = runtime()
    monkeypatch.setattr(repository, "vectors_ready", lambda db: True)
    monkeypatch.setattr(
        repository, "embedding", lambda *args: SimpleNamespace(source_fingerprint="old")
    )
    db = SimpleNamespace(scalar=lambda query: source, execute=Mock())
    ensure_embedding(db, source, state)
    state.provider.embed.assert_called_once_with(source_content(source))
    compiled = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "ON CONFLICT (grievance_id, model_name, dimensions) DO UPDATE" in str(compiled)
    assert compiled.params["source_fingerprint"] == fingerprint(source_content(source))
    assert compiled.params["dimensions"] == 768


def test_content_race_does_not_store_wrong_embedding(monkeypatch):
    source = row()
    changed = row()
    changed.description = "New content after provider request."
    state = runtime()
    monkeypatch.setattr(repository, "vectors_ready", lambda db: True)
    monkeypatch.setattr(repository, "embedding", lambda *args: None)
    db = SimpleNamespace(scalar=lambda query: changed, execute=Mock())
    with pytest.raises(HTTPException) as error:
        ensure_embedding(db, source, state)
    assert error.value.status_code == 409
    db.execute.assert_not_called()


@pytest.mark.parametrize(
    "failure,status",
    [
        (TimeoutError("secret"), 504),
        (RuntimeError("secret"), 503),
    ],
)
def test_embedding_failure_has_no_database_write(monkeypatch, failure, status):
    source = row()
    state = runtime()
    state.provider.embed.side_effect = failure
    monkeypatch.setattr(repository, "vectors_ready", lambda db: True)
    monkeypatch.setattr(repository, "embedding", lambda *args: None)
    db = SimpleNamespace(execute=Mock())
    with pytest.raises(HTTPException) as error:
        ensure_embedding(db, source, state)
    assert error.value.status_code == status
    assert "secret" not in error.value.detail
    db.execute.assert_not_called()


def test_sql_search_uses_cosine_and_model_dimension_scope_and_drops_stale_content():
    source, valid, stale = row(), row(), row()
    result_rows = [
        (valid, 0.1, fingerprint(source_content(valid))),
        (stale, 0.15, "outdated-fingerprint"),
    ]
    db = SimpleNamespace(execute=Mock(return_value=SimpleNamespace(all=lambda: result_rows)))
    found = repository.similar(db, source, [1.0] * 768, runtime().settings)
    assert found == [(valid, 0.1)]
    compiled = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "<=>" in sql and "LIMIT" in sql
    assert "grievance_embeddings.model_name =" in sql
    assert "grievance_embeddings.dimensions =" in sql
    assert "grievances.id !=" in sql and "grievances.district =" in sql
    assert runtime().settings.gemini_embedding_model in compiled.params.values()
    assert 768 in compiled.params.values()
    assert GrievanceEmbedding.__table__.c.embedding.type.dim == 768
