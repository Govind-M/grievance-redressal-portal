from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.dependencies import require_cmo_admin
from app.db.models import User
from app.db.session import get_db
from app.modules.analytics import service as analytics
from app.modules.cmo import schemas as dto
from app.modules.cmo import service

router = APIRouter(prefix="/cmo", tags=["CMO administration"])
DB = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require_cmo_admin)]


@router.get("/dashboard/stats", response_model=dto.DashboardStats)
def dashboard(user: Admin, db: DB):
    return analytics.dashboard(db)


@router.get("/statistics/districts", response_model=list[dto.DistrictStats])
def districts(user: Admin, db: DB):
    return analytics.districts(db)


@router.get("/statistics/departments", response_model=list[dto.DepartmentStats])
def departments(user: Admin, db: DB):
    return analytics.departments(db)


@router.get("/grievances", response_model=dto.WorkPage)
def grievances(user: Admin, db: DB, filters: Annotated[dto.WorkQuery, Query()]):
    return service.list_grievances(db, filters)


@router.get("/grievances/{grievance_id}", response_model=dto.AdminDetail)
def detail(grievance_id: UUID, user: Admin, db: DB):
    return service.detail(db, grievance_id)


@router.patch("/grievances/{grievance_id}/review", response_model=dto.AdminDetail)
def review(grievance_id: UUID, data: dto.ReviewInput, user: Admin, db: DB):
    return service.mutate(db, user, grievance_id, "review", data)


@router.post("/grievances/{grievance_id}/assign", response_model=dto.AdminDetail)
def assign(grievance_id: UUID, data: dto.AssignmentInput, user: Admin, db: DB, request: Request):
    return service.mutate(
        db, user, grievance_id, "assign", data, request.app.state.settings.default_resolution_days
    )


@router.post("/grievances/{grievance_id}/reassign", response_model=dto.AdminDetail)
def reassign(grievance_id: UUID, data: dto.AssignmentInput, user: Admin, db: DB, request: Request):
    return service.mutate(
        db, user, grievance_id, "reassign", data, request.app.state.settings.default_resolution_days
    )


@router.post("/grievances/{grievance_id}/remarks", response_model=dto.AdminDetail, status_code=201)
def remarks(grievance_id: UUID, data: dto.UpdateInput, user: Admin, db: DB):
    return service.mutate(db, user, grievance_id, "remarks", data)


@router.patch("/grievances/{grievance_id}/priority", response_model=dto.AdminDetail)
def priority(grievance_id: UUID, data: dto.PriorityInput, user: Admin, db: DB):
    return service.mutate(db, user, grievance_id, "priority", data)


@router.post("/grievances/{grievance_id}/escalate", response_model=dto.AdminDetail, status_code=201)
def escalate(grievance_id: UUID, data: dto.EscalationInput, user: Admin, db: DB):
    return service.mutate(db, user, grievance_id, "escalate", data)


@router.post("/grievances/{grievance_id}/reopen", response_model=dto.AdminDetail)
def reopen(grievance_id: UUID, data: dto.ReasonInput, user: Admin, db: DB):
    return service.mutate(db, user, grievance_id, "reopen", data)


@router.post("/grievances/{grievance_id}/resume", response_model=dto.AdminDetail)
def resume(grievance_id: UUID, data: dto.ReviewInput, user: Admin, db: DB):
    return service.mutate(db, user, grievance_id, "resume", data)


@router.get("/reports", response_model=dto.ReportPage)
def reports(user: Admin, db: DB, filters: Annotated[dto.ReportQuery, Query()]):
    return service.list_reports(db, filters)


@router.post("/reports/{report_id}/review", response_model=dto.AdminDetail)
def review_report(report_id: UUID, data: dto.ReportReviewInput, user: Admin, db: DB):
    return service.review_report(db, user, report_id, data)
