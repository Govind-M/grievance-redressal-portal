from enum import StrEnum


class UserRole(StrEnum):
    CITIZEN = "CITIZEN"
    CMO_ADMIN = "CMO_ADMIN"
    DEPARTMENT_OFFICER = "DEPARTMENT_OFFICER"


class GrievanceStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class Priority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class UpdateVisibility(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
