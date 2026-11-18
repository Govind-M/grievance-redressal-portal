from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import require_department_officer
from app.db.models import User
from app.db.session import get_db
from app.modules.analytics import service as analytics
from app.modules.cmo import schemas as dto
from app.modules.cmo.service import list_grievances
from app.modules.officer import service

router = APIRouter(prefix="/officer", tags=["Department officer"])
DB = Annotated[Session, Depends(get_db)]
Officer = Annotated[User, Depends(require_department_officer)]


@router.get("/dashboard/stats", response_model=dto.OfficerStats)
def dashboard(user: Officer, db: DB):
    return analytics.dashboard(db, user)


@router.get("/grievances", response_model=dto.WorkPage)
def grievances(user: Officer, db: DB, filters: Annotated[dto.OfficerQuery, Query()]):
    return list_grievances(db, filters, user)


@router.get("/grievances/assigned-to-me", response_model=dto.WorkPage)
def assigned(user: Officer, db: DB, filters: Annotated[dto.OfficerQuery, Query()]):
    if filters.unassigned_to_officer:
        raise HTTPException(422, "assigned-to-me cannot filter unassigned work.")
    return list_grievances(db, filters.model_copy(update={"assigned_to_me": True}), user)


@router.get("/grievances/{grievance_id}", response_model=dto.OfficerDetail)
def detail(grievance_id: UUID, user: Officer, db: DB):
    return service.detail(db, user, grievance_id)


@router.post("/grievances/{grievance_id}/updates", response_model=dto.UpdateView, status_code=201)
def update(grievance_id: UUID, data: dto.UpdateInput, user: Officer, db: DB):
    return service.update(db, user, grievance_id, data)


@router.post("/grievances/{grievance_id}/reports", response_model=dto.ReportView, status_code=201)
def submit_report(grievance_id: UUID, data: dto.ReportInput, user: Officer, db: DB):
    return service.submit_report(db, user, grievance_id, data)


@router.get("/grievances/{grievance_id}/reports", response_model=list[dto.ReportView])
def reports(grievance_id: UUID, user: Officer, db: DB):
    return service.reports(db, user, grievance_id)
