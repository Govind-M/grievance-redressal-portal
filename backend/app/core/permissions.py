"""Authorization foundations for future transactional grievance services."""

from uuid import UUID

from fastapi import HTTPException

from app.db.models import DepartmentAssignment, User
from app.modules.enums import UserRole


def is_active_department_officer(user: User) -> bool:
    return bool(
        user.is_active
        and user.role == UserRole.DEPARTMENT_OFFICER
        and user.department_id is not None
        and user.department is not None
        and user.department.is_active
        and user.department.id == user.department_id
    )


def officer_belongs_to_department(user: User, department_id: UUID) -> bool:
    return is_active_department_officer(user) and user.department_id == department_id


def is_designated_officer(user: User, assignment: DepartmentAssignment) -> bool:
    return (
        officer_belongs_to_department(user, assignment.department_id)
        and assignment.officer_id == user.id
    )


def may_view_assignment(user: User, assignment: DepartmentAssignment) -> bool:
    return bool(
        assignment.closed_at is None
        and assignment.department is not None
        and assignment.department.is_active
        and officer_belongs_to_department(user, assignment.department_id)
    )


def may_modify_assignment(user: User, assignment: DepartmentAssignment) -> bool:
    return may_view_assignment(user, assignment) and (
        assignment.officer_id is None or is_designated_officer(user, assignment)
    )


def require_assignment_permission(
    user: User, assignment: DepartmentAssignment, *, modify: bool = False
) -> None:
    allowed = (
        may_modify_assignment(user, assignment) if modify else may_view_assignment(user, assignment)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Assignment access denied.")
