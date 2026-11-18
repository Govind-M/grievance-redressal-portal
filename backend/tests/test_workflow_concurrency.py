"""Independent PostgreSQL connections exercise actual locks, not shared-session mocks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import BACKEND_DIR
from app.db.models import ActionTakenReport, Department, DepartmentAssignment, Grievance, User
from app.modules.cmo import schemas as dto
from app.modules.cmo import service as cmo
from app.modules.enums import GrievanceStatus, UserRole
from app.modules.officer import service as officer

pytestmark = pytest.mark.postgres


def test_concurrent_assignment_submission_and_review(pg_engine):
    # A dedicated synthetic schema permits real commits without deleting immutable audit rows.
    # pg_engine has already enforced the dedicated *_test database safety guard.
    schema = "phase4_concurrency_" + uuid4().hex
    with pg_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        pg_engine.url,
        hide_parameters=True,
        connect_args={
            "options": f"-c search_path={schema} -c timezone=UTC -c statement_timeout=15000"
        },
    )
    try:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            # This isolated search_path intentionally excludes public (and its vector type).
            # Phase 4 lock tests need only the mandatory core; vector SQL has separate tests.
            command.upgrade(config, "0005")
        with Session(engine, expire_on_commit=False) as db:
            department = Department(
                name="Synthetic concurrency department", description="Test only"
            )
            db.add(department)
            db.flush()
            citizen = User(
                name="Synthetic citizen",
                email="race-citizen@example.test",
                password_hash="unused",
                role=UserRole.CITIZEN,
            )
            admin = User(
                name="Synthetic administrator",
                email="race-admin@example.test",
                password_hash="unused",
                role=UserRole.CMO_ADMIN,
            )
            worker = User(
                name="Synthetic officer",
                email="race-officer@example.test",
                password_hash="unused",
                role=UserRole.DEPARTMENT_OFFICER,
                department_id=department.id,
            )
            db.add_all([citizen, admin, worker])
            db.flush()
            row = Grievance(
                reference_number="CMK-CONCURRENCY-" + uuid4().hex[:16],
                citizen_id=citizen.id,
                district="Ernakulam",
                category="Other",
                subject="Synthetic concurrency grievance",
                description="Test only",
                status=GrievanceStatus.UNDER_REVIEW,
            )
            db.add(row)
            db.commit()
            gid, aid, oid, did = row.id, admin.id, worker.id, department.id

        def compete(operation):
            barrier = Barrier(2)

            def attempt(index):
                with Session(engine, expire_on_commit=False) as db:
                    user = db.get(User, oid if operation == "report" else aid)
                    barrier.wait(timeout=10)
                    try:
                        if operation == "assign":
                            cmo.mutate(
                                db,
                                user,
                                gid,
                                "assign",
                                dto.AssignmentInput(
                                    department_id=did,
                                    assignment_note="Concurrent assignment attempt",
                                ),
                            )
                        elif operation == "report":
                            officer.submit_report(
                                db,
                                user,
                                gid,
                                dto.ReportInput(
                                    report_details="Fictional concurrent investigation report"
                                ),
                            )
                        else:
                            cmo.review_report(
                                db,
                                user,
                                rid,
                                dto.ReportReviewInput(
                                    decision="ACCEPTED" if index == 0 else "RETURNED",
                                    review_remarks="Concurrent review decision reason",
                                ),
                            )
                        return 200
                    except HTTPException as exc:
                        return exc.status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                return sorted(pool.map(attempt, range(2)))

        assert compete("assign") == [200, 409]
        assert compete("report") == [200, 409]
        with Session(engine) as db:
            rid = db.scalar(select(ActionTakenReport.id))
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(DepartmentAssignment)
                    .where(DepartmentAssignment.closed_at.is_(None))
                )
                == 1
            )
            assert db.scalar(select(func.count()).select_from(ActionTakenReport)) == 1
        assert compete("review") == [200, 409]
        with Session(engine) as db:
            report = db.get(ActionTakenReport, rid)
            grievance = db.get(Grievance, gid)
            assert report.review_status.value in ("ACCEPTED", "RETURNED")
            assert (grievance.status == GrievanceStatus.RESOLVED) == (
                report.review_status.value == "ACCEPTED"
            )
    finally:
        engine.dispose()
        with pg_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
