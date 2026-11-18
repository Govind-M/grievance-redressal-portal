from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.modules.enums import GrievanceStatus, Priority, ReviewStatus, UpdateVisibility
from app.modules.grievance_history.schemas import PublicHistoryEntry
from app.modules.grievances.schemas import (
    GrievanceListQuery,
    GrievanceSummary,
    Pagination,
    trim_text,
)

Message = Annotated[str, BeforeValidator(trim_text), Field(min_length=5, max_length=10000)]
Reason = Annotated[str, BeforeValidator(trim_text), Field(min_length=10, max_length=2000)]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewInput(StrictInput):
    remarks: Message | None = None
    visibility: UpdateVisibility = UpdateVisibility.INTERNAL


class AssignmentInput(StrictInput):
    department_id: UUID
    officer_id: UUID | None = None
    assignment_note: Reason
    priority: Priority | None = None


class UpdateInput(StrictInput):
    message: Message
    visibility: UpdateVisibility = UpdateVisibility.INTERNAL


class PriorityInput(StrictInput):
    priority: Priority
    reason: Reason


class ReasonInput(StrictInput):
    reason: Reason


class EscalationInput(ReasonInput):
    new_deadline: AwareDatetime | None = None
    priority: Priority | None = None


class ReportInput(StrictInput):
    report_details: Annotated[
        str, BeforeValidator(trim_text), Field(min_length=20, max_length=20000)
    ]


class ReportReviewInput(StrictInput):
    decision: Literal["ACCEPTED", "RETURNED"]
    review_remarks: Reason


class WorkQuery(GrievanceListQuery):
    priority: Priority | None = None
    department_id: UUID | None = None
    overdue_only: bool = False
    reference: (
        Annotated[str, BeforeValidator(trim_text), Field(min_length=1, max_length=40)] | None
    ) = None
    subject: (
        Annotated[str, BeforeValidator(trim_text), Field(min_length=1, max_length=255)] | None
    ) = None
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_filters(self):
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from must not be after created_to")
        return self


class OfficerQuery(WorkQuery):
    assigned_to_me: bool = False
    unassigned_to_officer: bool = False

    @model_validator(mode="after")
    def valid_assignment_filters(self):
        if self.assigned_to_me and self.unassigned_to_officer:
            raise ValueError("Officer assignment filters are mutually exclusive")
        return self


class ReportQuery(StrictInput):
    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=10, ge=1, le=100)
    review_status: ReviewStatus | None = None
    department_id: UUID | None = None
    reference: (
        Annotated[str, BeforeValidator(trim_text), Field(min_length=1, max_length=40)] | None
    ) = None
    sort_order: Literal["asc", "desc"] = "desc"


class ORMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Person(ORMResponse):
    id: UUID
    name: str


class CitizenContact(Person):
    email: str
    mobile_number: str | None


class DepartmentInfo(ORMResponse):
    id: UUID
    name: str


class WorkSummary(GrievanceSummary):
    current_department_id: UUID | None
    due_at: datetime | None
    resolved_at: datetime | None
    overdue: bool


class WorkPage(BaseModel):
    items: list[WorkSummary]
    pagination: Pagination


class AssignmentView(ORMResponse):
    id: UUID
    department_id: UUID
    officer_id: UUID | None
    assigned_at: datetime
    closed_at: datetime | None
    department: DepartmentInfo
    officer: Person | None


class AdminAssignment(AssignmentView):
    assigned_by: UUID
    assignment_note: str | None


class AdminHistory(ORMResponse):
    id: UUID
    from_status: GrievanceStatus | None
    to_status: GrievanceStatus
    changed_by: UUID
    created_at: datetime
    remarks: str | None
    remarks_visibility: UpdateVisibility


class UpdateView(ORMResponse):
    id: UUID
    message: str
    visibility: UpdateVisibility
    created_at: datetime
    author: Person


class ReportView(ORMResponse):
    id: UUID
    grievance_id: UUID
    assignment_id: UUID
    report_details: str
    review_status: ReviewStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    review_remarks: str | None
    submitter: Person
    reviewer: Person | None


class ReportPage(BaseModel):
    items: list[ReportView]
    pagination: Pagination


class AttachmentMetadata(ORMResponse):
    id: UUID
    report_id: UUID | None
    original_filename: str
    content_type: str
    file_size: int
    created_at: datetime


class EscalationView(ORMResponse):
    id: UUID
    escalated_by: UUID
    reason: str
    previous_due_at: datetime | None
    new_due_at: datetime | None
    previous_priority: Priority
    new_priority: Priority
    created_at: datetime


class AdminDetail(WorkSummary):
    description: str
    citizen: CitizenContact
    current_department: DepartmentInfo | None
    current_assignment: AdminAssignment | None
    history: list[AdminHistory]
    updates: list[UpdateView]
    assignments: list[AdminAssignment]
    reports: list[ReportView]
    attachments: list[AttachmentMetadata]
    escalations: list[EscalationView]


class OfficerDetail(WorkSummary):
    description: str
    current_assignment: AssignmentView
    can_modify: bool
    history: list[PublicHistoryEntry]
    updates: list[UpdateView]
    reports: list[ReportView]
    attachments: list[AttachmentMetadata]


class DashboardStats(BaseModel):
    total: int
    submitted: int
    under_review: int
    in_progress: int
    resolved: int
    reopened: int
    pending: int
    overdue: int


class OfficerStats(DashboardStats):
    department_active: int
    assigned_to_me: int
    unassigned_to_officer: int
    reports_pending_review: int


class DistrictStats(BaseModel):
    district: str
    total: int
    pending: int
    resolved: int
    overdue: int


class DepartmentStats(BaseModel):
    department_id: UUID | None
    department_name: str
    total: int
    pending: int
    resolved: int
    overdue: int
