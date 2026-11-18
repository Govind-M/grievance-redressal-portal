"""SQL aggregates: current department attribution, active-only officer workload."""

from sqlalchemy import func, select

from app.db.models import ActionTakenReport, Department, DepartmentAssignment, Grievance
from app.modules.cmo import repository as repo
from app.modules.cmo import schemas as dto
from app.modules.enums import GrievanceStatus as Status
from app.modules.enums import ReviewStatus
from app.modules.grievances.choices import District


def metrics():
    return (
        func.count(Grievance.id).label("total"),
        func.count(Grievance.id).filter(Grievance.status != Status.RESOLVED).label("pending"),
        func.count(Grievance.id).filter(Grievance.status == Status.RESOLVED).label("resolved"),
        func.count(Grievance.id).filter(repo.overdue()).label("overdue"),
    )


def dashboard(db, user=None):
    scope = repo.department_scope(user) if user else select(Grievance)
    ids = scope.with_only_columns(Grievance.id)
    counts = dict(
        db.execute(
            select(Grievance.status, func.count())
            .where(Grievance.id.in_(ids))
            .group_by(Grievance.status)
        ).all()
    )
    total = sum(counts.values())
    overdue = (
        db.scalar(
            select(func.count()).select_from(Grievance).where(Grievance.id.in_(ids), repo.overdue())
        )
        or 0
    )
    values = {status.value.lower(): counts.get(status, 0) for status in Status}
    values.update(total=total, pending=total - counts.get(Status.RESOLVED, 0), overdue=overdue)
    if user is None:
        return dto.DashboardStats(**values)
    mine, unassigned = db.execute(
        select(
            func.count().filter(DepartmentAssignment.officer_id == user.id),
            func.count().filter(DepartmentAssignment.officer_id.is_(None)),
        ).where(
            DepartmentAssignment.grievance_id.in_(ids), DepartmentAssignment.closed_at.is_(None)
        )
    ).one()
    pending_reports = (
        db.scalar(
            select(func.count())
            .select_from(ActionTakenReport)
            .join(DepartmentAssignment, DepartmentAssignment.id == ActionTakenReport.assignment_id)
            .where(
                ActionTakenReport.grievance_id.in_(ids),
                DepartmentAssignment.closed_at.is_(None),
                ActionTakenReport.review_status == ReviewStatus.PENDING,
            )
        )
        or 0
    )
    return dto.OfficerStats(
        **values,
        department_active=total,
        assigned_to_me=mine,
        unassigned_to_officer=unassigned,
        reports_pending_review=pending_reports,
    )


def districts(db):
    rows = {
        row.district: row._mapping
        for row in db.execute(select(Grievance.district, *metrics()).group_by(Grievance.district))
    }
    return [
        dto.DistrictStats(
            **dict(
                rows.get(
                    district.value,
                    {
                        "district": district.value,
                        "total": 0,
                        "pending": 0,
                        "resolved": 0,
                        "overdue": 0,
                    },
                )
            )
        )
        for district in District
    ]


def departments(db):
    # Outer join includes inactive/zero-count departments. NULL is an explicit unassigned bucket.
    rows = db.execute(
        select(Department.id, Department.name, *metrics())
        .outerjoin(Grievance, Grievance.current_department_id == Department.id)
        .group_by(Department.id, Department.name)
        .order_by(Department.name)
    ).all()
    result = [
        dto.DepartmentStats(
            department_id=row.id,
            department_name=row.name,
            **{k: row._mapping[k] for k in ("total", "pending", "resolved", "overdue")},
        )
        for row in rows
    ]
    unassigned = db.execute(
        select(*metrics()).where(Grievance.current_department_id.is_(None))
    ).one()
    result.append(
        dto.DepartmentStats(
            department_id=None, department_name="Unassigned", **dict(unassigned._mapping)
        )
    )
    return result
