# Project Agent Instructions — CM Kerala Grievance Redressal Portal

## 1. Purpose and authority

This repository is a **WhiteMatrix Software Solutions AI Full Stack Engineer recruitment prototype** for a fictional CM Kerala Public Grievance Redressal Portal. It is **not** an official Government of Kerala or Chief Minister's Office service. Use only fictional demonstration data and credentials; never imply government endorsement.

**Important:** These instructions document decisions agreed during project planning and implementation reports supplied by the developer. They are **not** proof that the repository currently implements every feature. Inspect source files, migrations, tests, Git state, and documentation before drawing conclusions or making changes. Existing verified repository behavior takes precedence over assumptions in this file; flag significant discrepancies rather than silently redesigning the application.

## 2. First actions for any coding agent

1. Open and inspect the **existing repository**; do not scaffold a new application or regenerate completed modules.
2. Read `README.md`, `DOCUMENTATION/`, existing architecture/code conventions, latest Alembic revision, and tests.
3. Check `git status`, active branch, and recent commits before editing. Never discard or reset uncommitted work without explicit approval.
4. For a handoff or verification task, **begin read-only**. Do not edit files, apply migrations, modify data, or install packages until authorized.
5. Make the smallest focused change consistent with established code patterns. Run relevant tests and report actual results; do not claim unexecuted tests passed.
6. Preserve prior migrations, stored records, API contracts, privacy rules, and functionality. Use new incremental Alembic revisions for justified schema changes.
7. Never commit `.env` files, API keys, JWT secrets, passwords, database credentials, personal grievance data, or other secrets.

## 3. Agreed technology architecture

- **Frontend:** One React application using Vite, JavaScript/JSX, Tailwind CSS, React Router and Axios. Public site, citizen, CMO and officer interfaces use separate route/layout groups. **Full UI design was deliberately deferred**; preserve the scaffold until explicitly asked to design it.
- **Backend:** One FastAPI **modular monolith**, Python 3.12+, Pydantic v2, domain-specific routers/services/repositories, REST API prefix `/api/v1`.
- **Database:** PostgreSQL, SQLAlchemy 2.x typed ORM (`Mapped`, `mapped_column`), Psycopg 3, Alembic migrations. Keep transaction handling centralized and consistent with existing synchronous/async implementation.
- **Authentication:** JWT access token (~15 minutes) and rotating refresh token (~7 days); Argon2id password hashing; PostgreSQL-backed sessions and revocation/blacklisting; refresh token in configurable secure HttpOnly cookie. Enforce server-side session validity on protected requests.
- **AI (planned):** Gemini API via LangChain prompt/model abstractions, Pydantic structured output; embeddings and optional `pgvector` semantic retrieval in PostgreSQL. No separate vector database is needed. Do not introduce LangGraph or autonomous agents without demonstrated need.
- **Files (planned):** Private cloud object storage, with file metadata in PostgreSQL; authorization required for retrieval.
- **Deployment:** Managed frontend, backend and PostgreSQL hosting. Test deployability; do not assume platform services support `pgvector` until verified.

Do not introduce microservices, Redis, Celery, Kubernetes, separate frontend applications, or competing ORM/database frameworks without a concrete requirement and user approval.

## 4. Roles and authorization

Exactly three authenticated roles:

- `CITIZEN`: Can register, log in, submit grievances, view/track **own** grievances, see public updates/history, and give feedback after resolution.
- `CMO_ADMIN`: Can view all grievances and private administrative details, confirm category/priority, review and assign cases, escalate, review reports, resolve/reopen, and access statewide analytics.
- `DEPARTMENT_OFFICER`: Can view **currently assigned department** grievances. Modification privileges are constrained by active assignments.

**Hybrid assignment policy:** A CMO assignment must select a department; an individual officer is optional. If `officer_id` is `NULL`, active officers in that department may investigate/modify. If `officer_id` is set, only that designated active officer may modify; other officers in that department have read-only access. Officers from unrelated departments cannot access the case. The CMO retains administrative visibility. Enforce these checks in backend services/queries, not merely frontend controls.

Public registration must **always** create a `CITIZEN`, regardless of extra fields provided by a client. Admin/officer accounts are provisioned through controlled means for the prototype. All authorization decisions should use the currently validated database user and active session; do not blindly trust JWT role claims.

## 5. Grievance workflow and audit invariants

Use **exactly five official grievance statuses**:

`SUBMITTED`, `UNDER_REVIEW`, `IN_PROGRESS`, `RESOLVED`, `REOPENED`.

Use **exactly three priority values**: `LOW`, `MEDIUM`, `HIGH`.

Expected baseline lifecycle:

1. Citizen submits → `SUBMITTED`, initial `MEDIUM` priority, no department; unique reference number and initial history record.
2. CMO starts review → `UNDER_REVIEW`.
3. CMO approves department assignment (officer optional) → `IN_PROGRESS`.
4. Authorized officer investigates, creates progress updates and submits an action-taken report. Submitting a report **does not** resolve the grievance.
5. CMO **accepts** the appropriate pending report → `RESOLVED`; or **returns** report for additional work, leaving case `IN_PROGRESS`.
6. CMO may reopen a resolved case → `REOPENED`; returning to `IN_PROGRESS` requires controlled re-investigation. A fresh report is required for a new resolution cycle.

Operational states (assignment, report pending/returned, escalation) are **not** extra grievance statuses. Report review statuses: `PENDING`, `ACCEPTED`, `RETURNED`.

**Non-negotiable invariants:**

- Every official status change must insert a `grievance_history` record with actor, timestamp, previous/new status in the same database transaction.
- Keep status history, previous assignments, past reports, and investigations; never overwrite or erase audit records on reassignment/reopening.
- Only **one active assignment per grievance**, enforced using the existing PostgreSQL partial unique index where `closed_at IS NULL`.
- Confirm selected officer belongs to the assigned active department and is active.
- Lock relevant rows and preserve atomicity for assignments, report decisions, status transitions, and conflicting concurrent actions.
- Do not permit multiple simultaneous pending action-taken reports for one grievance unless explicitly re-designed.
- Do not let officers resolve cases or AI assign departments/resolve cases autonomously.
- CMO controls final assignment, priority and resolution decisions.
- **Privacy:** `grievance_history.remarks_visibility` was added in migration `0003`. Status transitions may be public while internal remark text is redacted. `grievance_updates.visibility` distinguishes `PUBLIC` and `INTERNAL`. Citizen APIs must never leak internal CMO or officer notes, confidential assignment instructions, or another citizen's records. Officer views should not leak CMO-only administrative material.

When Phase 4 workflow code uses a more specific invariant, inspect its tests and documentation; report any conflict before changing it.

## 6. Data model and API expectations

Phase 1 planned eleven primary business tables: `users`, `departments`, `grievances`, `grievance_history`, `department_assignments`, `grievance_updates`, `action_taken_reports`, `attachments`, `citizen_feedback`, `contact_enquiries`, `ai_analyses`. Phase 2 also planned/implemented `user_sessions` and `revoked_tokens`. Phase 4 reportedly added persistent escalation tracking and officer-update assignment provenance. **Inspect actual migrations to establish the real schema and counts; do not enforce a hard-coded table count from this note.**

Grievances validate the 14 Kerala districts and 12 controlled categories stored in existing `grievances/choices.py` or equivalent. Reuse those canonical choices in future AI prompts and user input validation.

Existing Phase 3 APIs reported as implemented:

- `POST /api/v1/grievances`
- `GET /api/v1/grievances/me`
- `GET /api/v1/grievances/me/statistics`
- `GET /api/v1/grievances/{id}`
- `GET /api/v1/grievances/{id}/history`
- `GET /api/v1/grievances/track/{reference}`
- `GET /api/v1/departments`
- `GET /api/v1/departments/{id}`

Citizen records are ownership-filtered **in SQL**. Unauthenticated callers get `401`, wrong roles `403`, and unauthorized resource visibility generally `404`. CMO reads through generic Phase 3 endpoints are intentionally citizen-safe. Use distinct admin/officer detail schemas where necessary. Do not alter route conventions without checking existing integrations.

Phase 4's specification includes CMO dashboard/grievance CRUD-like workflow APIs, hybrid assignments/reassignments, CMO remarks, priority/escalation, officer department list/stats/details/updates/reports, CMO report review, reopen/resume, district- and department-wise statistics. **Discover exact existing endpoint names from routers/OpenAPI; do not assume all proposed endpoints were implemented.** Counts must be based on PostgreSQL records and correctly scoped; avoid counting historical reassignments twice.

## 7. AI design decisions (future phase)

AI is **advisory and human-reviewed**, never an official decision-maker.

**P0 mandatory — grievance analysis** usable by citizen at submission and CMO at review:
- Analyze description; suggest allowed department and category.
- Recommend `LOW`/`MEDIUM`/`HIGH` priority.
- Generate concise summary for CMO and brief grounded reasoning.
- Citizen can review suggestions, improve clarity if desired; original submitted content should not be silently rewritten.
- CMO confirms or overrides official values. Validate suggested department against active departments and category against controlled categories.

**P1 enhancements:**
- Potential duplicate detection: PostgreSQL full-text/location filtering and optional Gemini embeddings + `pgvector` to shortlist candidates, then Gemini assessment of candidates. Flag **possible** duplicates for CMO review; never automatically reject/merge grievances. Avoid sending every grievance to the LLM.
- CMO AI-assisted action-taken report review: compare original grievance, relevant updates, and officer report; summarize claimed actions, flag possibly unresolved aspects/missing evidence, propose follow-up questions. Do not claim physical facts have been independently verified.

**P2 if time permits:** Officer drafting assistance, investigation-history summaries, citizen-friendly resolution summary, complaint improvement, feedback summaries.

Use separate task-specific LangChain prompt + structured-response pipelines; maintain application/business authorization in FastAPI. Store AI results separately from official decisions, label model limitations and fallbacks. Do not make citizen submission dependent on external AI availability. Minimize personal data sent to model providers; guard against prompt injection from complaint text and reports.

## 8. Engineering and testing conventions

- Follow existing module layout (`models.py`, `schemas.py`, `router.py`, `service.py`, `repository.py` where established), Python type hints, Pydantic v2 validators and SQLAlchemy 2.x constructs.
- SQLAlchemy migrations, not `create_all()`, are authoritative for schema changes. Check enum lifecycle, foreign keys, indexes and existing migration chain.
- Use precise request and response schemas; reject over-posting privileged fields. Never return ORM objects with unfiltered private relationships.
- Database-side pagination, filters, sorting and aggregates; avoid N+1 queries.
- Maintain Argon2id password security, token type validation, refresh-token rotation/replay defense and session revocation. Never log tokens or passwords.
- Prefer pytest + PostgreSQL-backed integration tests for constraints, transaction behavior and concurrency; continue existing fixtures. Run Ruff, Python compilation, Alembic upgrade/check and tests as available. Identify unavailable infrastructure rather than assuming success.
- Document implemented vs planned features accurately. Preserve the mandatory `DOCUMENTATION/01_Project_Overview.md` through `07_User_Guide.md`, root README, `.env.example`, architecture and ER diagrams, and demo-account guidance. Existing additional docs are useful; do not remove them.
- Protect the prototype disclaimer, fictional test data, and third-party tool/service disclosures.

## 9. Current project handoff status — must be verified

**Reported implementation state:**
- Phase 1: FastAPI/PostgreSQL/Alembic foundation and minimal React scaffold.
- Phase 2: JWT access/refresh authentication, session revocation/blacklisting and RBAC.
- Phase 3: Citizen grievance CRUD-like submission/list/detail/tracking/history/stats and public department APIs; report stated **235 PostgreSQL-backed tests passed** before Phase 4.
- Phase 4: Codex implemented CMO/officer workflow and dashboard APIs. Reported **38 Phase 4 PostgreSQL-backed API tests passed**, including two-cycle lifecycle, hybrid permissions, privacy, reassignment, escalation, analytics. Independent-connection concurrency checks for assignment, report creation, and review reportedly passed (one success, one conflict). Then a full regression run found a fixed table-count assumption and fixture import issue; Codex reportedly fixed both and started rerunning, but final outcome was **not provided** because Codex usage limit was reached.

**Therefore Phase 4 is NOT yet independently confirmed complete.** The first task for the next agent is to inspect current code, reproduce test results, check route registration, inspect migration head/schema and completion of required docs, and fix only verified gaps. Do not launch Phase 5 until the user approves or Phase 4 verification is satisfactorily complete.

## 10. Agent handoff and completion reporting

For every significant task, summarize:

1. What code/files changed and why.
2. Implemented endpoints and database migrations (when applicable).
3. Business rules and privacy/authorization implications.
4. **Exact commands executed**, tests passed/failed/skipped, migrations and API checks actually performed.
5. Known blockers, unverified requirements, and next safe steps.

Never report work as complete solely from a prior agent's progress messages. Preserve stable structure, tests and data. If requirements are unclear, favor the agreed minimal secure implementation and explicitly identify assumptions.

## 11. Immediate instruction for a new agent

**First session: read-only repository audit and Phase 4 completion assessment.** Do not edit, migrate, reset Git, change credentials, or install dependencies until the developer authorizes changes. Review `git status` and existing implementation; report specific next verification steps. After authorization, complete remaining Phase 4 verification and only then proceed to Phase 5 AI integrations.
