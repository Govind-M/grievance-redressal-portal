# Project overview

This is a recruitment demonstration prototype, not an official Government of Kerala service.

Project: CM Kerala Public Grievance Redressal Portal. Recruitment context: WhiteMatrix Software
Solutions, AI Full Stack Engineer. Supplied deadline: 18 November 2026, 11:00 PM IST.

The planned lifecycle is citizen submission → CMO review → department assignment → investigation
and action report → CMO resolution decision → citizen feedback and possible reopening.
Public informational pages, citizen portal, CMO administration and department officer portal share
one frontend/backend/database.

## Phase 1 implemented

FastAPI application factory, health checks, configuration, logging, request-scoped synchronous
sessions, eleven relational models, one reversible Alembic revision, fictional idempotent seed,
React/Vite/Tailwind environment, nine placeholder routes and unknown-route fallback.
All pages visibly identify the recruitment prototype. Tests and setup/architecture documents exist.

## Planned

Public pages and dashboard design; citizen feedback APIs; private file storage and downloads;
Gemini/LangChain/pgvector workflows.

## Phase 2 implemented

Citizen registration, login for all roles, strict HS256 access/refresh JWTs, HttpOnly refresh cookie,
CSRF protection, atomic refresh rotation and replay revocation, current/all-device logout,
current-user/profile APIs, role dependencies and department/officer authorization helpers.
Incremental migration 0002 adds user_sessions and revoked_tokens, preserving Phase 1 records.

## Phase 3 implemented

Authenticated citizen submission; unpredictable stable reference numbers with bounded collision
retry; atomic initial history; ownership-scoped listing with pagination/filters/sorting; secure
details/reference tracking; chronological public-safe history/updates; aggregate citizen statistics;
public active department listing/details. CMO generic reads remain public-safe.
Migration 0003 adds private-by-default history remark visibility without changing prior migrations.
AI, attachments and frontend interfaces remain planned.

No later-phase functionality is simulated. Frontend placeholders do not represent authenticated access.
See 06_Setup_and_Testing.md for executed checks and the unverified Compose runtime.

## Phase 4 implemented

CMO listing/detail/review, hybrid assignment/reassignment, independent priority changes,
public/internal remarks, report approval/return, resolution, reopening/resume and persistent
escalation. Department officers have SQL-scoped dashboards, lists, assigned-to-me, restricted
detail/report history, investigation updates and report submission. All official changes use the
central workflow service and immutable history; operational actions do not create fake transitions.
SQL dashboards, all-14-district and current-department aggregates include explicit unassigned totals.
Migration 0004 adds escalation audit, internal update provenance and pending-report uniqueness.
See [workflow and API examples](10_Administrative_Workflow.md).

