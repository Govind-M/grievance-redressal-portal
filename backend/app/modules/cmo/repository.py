"""Bounded administrative and department queries. No statewide Python filtering."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, raiseload, selectinload

from app.db.models import (
    ActionTakenReport,
    Department,
    DepartmentAssignment,
    Grievance,
    GrievanceUpdate,
)
from app.modules.enums import GrievanceStatus, ReviewStatus, UpdateVisibility
from app.modules.grievances.workflow import now


def overdue():
    return (
        Grievance.due_at.is_not(None)
        & (Grievance.due_at < now())
        & (Grievance.status != GrievanceStatus.RESOLVED)
    )


def department_scope(user):
    return (
        select(Grievance)
        .join(DepartmentAssignment, DepartmentAssignment.grievance_id == Grievance.id)
        .join(Department, Department.id == DepartmentAssignment.department_id)
        .where(
            DepartmentAssignment.closed_at.is_(None),
            DepartmentAssignment.department_id == user.department_id,
            Grievance.current_department_id == user.department_id,
            Department.is_active.is_(True),
        )
    )


def filter_work(query, filters, user=None):
    for key in ("status", "priority", "district", "category", "current_department_id"):
        value = getattr(filters, "department_id" if key == "current_department_id" else key)
        if value is not None:
            query = query.where(getattr(Grievance, key) == value)
    if filters.overdue_only:
        query = query.where(overdue())
    for field, value in (("reference_number", filters.reference), ("subject", filters.subject)):
        if value:
            query = query.where(getattr(Grievance, field).icontains(value, autoescape=True))
    if filters.created_from:
        query = query.where(Grievance.created_at >= filters.created_from)
    if filters.created_to:
        query = query.where(Grievance.created_at <= filters.created_to)
    if user is not None:
        if filters.assigned_to_me:
            query = query.where(DepartmentAssignment.officer_id == user.id)
        if filters.unassigned_to_officer:
            query = query.where(DepartmentAssignment.officer_id.is_(None))
    return query


def list_work(db: Session, filters, user=None):
    query = filter_work(department_scope(user) if user else select(Grievance), filters, user)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort = {"created_at": Grievance.created_at, "updated_at": Grievance.updated_at}[filters.sort_by]
    order = (
        (sort.asc(), Grievance.id.asc())
        if filters.sort_order == "asc"
        else (sort.desc(), Grievance.id.desc())
    )
    rows = db.scalars(
        query.options(raiseload("*"))
        .order_by(*order)
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return rows, total


def admin_grievance(db: Session, grievance_id):
    return db.scalar(
        select(Grievance)
        .where(Grievance.id == grievance_id)
        .options(
            joinedload(Grievance.citizen),
            joinedload(Grievance.current_department),
            selectinload(Grievance.history),
            selectinload(Grievance.assignments).joinedload(DepartmentAssignment.department),
            selectinload(Grievance.assignments).joinedload(DepartmentAssignment.officer),
            selectinload(Grievance.updates).joinedload(GrievanceUpdate.author),
            selectinload(Grievance.reports).joinedload(ActionTakenReport.submitter),
            selectinload(Grievance.reports).joinedload(ActionTakenReport.reviewer),
            selectinload(Grievance.attachments),
            raiseload("*"),
        )
        .execution_options(populate_existing=True)
    )


def reports_query():
    return select(ActionTakenReport).options(
        joinedload(ActionTakenReport.submitter),
        joinedload(ActionTakenReport.reviewer),
        raiseload("*"),
    )


def officer_reports(db: Session, grievance_id, department_id):
    return db.scalars(
        reports_query()
        .join(DepartmentAssignment, DepartmentAssignment.id == ActionTakenReport.assignment_id)
        .where(
            ActionTakenReport.grievance_id == grievance_id,
            DepartmentAssignment.department_id == department_id,
        )
        .order_by(ActionTakenReport.submitted_at, ActionTakenReport.id)
    ).all()


def officer_updates(db: Session, grievance_id, department_id):
    return db.scalars(
        select(GrievanceUpdate)
        .outerjoin(DepartmentAssignment, DepartmentAssignment.id == GrievanceUpdate.assignment_id)
        .where(
            GrievanceUpdate.grievance_id == grievance_id,
            or_(
                GrievanceUpdate.visibility == UpdateVisibility.PUBLIC,
                DepartmentAssignment.department_id == department_id,
            ),
        )
        .options(joinedload(GrievanceUpdate.author), raiseload("*"))
        .order_by(GrievanceUpdate.created_at, GrievanceUpdate.id)
    ).all()


def list_reports(db: Session, filters):
    query = (
        reports_query()
        .join(DepartmentAssignment, DepartmentAssignment.id == ActionTakenReport.assignment_id)
        .join(Grievance, Grievance.id == ActionTakenReport.grievance_id)
    )
    if filters.review_status is not None:
        query = query.where(ActionTakenReport.review_status == filters.review_status)
    if filters.department_id is not None:
        query = query.where(DepartmentAssignment.department_id == filters.department_id)
    if filters.reference:
        query = query.where(
            Grievance.reference_number.icontains(filters.reference, autoescape=True)
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort = ActionTakenReport.submitted_at
    sort = sort.asc() if filters.sort_order == "asc" else sort.desc()
    rows = db.scalars(
        query.order_by(
            (ActionTakenReport.review_status == ReviewStatus.PENDING).desc(),
            sort,
            ActionTakenReport.id.desc(),
        )
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return rows, total
