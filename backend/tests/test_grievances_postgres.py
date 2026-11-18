"""Citizen workflows use PostgreSQL savepoints; outer rollback preserves immutable audit records."""

import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from secrets import token_hex
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    AIAnalysis,
    ContactEnquiry,
    Department,
    DepartmentAssignment,
    Grievance,
    GrievanceHistory,
    GrievanceUpdate,
    User,
)
from app.db.session import get_db
from app.main import create_app
from app.modules.enums import GrievanceStatus, Priority, UpdateVisibility, UserRole
from app.modules.grievance_history.service import SUBMISSION_REMARK
from app.modules.grievances import service
from app.modules.grievances.choices import Category
from app.modules.grievances.references import generate_reference_number
from app.modules.grievances.schemas import GrievanceCreate
from scripts.seed import seed

pytestmark = pytest.mark.postgres
PASSWORD = "Fictional-grievance-test-password"
PREFIX = "/api/v1"


def submission(**changes):
    return {
        "district": "Ernakulam",
        "category": "Roads and Infrastructure",
        "subject": "Damaged fictional road",
        "description": "A fictional road near the community hospital needs urgent repairs.",
        **changes,
    }


@pytest.fixture
def api(pg_engine):
    settings = Settings(
        _env_file=None,
        app_env="test",
        jwt_secret_key=token_hex(48),
        seed_citizen_password=PASSWORD,
        seed_cmo_password=PASSWORD,
        seed_officer_password=PASSWORD,
    )
    with pg_engine.connect() as connection:
        outer = connection.begin()

        def db_session():
            return Session(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )

        def request_db():
            with db_session() as db:
                yield db

        with db_session() as db:
            seed(db, settings)
            citizen = db.scalar(select(User).where(User.email == "citizen@example.test"))
            other = User(
                name="Other Fictional Citizen",
                email="other@example.test",
                password_hash=citizen.password_hash,
                role=UserRole.CITIZEN,
                is_active=True,
            )
            db.add(other)
            db.commit()
            users = {user.email.split("@")[0]: user.id for user in db.scalars(select(User))}
        app = create_app(settings)
        app.dependency_overrides[get_db] = request_db
        tokens = {}
        try:
            with TestClient(
                app, headers={"Origin": "http://localhost:5173"}, raise_server_exceptions=False
            ) as client:

                def headers(who="citizen"):
                    if who not in tokens:
                        response = client.post(
                            f"{PREFIX}/auth/login",
                            json={"email": f"{who}@example.test", "password": PASSWORD},
                        )
                        assert response.status_code == 200
                        tokens[who] = response.json()
                    return {"Authorization": f"Bearer {tokens[who]['access_token']}"}

                yield SimpleNamespace(
                    client=client,
                    db=db_session,
                    headers=headers,
                    users=users,
                    connection=connection,
                    tokens=tokens,
                )
        finally:
            outer.rollback()


def create(api, **changes):
    response = api.client.post(
        f"{PREFIX}/grievances", headers=api.headers(), json=submission(**changes)
    )
    assert response.status_code == 201
    return response.json()


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def fixture_grievances(api, *, who="citizen", statuses=None, same_timestamp=False):
    statuses = statuses or [
        GrievanceStatus.SUBMITTED,
        GrievanceStatus.UNDER_REVIEW,
        GrievanceStatus.IN_PROGRESS,
        GrievanceStatus.RESOLVED,
        GrievanceStatus.REOPENED,
    ]
    base = datetime(2026, 1, 1, tzinfo=UTC)
    result = []
    with api.db() as db:
        for index, status in enumerate(statuses):
            row = Grievance(
                citizen_id=api.users[who],
                reference_number=generate_reference_number(),
                district="Ernakulam" if index % 2 == 0 else "Kollam",
                category=Category.ROADS_AND_INFRASTRUCTURE
                if index % 2 == 0
                else Category.HEALTHCARE,
                subject=f"Fictional grievance {index}",
                description="Synthetic fixture description.",
                status=status,
                priority=Priority.MEDIUM,
                created_at=base if same_timestamp else base + timedelta(days=index),
                updated_at=base + timedelta(days=len(statuses) - index),
            )
            db.add(row)
            db.flush()
            result.append(
                {"id": str(row.id), "status": status, "reference_number": row.reference_number}
            )
        db.commit()
    return result


@contextmanager
def statements(connection):
    captured = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)  # SQL shapes only; do not capture passwords/token parameters.

    event.listen(connection, "before_cursor_execute", capture)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", capture)


def test_citizen_creation_initial_state_and_persisted_history(api):
    result = create(
        api,
        district="  eRNAKULAM  ",
        category=" roads AND infrastructure ",
        subject="  Damaged fictional road  ",
    )
    assert re.fullmatch(r"CMK-\d{4}-[0-9A-F]{16}", result["reference_number"])
    assert result["district"] == "Ernakulam"
    assert result["category"] == "Roads and Infrastructure"
    assert result["subject"] == "Damaged fictional road"
    assert result["status"] == "SUBMITTED" and result["priority"] == "MEDIUM"
    assert result["assigned_department_name"] is None and result["resolved_at"] is None
    assert result["updates"] == []
    history = result["history"]
    assert len(history) == 1
    assert history[0]["from_status"] is None and history[0]["to_status"] == "SUBMITTED"
    assert history[0]["remarks"] == SUBMISSION_REMARK
    assert history[0]["actor_label"] == "Citizen"
    with api.db() as db:
        row = db.get(Grievance, UUID(result["id"]))
        assert row.citizen_id == api.users["citizen"]
        assert row.current_department_id is None and row.due_at is None and row.resolved_at is None
        assert len(row.history) == 1 and row.history[0].changed_by == row.citizen_id
        assert row.history[0].remarks_visibility == UpdateVisibility.PUBLIC
        assert row.created_at.utcoffset() == timedelta(0)
    another = create(api)
    assert (
        another["id"] != result["id"] and another["reference_number"] != result["reference_number"]
    )


@pytest.mark.parametrize(
    "privileged",
    [
        "citizen_id",
        "status",
        "priority",
        "current_department_id",
        "reference_number",
        "resolved_at",
        "history",
        "remarks_visibility",
        "due_at",
    ],
)
def test_overposting_privileged_fields_is_rejected(api, privileged):
    response = api.client.post(
        f"{PREFIX}/grievances", headers=api.headers(), json=submission(**{privileged: "forbidden"})
    )
    assert response.status_code == 422
    with api.db() as db:
        assert count(db, Grievance) == 0 and count(db, GrievanceHistory) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"district": "Not Kerala"},
        {"category": "Unknown"},
        {"subject": "bad"},
        {"description": "bad"},
        {"description": " " * 50},
        {"subject": " " * 20},
    ],
)
def test_invalid_submission_api_returns_422(api, changes):
    assert (
        api.client.post(
            f"{PREFIX}/grievances", headers=api.headers(), json=submission(**changes)
        ).status_code
        == 422
    )


def test_maximum_description_is_preserved(api):
    result = create(api, description="  " + "d" * 10000 + "  ")
    assert result["description"] == "d" * 10000
    with api.db() as db:
        assert len(db.get(Grievance, UUID(result["id"])).description) == 10000


@pytest.mark.parametrize("who", ["cmo", "officer"])
def test_admin_and_officer_cannot_use_citizen_endpoints(api, who):
    headers = api.headers(who)
    assert (
        api.client.post(f"{PREFIX}/grievances", headers=headers, json=submission()).status_code
        == 403
    )
    for path in ("/grievances/me", "/grievances/me/statistics"):
        assert api.client.get(PREFIX + path, headers=headers).status_code == 403


def test_history_failure_rolls_back_creation_without_touching_existing_rows(api, monkeypatch):
    existing = create(api)

    def broken_history(db, grievance_id, citizen_id):
        db.add(
            GrievanceHistory(
                grievance_id=grievance_id,
                to_status=GrievanceStatus.SUBMITTED,
                changed_by=uuid4(),
                remarks="A deliberately invalid synthetic FK",
            )
        )

    monkeypatch.setattr(service, "add_initial_history", broken_history)
    response = api.client.post(
        f"{PREFIX}/grievances",
        headers=api.headers(),
        json=submission(subject="Should roll back completely"),
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    with api.db() as db:
        assert count(db, Grievance) == 1 and count(db, GrievanceHistory) == 1
        assert db.get(Grievance, UUID(existing["id"])).subject == existing["subject"]
        assert db.scalar(text("SELECT 1")) == 1


def test_reference_collision_retry_preserves_outer_transaction(api, monkeypatch):
    existing = create(api)
    unique = generate_reference_number()
    refs = iter([existing["reference_number"], unique])
    attempts = []

    def reference():
        attempts.append(1)
        return next(refs)

    monkeypatch.setattr(service, "generate_reference_number", reference)
    with api.db() as db:
        citizen = db.get(User, api.users["citizen"])
        db.add(
            ContactEnquiry(
                name="Synthetic pending work",
                email="pending@example.test",
                subject="Preserve pending work",
                message="Pending work must survive a collision",
            )
        )
        result = service.create(db, citizen, GrievanceCreate(**submission()))
        assert result.reference_number == unique
        assert count(db, ContactEnquiry) == 1
        assert db.scalar(text("SELECT 1")) == 1
        assert count(db, Grievance) == 2 and count(db, GrievanceHistory) == 2
        assert (
            db.get(Grievance, UUID(existing["id"])).reference_number == existing["reference_number"]
        )
    assert len(attempts) == 2


def test_reference_collision_exhaustion_is_bounded_and_recoverable(api, monkeypatch):
    existing = create(api)
    attempts = []

    def collision():
        attempts.append(1)
        return existing["reference_number"]

    monkeypatch.setattr(service, "generate_reference_number", collision)
    response = api.client.post(f"{PREFIX}/grievances", headers=api.headers(), json=submission())
    assert response.status_code == 503
    assert response.json() == {"detail": "Unable to allocate a reference. Please retry."}
    assert len(attempts) == service.REFERENCE_ATTEMPTS == 5
    with api.db() as db:
        assert count(db, Grievance) == 1 and count(db, GrievanceHistory) == 1
        assert db.get(Grievance, UUID(existing["id"])).description == existing["description"]
    monkeypatch.setattr(service, "generate_reference_number", generate_reference_number)
    create(api)


def test_list_is_owned_paginated_and_stably_sorted(api):
    owned = fixture_grievances(api, same_timestamp=True)
    fixture_grievances(api, who="other")
    all_ids = []
    for page, expected_size in ((1, 2), (2, 2), (3, 1), (4, 0)):
        response = api.client.get(
            f"{PREFIX}/grievances/me",
            headers=api.headers(),
            params={"page": page, "page_size": 2, "sort_order": "asc"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["pagination"] == {
            "page": page,
            "page_size": 2,
            "total_items": 5,
            "total_pages": 3,
        }
        assert len(result["items"]) == expected_size
        assert all("description" not in item for item in result["items"])
        all_ids.extend(item["id"] for item in result["items"])
    assert all_ids == sorted(row["id"] for row in owned)
    assert len(set(all_ids)) == 5


@pytest.mark.parametrize(
    ("params", "count_expected"),
    [
        ({"status": "RESOLVED"}, 1),
        ({"category": " healthcare "}, 2),
        ({"district": " ernakulam "}, 3),
        ({"district": "Kollam", "category": "Healthcare", "status": "UNDER_REVIEW"}, 1),
        ({"district": "Kannur"}, 0),
    ],
)
def test_list_filters_and_totals(api, params, count_expected):
    fixture_grievances(api)
    fixture_grievances(api, who="other")
    response = api.client.get(f"{PREFIX}/grievances/me", headers=api.headers(), params=params)
    assert response.status_code == 200
    assert response.json()["pagination"]["total_items"] == count_expected
    assert len(response.json()["items"]) == count_expected


@pytest.mark.parametrize(
    ("sort_by", "sort_order", "reverse"),
    [
        ("created_at", "asc", False),
        ("created_at", "desc", True),
        ("updated_at", "asc", True),
        ("updated_at", "desc", False),
    ],
)
def test_allowed_sort_orders(api, sort_by, sort_order, reverse):
    rows = fixture_grievances(api)
    result = api.client.get(
        f"{PREFIX}/grievances/me",
        headers=api.headers(),
        params={"sort_by": sort_by, "sort_order": sort_order},
    ).json()
    expected = list(reversed(rows)) if reverse else rows
    assert [item["id"] for item in result["items"]] == [row["id"] for row in expected]


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 101},
        {"status": "INVALID"},
        {"sort_by": "subject; DROP TABLE users"},
        {"sort_order": "random"},
        {"citizen_id": "other"},
        {"district": "Not Kerala"},
        {"category": "Arbitrary"},
    ],
)
def test_invalid_filters_are_rejected(api, params):
    assert (
        api.client.get(f"{PREFIX}/grievances/me", headers=api.headers(), params=params).status_code
        == 422
    )


def test_empty_listing_and_statistics(api):
    listing = api.client.get(f"{PREFIX}/grievances/me", headers=api.headers()).json()
    assert listing == {
        "items": [],
        "pagination": {"page": 1, "page_size": 10, "total_items": 0, "total_pages": 0},
    }
    stats = api.client.get(f"{PREFIX}/grievances/me/statistics", headers=api.headers()).json()
    assert stats == {
        "total": 0,
        "pending": 0,
        "resolved": 0,
        "by_status": {status: 0 for status in GrievanceStatus},
    }


@pytest.mark.parametrize("suffix", ["", "/history"])
def test_detail_and_history_ownership_and_cmo_access(api, suffix):
    result = create(api)
    path = f"{PREFIX}/grievances/{result['id']}{suffix}"
    assert api.client.get(path, headers=api.headers()).status_code == 200
    assert api.client.get(path, headers=api.headers("cmo")).status_code == 200
    assert api.client.get(path, headers=api.headers("other")).status_code == 404
    assert api.client.get(path, headers=api.headers("officer")).status_code == 403
    assert api.client.get(path).status_code == 401
    assert (
        api.client.get(f"{PREFIX}/grievances/{uuid4()}{suffix}", headers=api.headers()).status_code
        == 404
    )
    assert (
        api.client.get(f"{PREFIX}/grievances/not-a-uuid{suffix}", headers=api.headers()).status_code
        == 422
    )


def test_tracking_is_authenticated_owner_or_cmo_only(api):
    result = create(api)
    path = f"{PREFIX}/grievances/track/{result['reference_number'].lower()}"
    tracked = api.client.get(path, headers=api.headers())
    assert tracked.status_code == 200
    assert tracked.json()["history"] == result["history"]
    assert tracked.json()["reference_number"] == result["reference_number"]
    assert "description" not in tracked.json()
    assert api.client.get(path, headers=api.headers("cmo")).status_code == 200
    assert api.client.get(path, headers=api.headers("other")).status_code == 404
    assert api.client.get(path, headers=api.headers("officer")).status_code == 403
    assert api.client.get(path).status_code == 401
    assert (
        api.client.get(
            f"{PREFIX}/grievances/track/CMK-2026-0000000000000000", headers=api.headers()
        ).status_code
        == 404
    )


def test_history_and_updates_hide_internal_data_and_use_real_chronology(api):
    result = create(api)
    with api.db() as db:
        grievance = db.get(Grievance, UUID(result["id"]))
        admin = db.get(User, api.users["cmo"])
        officer = db.get(User, api.users["officer"])
        base = grievance.created_at
        grievance.status = GrievanceStatus.IN_PROGRESS
        grievance.current_department_id = officer.department_id
        db.add_all(
            [
                GrievanceHistory(
                    grievance_id=grievance.id,
                    from_status=GrievanceStatus.UNDER_REVIEW,
                    to_status=GrievanceStatus.IN_PROGRESS,
                    changed_by=officer.id,
                    remarks="Public inspection milestone",
                    remarks_visibility=UpdateVisibility.PUBLIC,
                    created_at=base + timedelta(minutes=2),
                ),
                GrievanceHistory(
                    grievance_id=grievance.id,
                    from_status=GrievanceStatus.SUBMITTED,
                    to_status=GrievanceStatus.UNDER_REVIEW,
                    changed_by=admin.id,
                    remarks="CONFIDENTIAL CMO decision note",
                    created_at=base + timedelta(minutes=1),
                ),
                GrievanceUpdate(
                    grievance_id=grievance.id,
                    author_id=officer.id,
                    message="CONFIDENTIAL officer update",
                    visibility=UpdateVisibility.INTERNAL,
                ),
                GrievanceUpdate(
                    grievance_id=grievance.id,
                    author_id=officer.id,
                    message="Public work is progressing",
                    visibility=UpdateVisibility.PUBLIC,
                ),
                DepartmentAssignment(
                    grievance_id=grievance.id,
                    department_id=officer.department_id,
                    officer_id=officer.id,
                    assigned_by=admin.id,
                    assignment_note="CONFIDENTIAL assignment instructions",
                ),
            ]
        )
        db.commit()
        hidden_ids = [str(admin.id), str(officer.id)]
    for who in ("citizen", "cmo"):
        for path in (
            f"/grievances/{result['id']}",
            f"/grievances/track/{result['reference_number']}",
            f"/grievances/{result['id']}/history",
        ):
            response = api.client.get(PREFIX + path, headers=api.headers(who))
            assert response.status_code == 200
            assert "CONFIDENTIAL" not in response.text
            assert "password_hash" not in response.text and "storage_key" not in response.text
            assert all(identifier not in response.text for identifier in hidden_ids)
            body = response.json()
            history = body if isinstance(body, list) else body["history"]
            assert [entry["to_status"] for entry in history] == [
                "SUBMITTED",
                "UNDER_REVIEW",
                "IN_PROGRESS",
            ]
            assert history[1]["remarks"] is None
            assert history[1]["actor_label"] == "Chief Minister's Office"
            assert history[2]["remarks"] == "Public inspection milestone"
            assert history[2]["actor_label"] == "Department Officer"
            if isinstance(body, dict):
                assert body["assigned_department_name"] == "Public Works"
                assert len(body["updates"]) == 1
                assert body["updates"][0]["message"] == "Public work is progressing"


def test_statistics_are_aggregated_and_owner_scoped(api):
    fixture_grievances(
        api,
        statuses=[
            GrievanceStatus.SUBMITTED,
            GrievanceStatus.SUBMITTED,
            GrievanceStatus.UNDER_REVIEW,
            GrievanceStatus.IN_PROGRESS,
            GrievanceStatus.RESOLVED,
            GrievanceStatus.RESOLVED,
            GrievanceStatus.REOPENED,
        ],
    )
    fixture_grievances(api, who="other", statuses=[GrievanceStatus.RESOLVED] * 4)
    headers = api.headers()
    with statements(api.connection) as captured:
        response = api.client.get(f"{PREFIX}/grievances/me/statistics", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "total": 7,
        "pending": 5,
        "resolved": 2,
        "by_status": {
            "SUBMITTED": 2,
            "UNDER_REVIEW": 1,
            "IN_PROGRESS": 1,
            "RESOLVED": 2,
            "REOPENED": 1,
        },
    }
    grievance_selects = [sql for sql in captured if "FROM grievances" in sql]
    assert len(grievance_selects) == 1 and "GROUP BY" in grievance_selects[0]


def test_list_uses_database_pagination_and_scoping(api):
    fixture_grievances(api)
    headers = api.headers()
    with statements(api.connection) as captured:
        response = api.client.get(f"{PREFIX}/grievances/me?page_size=2&page=2", headers=headers)
    assert response.status_code == 200
    queries = [sql for sql in captured if "FROM grievances" in sql]
    assert len(queries) == 2
    assert all("grievances.citizen_id" in sql and "WHERE" in sql for sql in queries)
    assert "LIMIT" in queries[1] and "OFFSET" in queries[1]
    assert "grievances.description" not in queries[1]


def test_detail_does_not_add_queries_per_public_update(api):
    result = create(api)
    headers = api.headers()
    with statements(api.connection) as before:
        assert (
            api.client.get(f"{PREFIX}/grievances/{result['id']}", headers=headers).status_code
            == 200
        )
    with api.db() as db:
        db.add_all(
            [
                GrievanceUpdate(
                    grievance_id=UUID(result["id"]),
                    author_id=api.users["citizen"],
                    visibility=UpdateVisibility.PUBLIC,
                    message=f"Public synthetic progress {index}",
                )
                for index in range(20)
            ]
        )
        db.commit()
    with statements(api.connection) as after:
        response = api.client.get(f"{PREFIX}/grievances/{result['id']}", headers=headers)
    assert len(response.json()["updates"]) == 20
    assert len([sql for sql in before if sql.lstrip().startswith("SELECT")]) == len(
        [sql for sql in after if sql.lstrip().startswith("SELECT")]
    )


def test_departments_are_public_active_sorted_and_database_driven(api):
    with api.db() as db:
        health = db.scalar(select(Department).where(Department.name == "Health"))
        health.is_active = False
        inactive_id = str(health.id)
        new = Department(
            name="Fictional Additional Department",
            description="Database-backed fixture",
            is_active=True,
        )
        db.add(new)
        db.commit()
        new_id = str(new.id)
    response = api.client.get(f"{PREFIX}/departments")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 7
    assert [item["name"] for item in rows] == sorted(item["name"] for item in rows)
    assert all(item["id"] != inactive_id for item in rows)
    assert any(item["id"] == new_id for item in rows)
    assert all(set(item) == {"id", "name", "description"} for item in rows)
    detail = api.client.get(f"{PREFIX}/departments/{new_id}")
    assert detail.json() == {
        "id": new_id,
        "name": "Fictional Additional Department",
        "description": "Database-backed fixture",
        "is_active": True,
    }
    assert api.client.get(f"{PREFIX}/departments/{inactive_id}").status_code == 404
    assert api.client.get(f"{PREFIX}/departments/{uuid4()}").status_code == 404
    assert api.client.get(f"{PREFIX}/departments/not-a-uuid").status_code == 422
    assert len(api.client.get(f"{PREFIX}/departments?q=works").json()) == 1
    assert api.client.get(f"{PREFIX}/departments?q=%25").json() == []


def test_revocation_and_refresh_still_protect_grievance_routes(api):
    result = create(api)
    headers = api.headers()
    token_data = api.tokens["citizen"]
    refreshed = api.client.post(
        f"{PREFIX}/auth/refresh", headers={"X-CSRF-Token": token_data["csrf_token"]}
    )
    assert refreshed.status_code == 200
    assert api.client.get(f"{PREFIX}/grievances/{result['id']}", headers=headers).status_code == 200
    logout_headers = {
        "Authorization": f"Bearer {refreshed.json()['access_token']}",
        "X-CSRF-Token": refreshed.json()["csrf_token"],
    }
    assert api.client.post(f"{PREFIX}/auth/logout", headers=logout_headers).status_code == 204
    for path in (
        "/grievances/me",
        "/grievances/me/statistics",
        f"/grievances/{result['id']}",
        f"/grievances/track/{result['reference_number']}",
    ):
        assert api.client.get(PREFIX + path, headers=headers).status_code == 401
    assert (
        api.client.post(f"{PREFIX}/grievances", headers=headers, json=submission()).status_code
        == 401
    )


def test_submission_does_not_apply_ai_or_create_assignment(api):
    result = create(api)
    with api.db() as db:
        db.add(
            AIAnalysis(
                grievance_id=UUID(result["id"]),
                requested_by=api.users["citizen"],
                model_name="Synthetic future model",
                analysis_type="TEST",
                suggested_priority=Priority.HIGH,
                suggested_category="Healthcare",
            )
        )
        db.commit()
    response = api.client.get(f"{PREFIX}/grievances/{result['id']}", headers=api.headers())
    assert response.json()["priority"] == "MEDIUM"
    assert response.json()["category"] == "Roads and Infrastructure"
    assert response.json()["assigned_department_name"] is None
    with api.db() as db:
        assert count(db, DepartmentAssignment) == 0


def test_citizen_cannot_mutate_history_or_official_grievance_state(api):
    result = create(api)
    for method, path in (
        ("post", f"/grievances/{result['id']}/history"),
        ("patch", f"/grievances/{result['id']}"),
        ("delete", f"/grievances/{result['id']}/history"),
    ):
        response = getattr(api.client, method)(PREFIX + path, headers=api.headers())
        assert response.status_code == 405
