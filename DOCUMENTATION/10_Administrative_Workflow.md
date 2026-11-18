# Administrative Workflow — CM Kerala Grievance Redressal Portal

> **Prototype disclaimer:** This document describes a WhiteMatrix Software Solutions AI Full Stack Engineer recruitment prototype. It is not an official Government of Kerala or Chief Minister's Office service.

---

## Table of Contents

1. [Roles and Permissions](#1-roles-and-permissions)
2. [Grievance Lifecycle Overview](#2-grievance-lifecycle-overview)
3. [Status Transition Rules](#3-status-transition-rules)
4. [CMO Dashboard and Analytics](#4-cmo-dashboard-and-analytics)
5. [CMO Grievance List and Detail](#5-cmo-grievance-list-and-detail)
6. [CMO Workflow Operations](#6-cmo-workflow-operations)
7. [Hybrid Department/Officer Assignment](#7-hybrid-departmentofficer-assignment)
8. [Department Officer Dashboard](#8-department-officer-dashboard)
9. [Officer Grievance List and Detail](#9-officer-grievance-list-and-detail)
10. [Investigation Updates](#10-investigation-updates)
11. [Action-Taken Reports](#11-action-taken-reports)
12. [CMO Report Review and Resolution](#12-cmo-report-review-and-resolution)
13. [Reopening and Investigation Cycles](#13-reopening-and-investigation-cycles)
14. [Escalation and Overdue Monitoring](#14-escalation-and-overdue-monitoring)
15. [Authorization and Data Privacy](#15-authorization-and-data-privacy)
16. [Error Reference](#16-error-reference)
17. [Appendix — Controlled Values](#17-appendix--controlled-values)

---

## 1. Roles and Permissions

The system enforces exactly three authenticated roles.

| Role | Description |
|---|---|
| `CITIZEN` | Submits grievances; views and tracks **own** records only. |
| `CMO_ADMIN` | Full administrative visibility and control over all grievances. The only role that may change official status. |
| `DEPARTMENT_OFFICER` | Reads grievances assigned to **their active department**. Modification rights depend on individual assignment. |

> **Important:** Public citizen registration always creates a `CITIZEN` account regardless of any additional fields supplied by the client. Admin and officer accounts are provisioned through controlled means only.

---

## 2. Grievance Lifecycle Overview

```
SUBMITTED ──► UNDER_REVIEW ──► IN_PROGRESS ──► RESOLVED
                                    ▲                │
                                    │                ▼
                                REOPENED ◄──────────┘
```

| Stage | Who acts | Trigger |
|---|---|---|
| Citizen submits | `CITIZEN` | `POST /api/v1/grievances` |
| CMO starts review | `CMO_ADMIN` | `PATCH /api/v1/cmo/grievances/{id}/review` |
| CMO assigns department (officer optional) | `CMO_ADMIN` | `POST /api/v1/cmo/grievances/{id}/assign` |
| Officer investigates, posts updates | `DEPARTMENT_OFFICER` | `POST /api/v1/officer/grievances/{id}/updates` |
| Officer submits action-taken report | `DEPARTMENT_OFFICER` | `POST /api/v1/officer/grievances/{id}/reports` |
| CMO accepts report → **RESOLVED** | `CMO_ADMIN` | `POST /api/v1/cmo/reports/{report_id}/review` with `"ACCEPTED"` |
| CMO returns report → officer re-investigates | `CMO_ADMIN` | `POST /api/v1/cmo/reports/{report_id}/review` with `"RETURNED"` |
| CMO reopens resolved case | `CMO_ADMIN` | `POST /api/v1/cmo/grievances/{id}/reopen` |
| CMO resumes reopened case | `CMO_ADMIN` | `POST /api/v1/cmo/grievances/{id}/resume` |

---

## 3. Status Transition Rules

Exactly **five** official statuses exist. Only `CMO_ADMIN` may execute official transitions.

```python
TRANSITIONS = {
    SUBMITTED:    {UNDER_REVIEW},
    UNDER_REVIEW: {IN_PROGRESS},
    IN_PROGRESS:  {RESOLVED},
    RESOLVED:     {REOPENED},
    REOPENED:     {IN_PROGRESS},
}
```

**Guards enforced by the workflow layer:**

- Transitioning to `IN_PROGRESS` requires a consistent active assignment (department matches `current_department_id`).
- Transitioning to `RESOLVED` requires an **accepted** action-taken report from the active assignment. Submitting a report does not automatically resolve the grievance.
- Every official status change inserts a `grievance_history` record in the **same transaction** as the state change. These records are immutable (enforced by a PL/pgSQL trigger).

**Operational states** (pending report, escalated, overdue) are derived values — they are **not** additional status values.

---

## 4. CMO Dashboard and Analytics

All endpoints require `CMO_ADMIN` role.

### `GET /api/v1/cmo/dashboard/stats`

Returns a statewide count snapshot.

**Response: `DashboardStats`**

```json
{
  "total": 142,
  "submitted": 12,
  "under_review": 8,
  "in_progress": 54,
  "resolved": 60,
  "reopened": 8,
  "pending": 82,
  "overdue": 11
}
```

- `pending` = total minus resolved.
- `overdue` = `IN_PROGRESS` or `REOPENED` grievances where `due_at < now()`.

---

### `GET /api/v1/cmo/statistics/districts`

Returns one `DistrictStats` entry per Kerala district (all 14, zero-filled if none).

**Response: `list[DistrictStats]`**

```json
[
  {
    "district": "Thiruvananthapuram",
    "total": 28,
    "pending": 16,
    "resolved": 12,
    "overdue": 3
  }
]
```

---

### `GET /api/v1/cmo/statistics/departments`

Returns one `DepartmentStats` entry per active department plus an `"Unassigned"` bucket (grievances with no `current_department_id`).

**Response: `list[DepartmentStats]`**

```json
[
  {
    "department_id": "uuid",
    "department_name": "Public Works",
    "total": 20,
    "pending": 14,
    "resolved": 6,
    "overdue": 2
  },
  {
    "department_id": null,
    "department_name": "Unassigned",
    "total": 5,
    "pending": 5,
    "resolved": 0,
    "overdue": 0
  }
]
```

---

## 5. CMO Grievance List and Detail

### `GET /api/v1/cmo/grievances`

Paginated list of all grievances. CMO sees every grievance regardless of department or status.

**Query parameters (`WorkQuery`):**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | int | 1 | Page number (1-based) |
| `page_size` | int | 10 | Items per page (1–100) |
| `status` | enum | — | Filter by `GrievanceStatus` |
| `priority` | enum | — | Filter by `Priority` |
| `department_id` | UUID | — | Filter by current department |
| `district` | string | — | Filter by district |
| `category` | string | — | Filter by category |
| `overdue_only` | bool | false | Only overdue grievances |
| `reference` | string | — | Search by reference number |
| `subject` | string | — | Search by subject |
| `created_from` | datetime | — | Filter by created date range start |
| `created_to` | datetime | — | Filter by created date range end |
| `sort_by` | string | `created_at` | Sort field |
| `sort_order` | `asc`/`desc` | `desc` | Sort direction |

**Response: `WorkPage`**

```json
{
  "items": [
    {
      "id": "uuid",
      "reference_number": "GR-2024-000001",
      "subject": "Pothole on NH-66",
      "status": "IN_PROGRESS",
      "priority": "HIGH",
      "district": "Ernakulam",
      "category": "Roads and Infrastructure",
      "current_department_id": "uuid",
      "due_at": "2024-12-01T00:00:00Z",
      "resolved_at": null,
      "overdue": false,
      "created_at": "2024-11-01T08:00:00Z",
      "updated_at": "2024-11-10T14:30:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 10,
    "total_items": 142,
    "total_pages": 15
  }
}
```

---

### `GET /api/v1/cmo/grievances/{grievance_id}`

Full administrative detail for one grievance.

**Response: `AdminDetail`** — extends `WorkSummary` with:

```json
{
  "description": "Full grievance description text",
  "citizen": {
    "id": "uuid",
    "name": "Citizen Name",
    "email": "citizen@example.com",
    "mobile_number": "+91-9876543210"
  },
  "current_department": { "id": "uuid", "name": "Public Works" },
  "current_assignment": {
    "id": "uuid",
    "department_id": "uuid",
    "officer_id": "uuid",
    "assigned_at": "2024-11-05T09:00:00Z",
    "closed_at": null,
    "assignment_note": "Assigned for site inspection",
    "assigned_by": "uuid",
    "department": { "id": "uuid", "name": "Public Works" },
    "officer": { "id": "uuid", "name": "Officer Name" }
  },
  "assignments": [ "...all past and present assignments..." ],
  "history": [ "...full status history including internal remarks..." ],
  "updates": [ "...all PUBLIC and INTERNAL updates..." ],
  "reports": [ "...all action-taken reports..." ],
  "escalations": [ "...all escalation records..." ],
  "attachments": [ "...attachment metadata..." ]
}
```

> **Privacy note:** CMO sees full history including `INTERNAL` remarks and all `GrievanceUpdate` records. Citizens see only `PUBLIC` entries via citizen APIs.

---

## 6. CMO Workflow Operations

All operations below require `CMO_ADMIN` role and lock the target grievance row (`SELECT FOR UPDATE`) for the duration of the transaction. All successful mutations return the updated `AdminDetail`.

---

### Start Review — `PATCH /api/v1/cmo/grievances/{id}/review`

Transitions `SUBMITTED → UNDER_REVIEW`.

**Request body:**
```json
{
  "remarks": "Initial review note (optional, 5–10000 chars)",
  "visibility": "INTERNAL"
}
```

- `visibility` accepts `PUBLIC` or `INTERNAL` (default `INTERNAL`).
- If `remarks` is provided, an `INTERNAL` or `PUBLIC` `GrievanceUpdate` is created.

---

### Assign Department — `POST /api/v1/cmo/grievances/{id}/assign`

Creates the first assignment and transitions `UNDER_REVIEW → IN_PROGRESS`. Only valid when no active assignment exists.

**Request body:**
```json
{
  "department_id": "uuid",
  "officer_id": "uuid or null",
  "assignment_note": "Assign to PW for road inspection (10–2000 chars)",
  "priority": "HIGH"
}
```

- `department_id` must refer to an **active** department.
- `officer_id` is optional. If provided, the officer must be **active**, have role `DEPARTMENT_OFFICER`, and belong to the specified department.
- `priority` is optional; updates the grievance priority if supplied.
- Sets `due_at` to `now() + default_resolution_days` if not already set.
- An operational update is recorded with the assignment note.

---

### Reassign — `POST /api/v1/cmo/grievances/{id}/reassign`

Changes the active assignment while the grievance is `IN_PROGRESS` or `REOPENED`. Valid only when an active assignment exists. Any pending action-taken report must be reviewed (accepted or returned) before reassignment.

Request body is identical to `/assign`.

The previous assignment's `closed_at` is set before the new record is inserted (maintains the partial unique index `uq_department_assignments_active_grievance`).

---

### Add CMO Remark — `POST /api/v1/cmo/grievances/{id}/remarks`

Adds an administrative update (does not change status).

```json
{
  "message": "Following up with department head (5–10000 chars)",
  "visibility": "INTERNAL"
}
```

---

### Change Priority — `PATCH /api/v1/cmo/grievances/{id}/priority`

```json
{
  "priority": "HIGH",
  "reason": "Citizen escalation received (10–2000 chars)"
}
```

Records an `INTERNAL` operational update: `"Priority MEDIUM -> HIGH: <reason>"`.

---

### Escalate — `POST /api/v1/cmo/grievances/{id}/escalate`

Records a `GrievanceEscalation` entry. Cannot be used on `RESOLVED` grievances (reopen first). Cannot decrease priority.

```json
{
  "reason": "No progress after two weeks (10–2000 chars)",
  "new_deadline": "2024-12-15T00:00:00Z",
  "priority": "HIGH"
}
```

- `new_deadline` must be in the future if provided.
- `priority` must be equal to or higher than current priority if provided.
- Both fields are optional; omitting them logs the escalation without changing deadline or priority.

---

### Reopen — `POST /api/v1/cmo/grievances/{id}/reopen`

Transitions `RESOLVED → REOPENED`. Clears `resolved_at` and `due_at`. Previous history and reports are preserved.

```json
{
  "reason": "Resolution unsatisfactory; re-investigate (10–2000 chars)"
}
```

---

### Resume — `POST /api/v1/cmo/grievances/{id}/resume`

Transitions `REOPENED → IN_PROGRESS`. Requires a valid active assignment (department active, assigned officer — if set — still active and in the same department).

```json
{
  "remarks": "Investigation resumed with new officer (optional)",
  "visibility": "INTERNAL"
}
```

---

### List Pending Reports — `GET /api/v1/cmo/reports`

Paginated list of action-taken reports across all grievances.

**Query parameters (`ReportQuery`):**

| Parameter | Type | Default |
|---|---|---|
| `page` | int | 1 |
| `page_size` | int | 10 |
| `review_status` | `PENDING`/`ACCEPTED`/`RETURNED` | — |
| `department_id` | UUID | — |
| `reference` | string | — |
| `sort_order` | `asc`/`desc` | `desc` |

---

### Review a Report — `POST /api/v1/cmo/reports/{report_id}/review`

**Accept or return** an action-taken report. The report must have `review_status = PENDING` and belong to the currently active assignment.

```json
{
  "decision": "ACCEPTED",
  "review_remarks": "Verified on-site. Issue resolved. (10–2000 chars)"
}
```

| Decision | Effect |
|---|---|
| `ACCEPTED` | Report marked `ACCEPTED`; grievance transitions `IN_PROGRESS → RESOLVED`; `resolved_at` and `assignment.closed_at` set. |
| `RETURNED` | Report marked `RETURNED`; grievance remains `IN_PROGRESS`; officer must submit a new report. |

---

## 7. Hybrid Department/Officer Assignment

The assignment model supports two modes:

| Mode | `officer_id` | Who may modify |
|---|---|---|
| **Department-wide** | `NULL` | Any **active** officer in the assigned department |
| **Individual** | Set to a specific officer UUID | Only **that** designated officer; others in the department have read-only access |

**Enforcement** (`app/core/permissions.py` → `may_modify_assignment`):
- If `assignment.officer_id IS NULL`: any active officer in the same department may modify.
- If `assignment.officer_id IS NOT NULL`: only that officer may modify.

The CMO retains full administrative visibility and control in all cases.

**Database constraint:** A PostgreSQL partial unique index (`uq_department_assignments_active_grievance`) ensures only one active assignment (`closed_at IS NULL`) per grievance at any time.

---

## 8. Department Officer Dashboard

All endpoints require `DEPARTMENT_OFFICER` role. All queries are automatically scoped to the **officer's current active department**.

### `GET /api/v1/officer/dashboard/stats`

Returns workload statistics for the officer's department.

**Response: `OfficerStats`**

```json
{
  "total": 30,
  "submitted": 0,
  "under_review": 0,
  "in_progress": 18,
  "resolved": 10,
  "reopened": 2,
  "pending": 20,
  "overdue": 4,
  "department_active": 30,
  "assigned_to_me": 6,
  "unassigned_to_officer": 12,
  "reports_pending_review": 2
}
```

- `department_active`: All grievances currently assigned to this department.
- `assigned_to_me`: Active grievances where `officer_id = current_officer`.
- `unassigned_to_officer`: Active grievances in this department with `officer_id IS NULL`.
- `reports_pending_review`: Reports with `PENDING` review status under this department's active assignment.

---

## 9. Officer Grievance List and Detail

### `GET /api/v1/officer/grievances`

Paginated list of grievances in the officer's department. Accepts `OfficerQuery` parameters (all `WorkQuery` fields plus):

| Parameter | Type | Description |
|---|---|---|
| `assigned_to_me` | bool | Only grievances assigned to this officer |
| `unassigned_to_officer` | bool | Only department grievances with no designated officer |

The two officer-specific filters are mutually exclusive (422 if both set).

### `GET /api/v1/officer/grievances/assigned-to-me`

Shortcut that sets `assigned_to_me = true`. The `unassigned_to_officer` filter is rejected on this route.

### `GET /api/v1/officer/grievances/{grievance_id}`

Detailed view for one grievance. Officer must have an active assignment in the same department.

**Response: `OfficerDetail`**

```json
{
  "id": "uuid",
  "reference_number": "GR-2024-000012",
  "subject": "Water supply disruption",
  "status": "IN_PROGRESS",
  "description": "Full description text",
  "current_assignment": {
    "id": "uuid",
    "department_id": "uuid",
    "officer_id": "uuid",
    "assigned_at": "2024-11-10T09:00:00Z",
    "closed_at": null,
    "department": { "id": "uuid", "name": "Water Authority" },
    "officer": { "id": "uuid", "name": "Officer Name" }
  },
  "can_modify": true,
  "history": [ "...public history entries only..." ],
  "updates": [ "...updates authored within this department..." ],
  "reports": [ "...reports from this department's assignments..." ],
  "attachments": [ "...complaint + this department's report attachments..." ]
}
```

- `can_modify` is `true` only when the officer has individual modify rights **and** status is `IN_PROGRESS`.
- History entries contain only `PUBLIC` remarks (internal CMO remarks are withheld).
- Updates are scoped to those whose `assignment_id` belongs to this department.
- Attachment metadata for report attachments is scoped to reports from this department's assignments only.

---

## 10. Investigation Updates

Officers post progress updates while a grievance is `IN_PROGRESS` and they have modify rights.

### `POST /api/v1/officer/grievances/{grievance_id}/updates`

```json
{
  "message": "Site inspection completed. Repair crew dispatched. (5–10000 chars)",
  "visibility": "PUBLIC"
}
```

- `visibility` accepts `PUBLIC` (visible to citizen) or `INTERNAL` (default; officer/CMO only).
- The officer must have modify rights on the active assignment (`may_modify_assignment`).
- Grievance must be `IN_PROGRESS`.
- Records a `GrievanceUpdate` linked to the active assignment (`assignment_id`).

**Response: `UpdateView`**
```json
{
  "id": "uuid",
  "message": "Site inspection completed. Repair crew dispatched.",
  "visibility": "PUBLIC",
  "created_at": "2024-11-12T11:00:00Z",
  "author": { "id": "uuid", "name": "Officer Name" }
}
```

---

## 11. Action-Taken Reports

An action-taken report is the officer's formal completion statement. CMO review of this report governs resolution.

### `POST /api/v1/officer/grievances/{grievance_id}/reports`

```json
{
  "report_details": "Detailed account of all actions taken... (20–20000 chars)"
}
```

**Rules:**
- Officer must have modify rights on the active assignment.
- Grievance must be `IN_PROGRESS`.
- Only **one `PENDING` report** per grievance is allowed at any time (enforced by PostgreSQL partial unique index `uq_action_taken_reports_pending_grievance`).
- Submitting a report does **not** resolve the grievance. CMO must accept it.

**Response: `ReportView`**
```json
{
  "id": "uuid",
  "grievance_id": "uuid",
  "assignment_id": "uuid",
  "report_details": "...",
  "review_status": "PENDING",
  "submitted_at": "2024-11-13T16:00:00Z",
  "reviewed_at": null,
  "review_remarks": null,
  "submitter": { "id": "uuid", "name": "Officer Name" },
  "reviewer": null
}
```

### `GET /api/v1/officer/grievances/{grievance_id}/reports`

Lists all reports for a grievance from the officer's department. Officer must belong to the active department.

---

## 12. CMO Report Review and Resolution

### `POST /api/v1/cmo/reports/{report_id}/review`

**Accept:**
```json
{
  "decision": "ACCEPTED",
  "review_remarks": "Actions verified independently. Issue resolved satisfactorily."
}
```
Effect:
1. Report `review_status` → `ACCEPTED`; `reviewed_at` and `reviewed_by` set.
2. Grievance transitions `IN_PROGRESS → RESOLVED` (atomic, same transaction).
3. `grievance.resolved_at` set.
4. Active `DepartmentAssignment.closed_at` set.
5. `GrievanceHistory` record inserted.
6. Operational update: `"Report ACCEPTED: <review_remarks>"`.

**Return:**
```json
{
  "decision": "RETURNED",
  "review_remarks": "On-site evidence missing. Provide photographic documentation."
}
```
Effect:
1. Report `review_status` → `RETURNED`.
2. Grievance remains `IN_PROGRESS`.
3. Officer must submit a fresh report (previous `PENDING` constraint is lifted).

---

## 13. Reopening and Investigation Cycles

Reopening starts a new investigation cycle while fully preserving the audit trail.

**Reopen flow:**

1. `POST /cmo/grievances/{id}/reopen` — `RESOLVED → REOPENED`, clears `resolved_at` and `due_at`.
2. `POST /cmo/grievances/{id}/assign` or `POST /cmo/grievances/{id}/reassign` — create a new active assignment for the new cycle (the previous closed assignment is retained in history).
3. `POST /cmo/grievances/{id}/resume` — `REOPENED → IN_PROGRESS` once a valid assignment exists.
4. Officer investigates, posts updates, submits a fresh report.
5. CMO accepts the new report → `IN_PROGRESS → RESOLVED` again.

**Invariants preserved across cycles:**
- All `grievance_history` records from prior cycles are retained (append-only trigger).
- All prior `department_assignments` with `closed_at IS NOT NULL` are retained.
- All prior `action_taken_reports` (accepted and returned) are retained.
- `grievance.resolved_at = NULL` during reopened/in-progress; set again on the new resolution.

---

## 14. Escalation and Overdue Monitoring

### Escalation

`POST /api/v1/cmo/grievances/{id}/escalate` records a `GrievanceEscalation` entry. This is advisory and does not change the grievance's official status. The escalation log is visible in `AdminDetail.escalations`.

Each escalation records:
- `previous_due_at` / `new_due_at` — deadline before and after.
- `previous_priority` / `new_priority` — priority before and after.
- `reason` — mandatory free-text explanation.
- `escalated_by` — CMO user ID.
- `created_at` — immutable timestamp.

### Overdue Detection

A grievance is considered overdue when `due_at IS NOT NULL AND due_at < now() AND status != 'RESOLVED'`. This is computed at query time — there is no separate overdue flag stored. The CMO list endpoint supports `overdue_only=true` to filter this subset.

---

## 15. Authorization and Data Privacy

### Role enforcement

| Endpoint prefix | Required role | Enforcement |
|---|---|---|
| `/api/v1/cmo/*` | `CMO_ADMIN` | `require_cmo_admin` dependency; also re-verified in `service.require_cmo()` |
| `/api/v1/officer/*` | `DEPARTMENT_OFFICER` | `require_department_officer` dependency |
| `/api/v1/grievances/*` | `CITIZEN` (own records) | `get_current_citizen` dependency; SQL `WHERE citizen_id = user.id` |
| `/api/v1/departments/*` | None (public) | No authentication required |

Authorization uses the **currently validated database user and active session**. JWT claims alone are not sufficient — the session table is checked on every protected request.

### Data scoping

- **Officer queries**: All repository queries join through `department_assignments` and filter to the officer's `department_id`. Officers from unrelated departments receive `404`.
- **Citizen queries**: `WHERE citizen_id = :user_id` is applied at SQL level, not Python filtering.
- **Officer detail — history**: Only `PUBLIC`-visibility history remarks are exposed. Internal remarks have their `remarks` field set to `NULL` in the citizen/officer query. The `remarks_visibility` discriminator column (`migration 0003`) controls this.
- **Officer detail — updates**: Only updates whose `assignment_id` belongs to this department's past or present assignments are returned. CMO-only internal remarks are excluded.
- **Officer detail — attachments**: Report attachments are scoped to report IDs from this department's assignments.
- **Citizen APIs (Phase 3)**: CMO administrative detail schemas are never returned. Citizen schemas include only `PUBLIC` history entries and exclude internal CMO remarks, assignment notes, and officer contact details.

---

## 16. Error Reference

| HTTP Status | Scenario |
|---|---|
| `401 Unauthorized` | No valid access token; expired session. |
| `403 Forbidden` | Authenticated but insufficient role. |
| `404 Not Found` | Resource does not exist **or** the caller is not authorized to see it (privacy-safe 404). |
| `409 Conflict` | Invalid state transition; concurrent assignment conflict; pending report blocks reassignment; escalation would decrease priority. |
| `422 Unprocessable Entity` | Request validation failure (invalid department/officer, bad field values, mutually exclusive filters). |

**Concurrent conflict handling:** If two CMO sessions simultaneously attempt to assign the same grievance, the second will receive a `409` from the PostgreSQL partial unique index violation (`uq_department_assignments_active_grievance`), which is caught and translated to `WorkflowConflict` by the `@transactional` decorator. The client should reload and retry.

---

## 17. Appendix — Controlled Values

### Grievance Statuses

`SUBMITTED` · `UNDER_REVIEW` · `IN_PROGRESS` · `RESOLVED` · `REOPENED`

### Priority Values

`LOW` · `MEDIUM` · `HIGH`

### Report Review Statuses

`PENDING` · `ACCEPTED` · `RETURNED`

### Update Visibility

`PUBLIC` · `INTERNAL`

### Districts (14 Kerala districts)

| | | |
|---|---|---|
| Thiruvananthapuram | Kollam | Pathanamthitta |
| Alappuzha | Kottayam | Idukki |
| Ernakulam | Thrissur | Palakkad |
| Malappuram | Kozhikode | Wayanad |
| Kannur | Kasaragod | |

### Categories (12 controlled values)

| | |
|---|---|
| Roads and Infrastructure | Healthcare |
| Education | Water Supply |
| Sanitation and Waste Management | Electricity |
| Transportation | Revenue and Land |
| Local Government Services | Public Safety |
| Social Welfare | Other |

> **Note for Phase 5:** These controlled values are defined in `backend/app/modules/grievances/choices.py` and must be reused verbatim in Gemini AI prompt templates and structured output validation to ensure suggested departments and categories remain within the allowed set.

---

*Document version: Phase 4 final. Last updated during Phase 4 verification.*
