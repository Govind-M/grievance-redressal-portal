import re
from datetime import datetime
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.modules.enums import UserRole


def normalize_email(value: str) -> str:
    try:
        # Reserved .test domains support fictional demo accounts; no DNS or mailbox verification.
        normalized = validate_email(
            value.strip(), check_deliverability=False, test_environment=True
        ).normalized.lower()
    except EmailNotValidError:
        raise ValueError("Provide a valid email address") from None
    if len(normalized) > 255:
        raise ValueError("Email is too long")
    return normalized


def validate_name(value: str) -> str:
    value = value.strip()
    if not 2 <= len(value) <= 150 or not value.isprintable() or not any(c.isalpha() for c in value):
        raise ValueError("Name must contain 2 to 150 printable characters and include a letter")
    return value


def validate_mobile(value: str) -> str:
    value = value.strip()
    if len(value) > 15 or not re.fullmatch(r"\+?[0-9]{8,15}", value):
        raise ValueError(
            "Mobile number must have 8 to 15 digits, at most 15 characters including +"
        )
    return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    email: str
    mobile_number: str | None
    role: UserRole
    department_id: UUID | None
    is_active: bool
    created_at: datetime


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=150)
    mobile_number: str | None = Field(default=None, max_length=15)

    @field_validator("name", "mobile_number")
    @classmethod
    def validate_profile(cls, value: str | None, info: ValidationInfo) -> str:
        if value is None:
            raise ValueError("Profile values cannot be null")
        return validate_name(value) if info.field_name == "name" else validate_mobile(value)
