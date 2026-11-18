"""Citizen workflows; CMO/officer lifecycle operations live in grievances.workflow."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Grievance, User
from app.modules.enums import GrievanceStatus, Priority, UserRole
from app.modules.grievance_history.schemas import PublicHistoryEntry
from app.modules.grievance_history.service import add_initial_history, public_history
from app.modules.grievances import repository
from app.modules.grievances.references import generate_reference_number
from app.modules.grievances.schemas import (
    GrievanceCreate,
    GrievanceDetail,
    GrievanceListQuery,
    GrievancePage,
    GrievanceStatistics,
    GrievanceSummary,
    GrievanceTracking,
    Pagination,
)

REFERENCE_ATTEMPTS = 5


def _visible(
    db: Session, user: User, *, grievance_id: UUID | None = None, reference: str | None = None
) -> Grievance:
    grievance = repository.visible_grievance(
        db, user, grievance_id=grievance_id, reference=reference
    )
    if grievance is None:
        raise HTTPException(status_code=404, detail="Grievance not found.")
    return grievance


def detail(db: Session, user: User, grievance_id: UUID) -> GrievanceDetail:
    grievance = _visible(db, user, grievance_id=grievance_id)
    return GrievanceDetail(
        **GrievanceSummary.model_validate(grievance).model_dump(),
        description=grievance.description,
        assigned_department_name=(
            grievance.current_department.name if grievance.current_department else None
        ),
        resolved_at=grievance.resolved_at,
        history=public_history(db, grievance.id),
        updates=repository.public_updates(db, grievance.id),
    )


def create(db: Session, citizen: User, data: GrievanceCreate) -> GrievanceDetail:
    if not citizen.is_active or citizen.role != UserRole.CITIZEN:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    try:
        for _ in range(REFERENCE_ATTEMPTS):
            try:
                # Authentication already began the request transaction. A savepoint isolates
                # a reference uniqueness failure without discarding that outer transaction.
                with db.begin_nested():
                    grievance = Grievance(
                        citizen_id=citizen.id,
                        reference_number=generate_reference_number(),
                        district=data.district.value,
                        category=data.category.value,
                        subject=data.subject,
                        description=data.description,
                        status=GrievanceStatus.SUBMITTED,
                        priority=Priority.MEDIUM,
                        current_department_id=None,
                        resolved_at=None,
                    )
                    db.add(grievance)
                    db.flush()
                    add_initial_history(db, grievance.id, citizen.id)
                    db.flush()
            except IntegrityError as exc:
                constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                if constraint != "uq_grievances_reference_number":
                    raise
                continue
            response = detail(db, citizen, grievance.id)
            db.commit()  # Grievance + audit entry commit together, only after response construction.
            return response
        raise HTTPException(status_code=503, detail="Unable to allocate a reference. Please retry.")
    except Exception:
        db.rollback()
        raise


def list_mine(db: Session, citizen: User, filters: GrievanceListQuery) -> GrievancePage:
    rows, total = repository.list_owned(db, citizen.id, filters)
    return GrievancePage(
        items=[GrievanceSummary.model_validate(row) for row in rows],
        pagination=Pagination(
            page=filters.page,
            page_size=filters.page_size,
            total_items=total,
            total_pages=(total + filters.page_size - 1) // filters.page_size,
        ),
    )


def track(db: Session, user: User, reference: str) -> GrievanceTracking:
    grievance = _visible(db, user, reference=reference.strip().upper())
    return GrievanceTracking(
        reference_number=grievance.reference_number,
        subject=grievance.subject,
        status=grievance.status,
        assigned_department_name=(
            grievance.current_department.name if grievance.current_department else None
        ),
        created_at=grievance.created_at,
        updated_at=grievance.updated_at,
        history=public_history(db, grievance.id),
        updates=repository.public_updates(db, grievance.id),
    )


def history(db: Session, user: User, grievance_id: UUID) -> list[PublicHistoryEntry]:
    _visible(db, user, grievance_id=grievance_id)
    return public_history(db, grievance_id)


def statistics(db: Session, citizen: User) -> GrievanceStatistics:
    counts = repository.status_counts(db, citizen.id)
    by_status = {status: counts.get(status, 0) for status in GrievanceStatus}
    total = sum(by_status.values())
    resolved = by_status[GrievanceStatus.RESOLVED]
    return GrievanceStatistics(
        total=total, resolved=resolved, pending=total - resolved, by_status=by_status
    )
