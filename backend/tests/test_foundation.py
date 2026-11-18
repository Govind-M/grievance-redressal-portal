import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import configure_mappers

from app.core.config import Settings
from app.db import models
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.modules.enums import GrievanceStatus, Priority, ReviewStatus, UpdateVisibility, UserRole
from app.modules.grievances.references import generate_reference_number

EXPECTED_TABLES = {
    "grievance_embeddings",
    "grievance_escalations",
    "user_sessions",
    "revoked_tokens",
    "users",
    "departments",
    "grievances",
    "grievance_history",
    "department_assignments",
    "grievance_updates",
    "action_taken_reports",
    "attachments",
    "citizen_feedback",
    "contact_enquiries",
    "ai_analyses",
}


def test_application_and_health():
    application = create_app()
    with TestClient(application) as client:
        assert client.get("/api/v1/health").json() == {
            "status": "healthy",
            "service": "CM Kerala Grievance API",
            "version": "1.0.0",
        }
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/api/v1/grievances").status_code == 405
        assert client.get("/api/v1/grievances/me").status_code == 401


def test_database_unavailable_is_sanitized():
    class UnavailableSession:
        def execute(self, statement):
            raise OperationalError("SELECT 1", {}, Exception("secret password"))

    application = create_app()
    application.dependency_overrides[get_db] = lambda: UnavailableSession()
    with TestClient(application) as client:
        response = client.get("/api/v1/health/db")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}


def test_database_endpoint_executes_query():
    class QuerySession:
        def execute(self, statement):
            assert str(statement) == "SELECT 1"

    application = create_app()
    application.dependency_overrides[get_db] = lambda: QuerySession()
    with TestClient(application) as client:
        assert client.get("/api/v1/health/db").json() == {
            "status": "healthy",
            "database": "connected",
        }


def test_model_registration_and_relationships():
    configure_mappers()
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert models.User.grievances.property.back_populates == "citizen"
    assert models.DepartmentAssignment.officer.property.back_populates == "officer_assignments"
    for table in Base.metadata.sorted_tables:
        assert table.c.id.primary_key
        for fk in table.foreign_keys:
            assert fk.column.table.name in EXPECTED_TABLES
            assert fk.ondelete == "RESTRICT"
    assignment = Base.metadata.tables["department_assignments"]
    assert assignment.c.officer_id.nullable
    index = next(
        i for i in assignment.indexes if i.name == "uq_department_assignments_active_grievance"
    )
    assert index.unique
    assert str(index.dialect_options["postgresql"]["where"]) == "closed_at IS NULL"


def test_enum_values():
    assert list(UserRole) == ["CITIZEN", "CMO_ADMIN", "DEPARTMENT_OFFICER"]
    assert list(GrievanceStatus) == [
        "SUBMITTED",
        "UNDER_REVIEW",
        "IN_PROGRESS",
        "RESOLVED",
        "REOPENED",
    ]
    assert list(Priority) == ["LOW", "MEDIUM", "HIGH"]
    assert list(UpdateVisibility) == ["PUBLIC", "INTERNAL"]
    assert list(ReviewStatus) == ["PENDING", "ACCEPTED", "RETURNED"]


def test_reference_numbers():
    references = {generate_reference_number() for _ in range(2000)}
    assert len(references) == 2000
    assert all(re.fullmatch(r"CMK-\d{4}-[A-F0-9]{16}", item) for item in references)


def test_configuration():
    assert Settings(
        cors_origins="http://localhost:5173, http://localhost:4173"
    ).allowed_origins == [
        "http://localhost:5173",
        "http://localhost:4173",
    ]
    with pytest.raises(ValueError):
        Settings(database_url="sqlite:///test.db")
