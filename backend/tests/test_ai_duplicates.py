"""Mock orchestration on all hosts; real pgvector SQL only on capable test instances."""

from uuid import UUID, uuid4

import pytest
import test_ai_postgres as ai_fixtures
from sqlalchemy import func, select
from test_ai_postgres import call
from test_grievances_postgres import create

from app.db.models import AIAnalysis, Grievance, GrievanceEmbedding
from app.integrations.embeddings import ensure_embedding
from app.modules.ai import repository, service

pytestmark = pytest.mark.postgres
ai_api = ai_fixtures.ai_api
base_api = ai_fixtures.base_api


def test_duplicate_pipeline_with_mock_retrieval(ai_api, monkeypatch):
    source = create(ai_api)
    candidate = create(ai_api, subject="Another fictional road concern")
    with ai_api.db() as db:
        other = db.get(Grievance, UUID(candidate["id"]))
    monkeypatch.setattr(service, "ensure_embedding", lambda *args: [1.0] * 768)
    monkeypatch.setattr(repository, "similar", lambda *args: [(other, 0.1)])
    result = call(ai_api, f"/cmo/grievances/{source['id']}/detect-duplicates", who="cmo")
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["reference_number"] == candidate["reference_number"]
    assert result["candidates"][0]["similarity_score"] == pytest.approx(0.9)
    assert result["candidates"][0]["potentially_duplicate"]
    with ai_api.db() as db:
        assert db.scalar(select(func.count()).select_from(Grievance)) == 2
        record = db.get(AIAnalysis, UUID(result["analysis_id"]))
        assert record.result_data["candidates"] == result["candidates"]


def test_no_candidates_means_no_chat_call(ai_api, monkeypatch):
    source = create(ai_api)
    monkeypatch.setattr(service, "ensure_embedding", lambda *args: [1.0] * 768)
    monkeypatch.setattr(repository, "similar", lambda *args: [])
    result = call(ai_api, f"/cmo/grievances/{source['id']}/detect-duplicates", who="cmo")
    assert result["candidates"] == []
    assert ai_api.fake.calls == []


@pytest.mark.parametrize("invalid", ["unknown", "repeated", "missing", "not_boolean"])
def test_duplicate_model_cannot_invent_candidates(ai_api, monkeypatch, invalid):
    source = create(ai_api)
    candidate = create(ai_api)
    with ai_api.db() as db:
        other = db.get(Grievance, UUID(candidate["id"]))
        monkeypatch.setattr(service, "ensure_embedding", lambda *args: [1.0] * 768)
        monkeypatch.setattr(repository, "similar", lambda *args: [(other, 0.05)])
        decision = {
            "grievance_id": candidate["id"],
            "potentially_duplicate": True,
            "reasoning": "A fictional possible match.",
        }
        output = [decision]
        if invalid == "unknown":
            output = [{**decision, "grievance_id": str(uuid4())}]
        elif invalid == "repeated":
            output = [decision, decision]
        elif invalid == "missing":
            output = []
        else:
            output = [{**decision, "potentially_duplicate": "true"}]
        ai_api.fake.output = {"candidates": output}
        call(ai_api, f"/cmo/grievances/{source['id']}/detect-duplicates", who="cmo", status=502)
    with ai_api.db() as db:
        assert db.scalar(select(func.count()).select_from(AIAnalysis)) == 0


@pytest.fixture
def vector_api(request):
    api = request.getfixturevalue("ai_api")
    with api.db() as db:
        if not repository.vectors_ready(db):
            pytest.skip(
                "Real pgvector SQL unavailable: server extension absent; mocked pipeline tested separately"
            )
    return api


def test_real_vector_roundtrip_idempotence_and_fingerprint(vector_api):
    api = vector_api
    source = create(api)
    with api.db() as db:
        row = db.get(Grievance, UUID(source["id"]))
        ensure_embedding(db, row, api.runtime)
        db.commit()
        ensure_embedding(db, row, api.runtime)
        db.commit()
        assert len(api.fake.embed_calls) == 1
        stored = db.scalar(select(GrievanceEmbedding))
        assert len(stored.embedding) == 768
        old_fingerprint = stored.source_fingerprint
        row.description += " A changed fictional location."
        db.commit()
        ensure_embedding(db, row, api.runtime)
        db.commit()
        db.refresh(stored)
        assert old_fingerprint != stored.source_fingerprint
        assert len(api.fake.embed_calls) == 2
        assert db.scalar(select(func.count()).select_from(GrievanceEmbedding)) == 1


def test_real_similarity_sql_filters_current_and_incompatible_models(vector_api):
    api = vector_api
    ids = [create(api)["id"] for _ in range(4)]
    with api.db() as db:
        rows = [db.get(Grievance, UUID(identifier)) for identifier in ids]
        for row in rows:
            ensure_embedding(db, row, api.runtime)
        db.commit()
        stale = db.scalar(
            select(GrievanceEmbedding).where(GrievanceEmbedding.grievance_id == rows[-1].id)
        )
        stale.model_name = "incompatible-test-model"
        db.commit()
        api.runtime.settings = api.runtime.settings.model_copy(
            update={"ai_duplicate_candidate_limit": 1}
        )
        found = repository.similar(db, rows[0], [1.0] + [0.0] * 767, api.runtime.settings)
        assert len(found) == 1
        assert found[0][0].id not in (rows[0].id, rows[-1].id)


def test_real_vector_endpoint_mocked_gemini(vector_api):
    api = vector_api
    source = create(api)
    candidate = create(api, subject="Fictional matching road damage")
    with api.db() as db:
        ensure_embedding(db, db.get(Grievance, UUID(candidate["id"])), api.runtime)
        db.commit()
    result = call(api, f"/cmo/grievances/{source['id']}/detect-duplicates", who="cmo")
    assert result["candidates"][0]["grievance_id"] == candidate["id"]
    assert len(api.fake.embed_calls) == 2 and len(api.fake.calls) == 1
