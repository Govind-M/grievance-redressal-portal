# Domain modules

Implemented models: users, departments, grievances, grievance_history, assignments,
grievance_updates, action_reports, attachments, feedback, contact and ai.
Import all mapped classes through app.db.models before using ORM relationships.

Auth now includes session/revocation models, schemas, transaction services and API routes.
Users includes safe response/profile schemas and a self-profile router. Core authentication and
permission dependencies support future workflows. Grievances now has controlled choices, strict
schemas, an ownership-scoped repository, transactional creation/read services and API routes.
History provides atomic audit insertion and public-safe projections. Departments exposes active
public list/detail APIs. CMO/officer routers, explicit DTOs, scoped repositories, transaction services,
central grievances/workflow.py and SQL analytics implement the administrative lifecycle.
escalations/models.py preserves immutable escalation events. Internal officer updates carry
assignment provenance. AI, feedback/contact endpoints and uploads remain deferred.

