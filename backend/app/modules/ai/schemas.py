from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool

from app.modules.enums import Priority
from app.modules.grievances.choices import Category, DistrictInput
from app.modules.grievances.schemas import trim_text


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisRequest(StrictModel):
    district: DistrictInput
    subject: Annotated[str, BeforeValidator(trim_text), Field(min_length=5, max_length=255)]
    description: Annotated[str, BeforeValidator(trim_text), Field(min_length=20, max_length=10000)]


ShortText = Annotated[str, BeforeValidator(trim_text), Field(min_length=1, max_length=500)]
Reason = Annotated[str, BeforeValidator(trim_text), Field(min_length=1, max_length=1000)]
TextList = Annotated[list[ShortText], Field(max_length=10)]


class GrievanceAnalysisResult(StrictModel):
    suggested_department_id: UUID | None
    suggested_category: Category
    suggested_priority: Priority
    summary: Annotated[str, BeforeValidator(trim_text), Field(min_length=10, max_length=500)]
    department_reasoning: Reason
    priority_reasoning: Reason
    missing_information: TextList = Field(default_factory=list)


class DepartmentSuggestion(StrictModel):
    id: UUID
    name: str


class AnalysisResponse(GrievanceAnalysisResult):
    suggested_department: DepartmentSuggestion | None
    is_advisory: Literal[True] = True
    analysis_id: UUID | None = None
    model_name: str
    created_at: datetime | None = None


class DuplicateDecision(StrictModel):
    grievance_id: UUID
    potentially_duplicate: StrictBool
    reasoning: Reason


class DuplicateAssessmentResult(StrictModel):
    candidates: Annotated[list[DuplicateDecision], Field(max_length=10)]


class DuplicateCandidate(DuplicateDecision):
    reference_number: str
    similarity_score: float = Field(ge=-1, le=1, allow_inf_nan=False)


class DuplicateResponse(StrictModel):
    candidates: list[DuplicateCandidate]
    is_advisory: Literal[True] = True
    analysis_id: UUID
    model_name: str
    created_at: datetime


class ActionTakenAIReview(StrictModel):
    report_summary: Annotated[
        str, BeforeValidator(trim_text), Field(min_length=10, max_length=1000)
    ]
    reported_actions: TextList
    apparently_addressed_issues: TextList
    potentially_unresolved: TextList
    missing_evidence: TextList
    follow_up_questions: TextList


class ReportAnalysisResponse(ActionTakenAIReview):
    report_id: UUID
    is_advisory: Literal[True] = True
    analysis_id: UUID
    model_name: str
    created_at: datetime
