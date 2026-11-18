"""Import every mapped class for Alembic and application metadata discovery."""

from app.modules.action_reports.models import ActionTakenReport
from app.modules.ai.embedding_models import GrievanceEmbedding
from app.modules.ai.models import AIAnalysis
from app.modules.assignments.models import DepartmentAssignment
from app.modules.attachments.models import Attachment
from app.modules.auth.models import RevokedToken, UserSession
from app.modules.contact.models import ContactEnquiry
from app.modules.departments.models import Department
from app.modules.escalations.models import GrievanceEscalation
from app.modules.feedback.models import CitizenFeedback
from app.modules.grievance_history.models import GrievanceHistory
from app.modules.grievance_updates.models import GrievanceUpdate
from app.modules.grievances.models import Grievance
from app.modules.users.models import User

__all__ = [
    "GrievanceEmbedding",
    "GrievanceEscalation",
    "ActionTakenReport",
    "AIAnalysis",
    "DepartmentAssignment",
    "Attachment",
    "ContactEnquiry",
    "Department",
    "CitizenFeedback",
    "GrievanceHistory",
    "GrievanceUpdate",
    "Grievance",
    "User",
    "UserSession",
    "RevokedToken",
]
