from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.models import Department
from app.db.session import get_db
from app.modules.departments import service
from app.modules.departments.schemas import DepartmentDetail, DepartmentSummary

router = APIRouter(prefix="/departments", tags=["Departments"])
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[DepartmentSummary])
def departments(
    db: DB, q: Annotated[str | None, Query(min_length=1, max_length=150)] = None
) -> list[Department]:
    return service.list_active(db, q.strip() if q is not None else None)


@router.get("/{department_id}", response_model=DepartmentDetail)
def department(department_id: UUID, db: DB) -> Department:
    return service.get_active(db, department_id)
