from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.core.dependencies import require_citizen, require_roles
from app.db.models import User
from app.db.session import get_db
from app.modules.enums import UserRole
from app.modules.grievance_history.schemas import PublicHistoryEntry
from app.modules.grievances import service
from app.modules.grievances.schemas import (
    GrievanceCreate,
    GrievanceDetail,
    GrievanceListQuery,
    GrievancePage,
    GrievanceStatistics,
    GrievanceTracking,
)

router = APIRouter(prefix="/grievances", tags=["Grievances"])
DB = Annotated[Session, Depends(get_db)]
Citizen = Annotated[User, Depends(require_citizen)]
Reader = Annotated[User, Depends(require_roles(UserRole.CITIZEN, UserRole.CMO_ADMIN))]


@router.post("", response_model=GrievanceDetail, status_code=201)
def create_grievance(data: GrievanceCreate, user: Citizen, db: DB) -> GrievanceDetail:
    return service.create(db, user, data)


# Literal routes must precede UUID paths.
@router.get("/me", response_model=GrievancePage)
def list_grievances(
    user: Citizen, db: DB, filters: Annotated[GrievanceListQuery, Query()]
) -> GrievancePage:
    return service.list_mine(db, user, filters)


@router.get("/me/statistics", response_model=GrievanceStatistics)
def my_statistics(user: Citizen, db: DB) -> GrievanceStatistics:
    return service.statistics(db, user)


@router.get("/track/{reference_number}", response_model=GrievanceTracking)
def track_grievance(
    reference_number: Annotated[str, Path(min_length=1, max_length=40)], user: Reader, db: DB
) -> GrievanceTracking:
    return service.track(db, user, reference_number)


@router.get("/{grievance_id}/history", response_model=list[PublicHistoryEntry])
def status_history(grievance_id: UUID, user: Reader, db: DB) -> list[PublicHistoryEntry]:
    return service.history(db, user, grievance_id)


@router.get("/{grievance_id}", response_model=GrievanceDetail)
def grievance_detail(grievance_id: UUID, user: Reader, db: DB) -> GrievanceDetail:
    return service.detail(db, user, grievance_id)
