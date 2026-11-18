from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app.core.permissions import may_modify_assignment
from app.db.models import ActionTakenReport, Attachment, DepartmentAssignment, GrievanceUpdate
from app.modules.cmo import repository as repo
from app.modules.cmo import schemas as dto
from app.modules.cmo.service import summary, transactional
from app.modules.enums import GrievanceStatus
from app.modules.grievance_history.service import public_history
from app.modules.grievances import workflow


def detail(db, user, grievance_id):
    row = db.scalar(
        repo.department_scope(user).where(
            # SQL department scope also protects detail reads.
            DepartmentAssignment.grievance_id == grievance_id
        )
    )
    if row is None:
        raise HTTPException(404, "Grievance not found.")
    assignment = workflow.officer_assignment(db, row, user)
    reports = repo.officer_reports(db, row.id, user.department_id)
    report_ids = [x.id for x in reports]
    # Complaint attachments are relevant; report attachments only from this department.
    attachments = db.scalars(
        select(Attachment).where(
            Attachment.grievance_id == row.id,
            or_(Attachment.report_id.is_(None), Attachment.report_id.in_(report_ids)),
        )
    ).all()
    return dto.OfficerDetail(
        **summary(row).model_dump(),
        description=row.description,
        current_assignment=dto.AssignmentView.model_validate(assignment),
        can_modify=may_modify_assignment(user, assignment)
        and row.status == GrievanceStatus.IN_PROGRESS,
        history=public_history(db, row.id),
        updates=[
            dto.UpdateView.model_validate(x)
            for x in repo.officer_updates(db, row.id, user.department_id)
        ],
        reports=[dto.ReportView.model_validate(x) for x in reports],
        attachments=[dto.AttachmentMetadata.model_validate(x) for x in attachments],
    )


def reports(db, user, grievance_id):
    row = db.scalar(
        repo.department_scope(user).where(DepartmentAssignment.grievance_id == grievance_id)
    )
    if row is None:
        raise HTTPException(404, "Grievance not found.")
    workflow.officer_assignment(db, row, user)
    return [
        dto.ReportView.model_validate(x)
        for x in repo.officer_reports(db, row.id, user.department_id)
    ]


@transactional
def update(db, user, grievance_id, data):
    row = workflow.lock_grievance(db, grievance_id)
    assignment = workflow.officer_assignment(db, row, user, modify=True)
    entry = workflow.operational_update(db, row, user, data.message, data.visibility, assignment)
    db.flush()
    # Explicit eager loading keeps response serialization independent of lazy relationships.
    entry = db.scalar(
        select(GrievanceUpdate)
        .where(GrievanceUpdate.id == entry.id)
        .options(joinedload(GrievanceUpdate.author))
    )
    return dto.UpdateView.model_validate(entry)


@transactional
def submit_report(db, user, grievance_id, data):
    row = workflow.lock_grievance(db, grievance_id)
    report = workflow.submit_report(db, row, user, data.report_details)
    db.flush()
    report = db.scalar(repo.reports_query().where(ActionTakenReport.id == report.id))
    return dto.ReportView.model_validate(report)
