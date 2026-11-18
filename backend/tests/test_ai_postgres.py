"""Every provider call is fake; real PostgreSQL still enforces persistence and privacy."""

import json
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_grievances_postgres import api as base_api  # noqa: F401
from test_grievances_postgres import create

from app.db.models import AIAnalysis, Grievance, GrievanceHistory, User
from app.modules.ai import repository
from app.modules.ai.runtime import AIRuntime
from app.modules.ai.schemas import ActionTakenAIReview, DuplicateAssessmentResult

P = "/api/v1"
pytestmark = pytest.mark.postgres


class FakeProvider:
    def __init__(self, department_id):
        self.department_id = department_id
        self.calls = []
        self.embed_calls = []
        self.output = None
        self.failure = None

    def structured(self, prompt, payload, schema):
        self.calls.append((prompt, json.loads(payload), schema))
        if self.failure:
            raise self.failure
        if self.output is not None:
            return self.output
        if schema == ActionTakenAIReview:
            return {
                "report_summary": "The report states that fictional repairs were completed.",
                "reported_actions": ["The officer reports repairs."],
                "apparently_addressed_issues": ["Reported road damage"],
                "potentially_unresolved": ["Durability remains unestablished."],
                "missing_evidence": ["Independent inspection"],
                "follow_up_questions": ["When was the inspection conducted?"],
            }
        if schema == DuplicateAssessmentResult:
            return {
                "candidates": [
                    {
                        "grievance_id": x["id"],
                        "potentially_duplicate": True,
                        "reasoning": "The reports may describe the same fictional incident.",
                    }
                    for x in json.loads(payload)["candidates"]
                ]
            }
        return {
            "suggested_department_id": str(self.department_id),
            "suggested_category": "Roads and Infrastructure",
            "suggested_priority": "HIGH",
            "summary": "The citizen reports fictional damage to a community road.",
            "department_reasoning": "The complaint concerns reported road maintenance.",
            "priority_reasoning": "The complaint reports a possible safety hazard.",
            "missing_information": ["Provide the exact fictional road location."],
        }

    def embed(self, content):
        self.embed_calls.append(content)
        if self.failure:
            raise self.failure
        return [1.0] + [0.0] * 767

    def close(self):
        pass


@pytest.fixture
def ai_api(request):
    api = request.getfixturevalue("base_api")
    with api.db() as db:
        officer = db.get(User, api.users["officer"])
        department_id = officer.department_id
    settings = api.client.app.state.settings.model_copy(
        update={"ai_enabled": True, "ai_live_requests_enabled": False, "ai_requests_per_minute": 30}
    )
    api.fake = FakeProvider(department_id)
    api.runtime = AIRuntime(settings, api.fake)
    api.client.app.state.ai_runtime = api.runtime
    api.department_id = department_id
    return api


def analyze_request(**changes):
    return {
        "district": "Ernakulam",
        "subject": "Fictional road damage report",
        "description": "A fictional road near the community hospital needs repairs.",
        **changes,
    }


def call(api, path="/ai/analyze-grievance", data=None, who="citizen", status=200):
    response = api.client.post(P + path, headers=api.headers(who), json=data)
    assert response.status_code == status, response.text
    return response.json()


def test_citizen_analysis_no_draft_or_official_persistence(ai_api):
    result = call(ai_api, data=analyze_request())
    assert result["is_advisory"] is True
    assert result["suggested_department"]["id"] == str(ai_api.department_id)
    assert result["suggested_priority"] == "HIGH"
    assert result["analysis_id"] is None
    assert result["missing_information"]
    with ai_api.db() as db:
        for model in (AIAnalysis, Grievance, GrievanceHistory):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    payload = ai_api.fake.calls[0][1]
    assert len(payload["allowed_categories"]) == 12
    assert len(payload["active_departments"]) == 7
    assert "email" not in str(payload) and "password" not in str(payload)
    # Repeated draft uses hash/result cache, no additional paid call, no stored draft.
    call(ai_api, data=analyze_request())
    assert len(ai_api.fake.calls) == 1


@pytest.mark.parametrize("who", ["cmo", "officer"])
def test_citizen_role_restricted(ai_api, who):
    call(ai_api, data=analyze_request(), who=who, status=403)
    assert ai_api.fake.calls == []


def test_authentication_required(ai_api):
    response = ai_api.client.post(P + "/ai/analyze-grievance", json=analyze_request())
    assert response.status_code == 401
    assert ai_api.fake.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"district": "Atlantis"},
        {"subject": "x"},
        {"description": "short"},
        {"description": "x" * 10001},
        {"priority": "HIGH"},
        {"subject": "\x00" * 8},
    ],
)
def test_request_validation(ai_api, changes):
    call(ai_api, data=analyze_request(**changes), status=422)
    assert ai_api.fake.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("suggested_department_id", str(uuid4())),
        ("suggested_category", "INVENTED_CATEGORY"),
        ("suggested_priority", "URGENT"),
        ("summary", "short"),
        ("department_reasoning", "x" * 1001),
        ("missing_information", ["item"] * 11),
        ("unexpected", "field"),
    ],
)
def test_invalid_provider_output(ai_api, field, value):
    output = ai_api.fake.structured(None, "{}", object)
    ai_api.fake.calls.clear()
    ai_api.fake.output = {**output, field: value}
    call(ai_api, data=analyze_request(), status=502)
    assert len(ai_api.fake.calls) == 1


def test_null_department_and_deactivated_selection(ai_api):
    ai_api.fake.output = ai_api.fake.structured(None, "{}", object)
    ai_api.fake.output["suggested_department_id"] = None
    result = call(ai_api, data=analyze_request())
    assert result["suggested_department"] is None
    from app.db.models import Department

    with ai_api.db() as db:
        db.get(Department, ai_api.department_id).is_active = False
        db.commit()
    ai_api.fake.output["suggested_department_id"] = str(ai_api.department_id)
    call(ai_api, data=analyze_request(subject="Different fictional road report"), status=502)


@pytest.mark.parametrize(
    "failure,status",
    [
        (TimeoutError("SECRET_MUST_NOT_LEAK"), 504),
        (RuntimeError("SECRET_MUST_NOT_LEAK"), 503),
        (HTTPException(429, "Quota exhausted"), 429),
    ],
)
def test_provider_failure_and_manual_submission(ai_api, failure, status):
    ai_api.fake.failure = failure
    response = ai_api.client.post(
        P + "/ai/analyze-grievance", headers=ai_api.headers(), json=analyze_request()
    )
    assert response.status_code == status
    assert "SECRET_MUST_NOT_LEAK" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert create(ai_api)["status"] == "SUBMITTED"


def test_disabled_and_throttled(ai_api):
    ai_api.runtime.settings = ai_api.runtime.settings.model_copy(update={"ai_enabled": False})
    call(ai_api, data=analyze_request(), status=503)
    assert not ai_api.fake.calls
    ai_api.runtime.settings = ai_api.runtime.settings.model_copy(
        update={"ai_enabled": True, "ai_requests_per_minute": 1}
    )
    # Disabled attempts count toward throttling, to bound failure spam.
    call(ai_api, data=analyze_request(), status=429)


def test_cmo_analysis_is_append_only_advisory(ai_api):
    row = create(ai_api)
    gid = row["id"]
    first = call(ai_api, f"/cmo/grievances/{gid}/ai-analyze", who="cmo")
    second = call(ai_api, f"/cmo/grievances/{gid}/ai-analyze", who="cmo")
    assert first["analysis_id"] != second["analysis_id"]
    assert len(ai_api.fake.calls) == 1
    with ai_api.db() as db:
        stored = db.get(Grievance, UUID(gid))
        assert stored.priority.value == "MEDIUM"
        assert stored.status.value == "SUBMITTED"
        assert stored.category == row["category"]
        assert stored.current_department_id is None
        assert db.scalar(select(func.count()).select_from(GrievanceHistory)) == 1
        records = db.scalars(select(AIAnalysis)).all()
        assert len(records) == 2
        assert all(x.requested_by == ai_api.users["cmo"] for x in records)
        assert records[0].analysis_type == "GRIEVANCE_CLASSIFICATION"
        assert records[0].result_data["is_advisory"] is True
    # Generic citizen DTO does not implicitly expose AI/internal records.
    public = ai_api.client.get(P + f"/grievances/{gid}", headers=ai_api.headers())
    assert first["analysis_id"] not in public.text


@pytest.mark.parametrize("who", ["citizen", "officer"])
@pytest.mark.parametrize("kind", ["ai-analyze", "detect-duplicates"])
def test_cmo_ai_authorization(ai_api, who, kind):
    row = create(ai_api)
    call(ai_api, f"/cmo/grievances/{row['id']}/{kind}", who=who, status=403)
    assert ai_api.fake.calls == [] and ai_api.fake.embed_calls == []


@pytest.mark.parametrize(
    "path",
    [
        "/cmo/grievances/{id}/ai-analyze",
        "/cmo/grievances/{id}/detect-duplicates",
        "/cmo/reports/{id}/ai-analyze",
    ],
)
def test_missing_resources(ai_api, path):
    call(ai_api, path.format(id=uuid4()), who="cmo", status=404)
    assert ai_api.fake.calls == [] and ai_api.fake.embed_calls == []


def make_report(api):
    row = create(api)
    gid = row["id"]
    headers = api.headers("cmo")
    assert (
        api.client.patch(
            P + f"/cmo/grievances/{gid}/review",
            headers=headers,
            json={"remarks": "CMO_PRIVATE_MARKER"},
        ).status_code
        == 200
    )
    assert (
        api.client.post(
            P + f"/cmo/grievances/{gid}/assign",
            headers=headers,
            json={
                "department_id": str(api.department_id),
                "assignment_note": "CMO_ASSIGNMENT_PRIVATE_MARKER",
            },
        ).status_code
        == 200
    )
    assert (
        api.client.post(
            P + f"/officer/grievances/{gid}/updates",
            headers=api.headers("officer"),
            json={
                "message": "The officer reports that inspection was completed.",
                "visibility": "INTERNAL",
            },
        ).status_code
        == 201
    )
    response = api.client.post(
        P + f"/officer/grievances/{gid}/reports",
        headers=api.headers("officer"),
        json={"report_details": "The report states fictional repairs were completed."},
    )
    assert response.status_code == 201
    return gid, response.json()["id"]


def test_report_analysis_provenance_privacy_no_review_decision(ai_api):
    gid, rid = make_report(ai_api)
    result = call(ai_api, f"/cmo/reports/{rid}/ai-analyze", who="cmo")
    assert result["report_id"] == rid and result["is_advisory"]
    assert result["missing_evidence"]
    payload = ai_api.fake.calls[0][1]
    assert "CMO_PRIVATE_MARKER" not in str(payload)
    assert "CMO_ASSIGNMENT_PRIVATE_MARKER" not in str(payload)
    assert "example.test" not in str(payload)
    assert payload["investigation_updates"]
    from app.db.models import ActionTakenReport

    with ai_api.db() as db:
        assert db.get(Grievance, UUID(gid)).status.value == "IN_PROGRESS"
        assert db.get(ActionTakenReport, UUID(rid)).review_status.value == "PENDING"
        record = db.get(AIAnalysis, UUID(result["analysis_id"]))
        assert record.report_id == UUID(rid)
        assert record.grievance_id == UUID(gid)
        assert record.analysis_type == "ACTION_REPORT_REVIEW"


@pytest.mark.parametrize("who", ["citizen", "officer"])
def test_report_ai_role_denial(ai_api, who):
    call(ai_api, f"/cmo/reports/{uuid4()}/ai-analyze", who=who, status=403)
    assert not ai_api.fake.calls


def test_report_analysis_timeout_leaves_report_pending(ai_api):
    gid, rid = make_report(ai_api)
    ai_api.fake.failure = TimeoutError("hidden-key")
    call(ai_api, f"/cmo/reports/{rid}/ai-analyze", who="cmo", status=504)
    with ai_api.db() as db:
        assert db.get(Grievance, UUID(gid)).status.value == "IN_PROGRESS"
        assert db.scalar(select(func.count()).select_from(AIAnalysis)) == 0


def test_vector_capability_fails_before_spending_quota(ai_api, monkeypatch):
    row = create(ai_api)
    monkeypatch.setattr(repository, "vectors_ready", lambda db: False)
    call(ai_api, f"/cmo/grievances/{row['id']}/detect-duplicates", who="cmo", status=503)
    assert ai_api.fake.calls == [] and ai_api.fake.embed_calls == []


def test_persistence_failure_rolls_back(ai_api, monkeypatch):
    row = create(ai_api)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic private database failure")

    monkeypatch.setattr(repository, "save_analysis", fail)
    call(ai_api, f"/cmo/grievances/{row['id']}/ai-analyze", who="cmo", status=500)
    with ai_api.db() as db:
        assert db.scalar(select(func.count()).select_from(AIAnalysis)) == 0
        assert db.get(Grievance, UUID(row["id"])).status.value == "SUBMITTED"


def test_no_ai_history_api_exposes_internal_records(ai_api):
    response = ai_api.client.get(P + "/ai/analyses", headers=ai_api.headers())
    assert response.status_code == 404
