from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only, raiseload

from app.db.models import Department


def list_active(db: Session, search: str | None = None) -> list[Department]:
    query = select(Department).where(Department.is_active.is_(True))
    if search is not None:
        query = query.where(Department.name.icontains(search, autoescape=True))
    return list(
        db.scalars(
            query.options(
                load_only(Department.id, Department.name, Department.description), raiseload("*")
            ).order_by(Department.name.asc(), Department.id.asc())
        )
    )


def get_active(db: Session, department_id: UUID) -> Department:
    department = db.scalar(
        select(Department)
        .where(Department.id == department_id, Department.is_active.is_(True))
        .options(raiseload("*"))
    )
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found.")
    return department
