from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.enums import GrievanceStatus

ActorLabel = Literal["Citizen", "Chief Minister's Office", "Department Officer"]


class PublicHistoryEntry(BaseModel):
    from_status: GrievanceStatus | None
    to_status: GrievanceStatus
    created_at: datetime
    remarks: str | None
    actor_label: ActorLabel
