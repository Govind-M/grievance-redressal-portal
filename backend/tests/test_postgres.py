"""PostgreSQL-only tests; never substitute SQLite for these constraints.

TEST_DATABASE_URL must name an EMPTY dedicated database ending in _test.
Migrations run up/down/up once; test data is rolled back after each test.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import verify_password
from app.db.base import Base
from app.db.models import (
    ActionTakenReport,
    AIAnalysis,
    Attachment,
    CitizenFeedback,
    Department,
    DepartmentAssignment,
    Grievance,
    GrievanceHistory,
    User,
)
from app.db.session import get_db
from app.main import create_app
from app.modules.enums import GrievanceStatus, Priority, ReviewStatus, UserRole
from app.modules.grievances.references import generate_reference_number
from scripts.seed import seed

pytestmark = pytest.mark.postgres


@pytest.fixture
def session(pg_engine):
    with pg_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db
        transaction.rollback()


@pytest.fixture
def seeded(session):
    # Test-only values; application/demo credentials always come from local settings.
    settings = Settings(
        seed_citizen_password="unit-test-citizen-only",
        seed_cmo_password="unit-test-admin-only",
        seed_officer_password="unit-test-officer-only",
    )
    seed(session, settings)
    return settings


@pytest.fixture
def case(session, seeded):
    citizen = session.scalar(select(User).where(User.role == UserRole.CITIZEN))
    admin = session.scalar(select(User).where(User.role == UserRole.CMO_ADMIN))
    officer = session.scalar(select(User).where(User.role == UserRole.DEPARTMENT_OFFICER))
    grievance = Grievance(
        reference_number=generate_reference_number(),
        citizen=citizen,
        district="Ernakulam",
        category="Infrastructure",
        subject="Fictional test road",
        description="Synthetic test case",
    )
    session.add(grievance)
    session.flush()
    return grievance, citizen, admin, officer


def test_real_database_health(session):
    application = create_app()
    application.dependency_overrides[get_db] = lambda: session
    with TestClient(application) as client:
        assert client.get("/api/v1/health/db").json() == {
            "status": "healthy",
            "database": "connected",
        }


def test_postgresql_schema(pg_engine):
    inspector = inspect(pg_engine)
    expected = set(Base.metadata.tables)
    if pg_engine._phase5_target == "0005":
        expected.remove("grievance_embeddings")
    assert set(inspector.get_table_names()) == expected | {"alembic_version"}
    enums = {item["name"]: item["labels"] for item in inspector.get_enums()}
    assert enums == {
        "user_role": ["CITIZEN", "CMO_ADMIN", "DEPARTMENT_OFFICER"],
        "grievance_status": ["SUBMITTED", "UNDER_REVIEW", "IN_PROGRESS", "RESOLVED", "REOPENED"],
        "priority": ["LOW", "MEDIUM", "HIGH"],
        "update_visibility": ["PUBLIC", "INTERNAL"],
        "review_status": ["PENDING", "ACCEPTED", "RETURNED"],
    }
    for name, table in Base.metadata.tables.items():
        if name not in expected:
            continue
        assert len(inspector.get_foreign_keys(name)) == len(table.foreign_key_constraints)
    indexes = inspector.get_indexes("department_assignments")
    active = next(
        index for index in indexes if index["name"] == "uq_department_assignments_active_grievance"
    )
    assert active["unique"]
    assert "closed_at IS NULL" in str(active["dialect_options"]["postgresql_where"])


def test_seed_is_idempotent(session, seeded):
    originals = {
        user.email: (user.id, user.password_hash) for user in session.scalars(select(User))
    }
    seed(session, seeded)
    assert session.scalar(select(func.count()).select_from(Department)) == 7
    assert session.scalar(select(func.count()).select_from(User)) == 3
    assert originals == {
        user.email: (user.id, user.password_hash) for user in session.scalars(select(User))
    }
    for user in session.scalars(select(User)):
        key = {
            UserRole.CITIZEN: "seed_citizen_password",
            UserRole.CMO_ADMIN: "seed_cmo_password",
            UserRole.DEPARTMENT_OFFICER: "seed_officer_password",
        }[user.role]
        assert verify_password(getattr(seeded, key).get_secret_value(), user.password_hash)
        assert user.password_hash.startswith("$argon2id$")
        if user.role == UserRole.DEPARTMENT_OFFICER:
            assert user.department.name == "Public Works"
            assert user.department.is_active
        else:
            assert user.department_id is None


def test_seed_missing_credentials_does_not_write(session):
    with pytest.raises(ValueError):
        seed(
            session,
            Settings(seed_citizen_password="", seed_cmo_password="", seed_officer_password=""),
        )
    assert session.scalar(select(func.count()).select_from(Department)) == 0


def test_active_assignment_unique_and_nullable_officer(session, case):
    grievance, _, admin, officer = case
    assignment = DepartmentAssignment(
        grievance=grievance,
        department=officer.department,
        assigner=admin,
        officer=None,
    )
    session.add(assignment)
    session.flush()
    assert assignment.officer_id is None
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            DepartmentAssignment(
                grievance_id=grievance.id,
                department_id=officer.department_id,
                assigned_by=admin.id,
            )
        )
        session.flush()
    assignment.closed_at = datetime.now(UTC) + timedelta(seconds=1)
    session.flush()
    replacement = DepartmentAssignment(
        grievance=grievance,
        department=officer.department,
        assigner=admin,
        officer=officer,
    )
    session.add(replacement)
    session.flush()
    assert len(grievance.assignments) == 2
    assert replacement.officer_id == officer.id
    assert assignment.closed_at is not None


def test_role_department_and_foreign_keys(session, case):
    grievance, citizen, _, officer = case
    with pytest.raises(IntegrityError), session.begin_nested():
        citizen.department_id = officer.department_id
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        officer.department_id = None
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        grievance.citizen_id = uuid4()
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("DELETE FROM users WHERE id = :id"), {"id": citizen.id})


@pytest.mark.parametrize("rating", [0, 6])
def test_feedback_rating_constraint(session, case, rating):
    grievance, citizen, _, _ = case
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            CitizenFeedback(grievance_id=grievance.id, citizen_id=citizen.id, rating=rating)
        )
        session.flush()


def test_multiple_feedback_and_optional_rating(session, case):
    grievance, citizen, _, _ = case
    session.add_all(
        [
            CitizenFeedback(grievance=grievance, citizen=citizen, rating=5),
            CitizenFeedback(
                grievance=grievance, citizen=citizen, rating=None, reopen_requested=True
            ),
        ]
    )
    session.flush()
    assert len(grievance.feedback) == 2


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_history_is_append_only(session, case, operation):
    grievance, citizen, _, _ = case
    history = GrievanceHistory(
        grievance=grievance,
        actor=citizen,
        to_status=GrievanceStatus.SUBMITTED,
    )
    session.add(history)
    session.flush()
    statement = {
        "UPDATE": "UPDATE grievance_history SET remarks = 'overwrite'",
        "DELETE": "DELETE FROM grievance_history",
        "TRUNCATE": "TRUNCATE grievance_history",
    }[operation]
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text(statement))
    assert session.get(GrievanceHistory, history.id) is not None
    with pytest.raises(IntegrityError), session.begin_nested():
        session.delete(grievance)
        session.flush()


def test_report_review_attachments_and_ai(session, case):
    grievance, citizen, admin, officer = case
    assignment = DepartmentAssignment(
        grievance=grievance,
        department=officer.department,
        assigner=admin,
        officer=officer,
    )
    report = ActionTakenReport(
        grievance=grievance,
        assignment=assignment,
        submitter=officer,
        report_details="Fictional inspection report",
    )
    session.add(report)
    session.flush()
    assert report.review_status == ReviewStatus.PENDING
    with pytest.raises(IntegrityError), session.begin_nested():
        report.review_status = ReviewStatus.ACCEPTED
        session.flush()
    report.review_status = ReviewStatus.ACCEPTED
    report.reviewer = admin
    report.reviewed_at = datetime.now(UTC) + timedelta(seconds=1)
    attachment = Attachment(
        grievance=grievance,
        report=report,
        uploader=officer,
        storage_key="test/private/report.txt",
        original_filename="report.txt",
        content_type="text/plain",
        file_size=10,
    )
    session.add(attachment)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        attachment.file_size = -1
        session.flush()
    ai = AIAnalysis(
        grievance=grievance,
        requester=admin,
        model_name="future-model-placeholder",
        analysis_type="CMO_GRIEVANCE_ANALYSIS",
        suggested_priority=Priority.HIGH,
        result_data={"synthetic": True},
    )
    session.add(ai)
    session.flush()
    assert grievance.priority == Priority.MEDIUM
    assert ai.result_data == {"synthetic": True}
    assert len(assignment.reports) == 1
    assert report.attachments == [attachment]


def test_reference_unique_and_native_enum_rejection(session, case):
    grievance, citizen, _, _ = case
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            Grievance(
                reference_number=grievance.reference_number,
                citizen_id=citizen.id,
                district="Test",
                category="Test",
                subject="Duplicate",
                description="Synthetic",
            )
        )
        session.flush()
    with pytest.raises(DataError), session.begin_nested():
        # PostgreSQL itself rejects a value outside the native enum.
        session.execute(
            text("UPDATE grievances SET status = 'INVALID' WHERE id = :id"), {"id": grievance.id}
        )


def test_updated_timestamp_database_trigger(session, case):
    grievance, citizen, _, _ = case
    before = citizen.updated_at
    session.execute(
        text("UPDATE users SET name = 'Updated fictional citizen' WHERE id = :id"),
        {"id": citizen.id},
    )
    session.refresh(citizen)
    assert citizen.updated_at > before
    assert grievance.created_at.utcoffset() == timedelta(0)
