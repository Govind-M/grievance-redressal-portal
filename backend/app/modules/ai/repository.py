"""Bounded AI projections and persistence. No official grievance writes."""

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    ActionTakenReport,
    AIAnalysis,
    Department,
    Grievance,
    GrievanceUpdate,
    User,
)
from app.modules.ai.content import fingerprint, source_content
from app.modules.ai.embedding_models import GrievanceEmbedding
from app.modules.enums import UserRole


def active_departments(db: Session):
    return db.execute(
        select(Department.id, Department.name)
        .where(Department.is_active.is_(True))
        .order_by(Department.name, Department.id)
    ).all()


def grievance(db: Session, grievance_id):
    return db.get(Grievance, grievance_id)


def report(db: Session, report_id):
    return db.get(ActionTakenReport, report_id)


def investigation_context(db: Session, report: ActionTakenReport):
    # Only this report's assignment and officer-authored updates. No CMO/private contact data.
    rows = db.scalars(
        select(GrievanceUpdate.message)
        .join(User, User.id == GrievanceUpdate.author_id)
        .where(
            GrievanceUpdate.grievance_id == report.grievance_id,
            GrievanceUpdate.assignment_id == report.assignment_id,
            User.role == UserRole.DEPARTMENT_OFFICER,
            GrievanceUpdate.created_at <= report.submitted_at,
        )
        .order_by(GrievanceUpdate.created_at.desc(), GrievanceUpdate.id.desc())
        .limit(5)
    ).all()
    return [message[:2000] for message in reversed(rows)]


def save_analysis(db: Session, **values):
    row = AIAnalysis(**values)
    db.add(row)
    db.flush()
    return row


def vectors_ready(db: Session) -> bool:
    return bool(
        db.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"))
        and inspect(db.connection()).has_table("grievance_embeddings")
    )


def embedding(db: Session, grievance_id, model, dimensions):
    return db.scalar(
        select(GrievanceEmbedding).where(
            GrievanceEmbedding.grievance_id == grievance_id,
            GrievanceEmbedding.model_name == model,
            GrievanceEmbedding.dimensions == dimensions,
        )
    )


def similar(db: Session, row: Grievance, vector, settings):
    distance = GrievanceEmbedding.embedding.cosine_distance(vector)
    rows = db.execute(
        select(Grievance, distance.label("distance"), GrievanceEmbedding.source_fingerprint)
        .join(GrievanceEmbedding, GrievanceEmbedding.grievance_id == Grievance.id)
        .where(
            Grievance.id != row.id,
            Grievance.district == row.district,
            GrievanceEmbedding.model_name == settings.gemini_embedding_model,
            GrievanceEmbedding.dimensions == settings.ai_embedding_dimensions,
            distance <= 1 - settings.ai_duplicate_similarity_threshold,
        )
        .order_by(distance, Grievance.id)
        .limit(settings.ai_duplicate_candidate_limit)
    ).all()
    # SQL bounded/scored the shortlist; never assess stale vectors against changed content.
    return [
        (candidate, score)
        for candidate, score, digest in rows
        if fingerprint(source_content(candidate)) == digest
    ]
