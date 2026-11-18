"""SQL ownership scoping, bounded result sets, and explicit public projections."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload, load_only, raiseload

from app.db.models import Grievance, GrievanceUpdate, User
from app.modules.enums import GrievanceStatus, UpdateVisibility, UserRole
from app.modules.grievance_history.service import ACTOR_LABELS
from app.modules.grievances.schemas import GrievanceListQuery, PublicUpdate


def visible_query(user: User) -> Select[tuple[Grievance]]:
    query = select(Grievance)
    if user.role == UserRole.CITIZEN:
        return query.where(Grievance.citizen_id == user.id)
    if user.role == UserRole.CMO_ADMIN:
        return query
    raise HTTPException(status_code=403, detail="Insufficient permissions.")


def visible_grievance(
    db: Session, user: User, *, grievance_id: UUID | None = None, reference: str | None = None
) -> Grievance | None:
    query = visible_query(user)
    if grievance_id is not None:
        query = query.where(Grievance.id == grievance_id)
    elif reference is not None:
        query = query.where(Grievance.reference_number == reference)
    else:
        raise ValueError("An identifier is required")
    return db.scalar(query.options(joinedload(Grievance.current_department), raiseload("*")))


def list_owned(
    db: Session, citizen_id: UUID, filters: GrievanceListQuery
) -> tuple[list[Grievance], int]:
    conditions = [Grievance.citizen_id == citizen_id]
    if filters.status is not None:
        conditions.append(Grievance.status == filters.status)
    if filters.category is not None:
        conditions.append(Grievance.category == filters.category.value)
    if filters.district is not None:
        conditions.append(Grievance.district == filters.district.value)
    total = db.scalar(select(func.count()).select_from(Grievance).where(*conditions)) or 0
    columns = {"created_at": Grievance.created_at, "updated_at": Grievance.updated_at}
    sort = columns[filters.sort_by]
    ordering = (
        (sort.asc(), Grievance.id.asc())
        if filters.sort_order == "asc"
        else (sort.desc(), Grievance.id.desc())
    )
    rows = db.scalars(
        select(Grievance)
        .where(*conditions)
        .options(
            load_only(
                Grievance.id,
                Grievance.reference_number,
                Grievance.subject,
                Grievance.district,
                Grievance.category,
                Grievance.status,
                Grievance.priority,
                Grievance.created_at,
                Grievance.updated_at,
            ),
            raiseload("*"),
        )
        .order_by(*ordering)
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return list(rows), total


def status_counts(db: Session, citizen_id: UUID) -> dict[GrievanceStatus, int]:
    return dict(
        db.execute(
            select(Grievance.status, func.count())
            .where(Grievance.citizen_id == citizen_id)
            .group_by(Grievance.status)
        ).all()
    )


def public_updates(db: Session, grievance_id: UUID) -> list[PublicUpdate]:
    rows = db.execute(
        select(GrievanceUpdate.message, GrievanceUpdate.created_at, User.role)
        .join(User, User.id == GrievanceUpdate.author_id)
        .where(
            GrievanceUpdate.grievance_id == grievance_id,
            GrievanceUpdate.visibility == UpdateVisibility.PUBLIC,
        )
        .order_by(GrievanceUpdate.created_at.asc(), GrievanceUpdate.id.asc())
    )
    return [
        PublicUpdate(
            message=row.message, created_at=row.created_at, actor_label=ACTOR_LABELS[row.role]
        )
        for row in rows
    ]
