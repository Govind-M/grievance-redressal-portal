from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DepartmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str


class DepartmentDetail(DepartmentSummary):
    is_active: bool
