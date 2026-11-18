from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import require_citizen, require_cmo_admin
from app.db.models import User
from app.db.session import get_db
from app.modules.ai import schemas, service
from app.modules.ai.runtime import AIRuntime, get_runtime

router = APIRouter(tags=["Advisory AI"])
DB = Annotated[Session, Depends(get_db)]
Runtime = Annotated[AIRuntime, Depends(get_runtime)]
Citizen = Annotated[User, Depends(require_citizen)]
Admin = Annotated[User, Depends(require_cmo_admin)]


@router.post("/ai/analyze-grievance", response_model=schemas.AnalysisResponse)
def analyze(data: schemas.AnalysisRequest, user: Citizen, db: DB, runtime: Runtime):
    return service.citizen_analysis(db, user, data, runtime)


@router.post("/cmo/grievances/{grievance_id}/ai-analyze", response_model=schemas.AnalysisResponse)
def reanalyze(grievance_id: UUID, user: Admin, db: DB, runtime: Runtime):
    return service.cmo_analysis(db, user, grievance_id, runtime)


@router.post(
    "/cmo/grievances/{grievance_id}/detect-duplicates", response_model=schemas.DuplicateResponse
)
def duplicates(grievance_id: UUID, user: Admin, db: DB, runtime: Runtime):
    return service.detect_duplicates(db, user, grievance_id, runtime)


@router.post("/cmo/reports/{report_id}/ai-analyze", response_model=schemas.ReportAnalysisResponse)
def review_report(report_id: UUID, user: Admin, db: DB, runtime: Runtime):
    return service.report_analysis(db, user, report_id, runtime)
