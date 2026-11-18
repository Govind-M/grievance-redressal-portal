from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.modules.enums import GrievanceStatus, Priority
from app.modules.grievance_history.schemas import ActorLabel, PublicHistoryEntry
from app.modules.grievances.choices import CategoryInput, DistrictInput


def trim_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Provide text")
    if "\x00" in value:
        raise ValueError("Text cannot contain null characters")
    return value.strip()


class GrievanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    district: DistrictInput
    category: CategoryInput
    subject: Annotated[str, BeforeValidator(trim_text), Field(min_length=5, max_length=255)]
    description: Annotated[str, BeforeValidator(trim_text), Field(min_length=20, max_length=10000)]


class GrievanceListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=10, ge=1, le=100)
    status: GrievanceStatus | None = None
    category: CategoryInput | None = None
    district: DistrictInput | None = None
    sort_by: Literal["created_at", "updated_at"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"


class GrievanceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    reference_number: str
    subject: str
    district: str
    category: str
    status: GrievanceStatus
    priority: Priority
    created_at: datetime
    updated_at: datetime


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class GrievancePage(BaseModel):
    items: list[GrievanceSummary]
    pagination: Pagination


class PublicUpdate(BaseModel):
    message: str
    created_at: datetime
    actor_label: ActorLabel


class GrievanceDetail(GrievanceSummary):
    description: str
    assigned_department_name: str | None
    resolved_at: datetime | None
    history: list[PublicHistoryEntry]
    updates: list[PublicUpdate]


class GrievanceTracking(BaseModel):
    reference_number: str
    subject: str
    status: GrievanceStatus
    assigned_department_name: str | None
    created_at: datetime
    updated_at: datetime
    history: list[PublicHistoryEntry]
    updates: list[PublicUpdate]


class GrievanceStatistics(BaseModel):
    total: int
    pending: int
    resolved: int
    by_status: dict[GrievanceStatus, int]
