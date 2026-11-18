# Citizen grievances — Phase 3

Backend APIs only. No frontend design, assignment/investigation/report workflows, AI calls,
embeddings or file persistence were introduced. The recruitment prototype disclaimer still applies.

## Authentication and ownership

Use the existing Phase 2 login flow and send Authorization: Bearer <access JWT>.
Every grievance request checks the current active PostgreSQL user and session.
POST /grievances, GET /grievances/me and GET /grievances/me/statistics require CITIZEN.
CMO_ADMIN can read details, history and reference tracking for any grievance.
An owner can read only their own records; SQL includes citizen_id before selecting rows.
A non-owner receives the same 404 as an unknown grievance. Officers receive 403 through these
generic read routes, even if an assignment exists; officer APIs arrive in Phase 4.
Anonymous reference tracking is not available.

Unlike refresh/logout cookie operations, grievance submission authenticates exclusively through
an explicit Bearer header. Existing HttpOnly cookie, CSRF, rotation and revocation behavior is unchanged.
Authenticated grievance responses use Cache-Control: no-store.

## Submission contract

POST /api/v1/grievances — HTTP 201.

~~~json
{
  "district": "Ernakulam",
  "category": "Roads and Infrastructure",
  "subject": "Damaged road near the community hospital",
  "description": "The fictional road near the community hospital contains large potholes and needs inspection."
}
~~~

Exactly these four fields are accepted. No citizen_id, status, priority, reference_number,
current_department_id, due_at, resolved_at, history, AI decision or attachment data is accepted.
Unexpected fields return 422.

District and category input is matched case-insensitively with surrounding/repeated whitespace
normalized, then stored using its canonical value. Subject/description are trimmed first, validated
without silent truncation, and reject PostgreSQL-incompatible null characters.

| Field | Rule |
|---|---|
| district | one of the 14 controlled districts below |
| category | one of the 12 controlled categories below |
| subject | 5–255 characters after trimming |
| description | 20–10,000 characters after trimming |

Districts: Thiruvananthapuram, Kollam, Pathanamthitta, Alappuzha, Kottayam, Idukki, Ernakulam,
Thrissur, Palakkad, Malappuram, Kozhikode, Wayanad, Kannur, Kasaragod.

Categories: Roads and Infrastructure; Healthcare; Education; Water Supply; Sanitation and Waste
Management; Electricity; Transportation; Revenue and Land; Local Government Services; Public Safety;
Social Welfare; Other.

The shared [choices module](../backend/app/modules/grievances/choices.py) supplies the same values
to request validation and future structured AI schemas. Historical records are not rewritten.

The service assigns the authenticated citizen and initializes SUBMITTED/MEDIUM, no department,
no resolution timestamp and no deadline/assignment. MEDIUM is an application default, not AI output.
The existing generator creates CMK-<UTC year>-<16 uppercase random hex characters>.
The reference is stable and protected by PostgreSQL uniqueness.
Only reference constraint failures are retried, at most five times, using SAVEPOINTs.
Unrelated integrity errors are not retried.
This follows SQLAlchemy's documented [savepoint handling](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html).

The grievance and initial history event share one transaction. The event records from_status=null,
to_status=SUBMITTED, the authenticated citizen actor, PUBLIC submission remark and database UTC time.
If history insertion fails, creation rolls back. A response is returned only after commit succeeds.

## Details, tracking and timelines

- GET /api/v1/grievances/{grievance_id}
- GET /api/v1/grievances/track/{reference_number}
- GET /api/v1/grievances/{grievance_id}/history

Details contain id, reference_number, subject, description, district, category, status, priority,
assigned_department_name, created_at, updated_at, resolved_at, history and updates.
Tracking is a smaller response containing the reference, subject, status, assigned department,
submission/update times, history and public updates. References are normalized to uppercase.
The history endpoint returns only the chronological history list.

Every timeline is queried from actual grievance_history rows, ordered by created_at and UUID.
Each entry contains from_status, to_status, created_at, remarks and actor_label.
Actor labels are Citizen, Chief Minister's Office or Department Officer; no actor IDs, names,
emails or officer contact details are serialized.

Migration 0003 adds remarks_visibility with INTERNAL as the default for legacy and future
unclassified remarks. All official transitions appear, but private remarks are SQL-redacted to null.
The controlled initial submission remark is explicitly PUBLIC. The append-only trigger remains in
force, including visibility: old rows cannot be relabeled through ordinary updates.
Only updates with visibility=PUBLIC are selected. Private assignment notes, investigation text,
AI analyses and storage keys are absent.
The generic CMO read routes intentionally use the same safe schema; administrative projections
and additional workflows are Phase 4 work.

Illustrative initial history entry (timestamps come from the database):
~~~json
{
  "from_status": null,
  "to_status": "SUBMITTED",
  "created_at": "2026-11-18T09:00:00Z",
  "remarks": "Grievance submitted by citizen",
  "actor_label": "Citizen"
}
~~~

## Listing and statistics

GET /api/v1/grievances/me

| Parameter | Default / allowed values |
|---|---|
| page | 1; integer 1–1,000,000 |
| page_size | 10; integer 1–100 |
| status | optional SUBMITTED / UNDER_REVIEW / IN_PROGRESS / RESOLVED / REOPENED |
| category | optional controlled category, normalized as for submission |
| district | optional controlled district, normalized as for submission |
| sort_by | created_at or updated_at; default created_at |
| sort_order | asc or desc; default desc |

Unknown query parameters, invalid values and attempted ownership parameters return 422.
All filtering/counting/pagination occurs in PostgreSQL; no cross-citizen list is loaded then filtered.
Sort columns come from an allowlist, with UUID as a stable tie-breaker.
List rows contain id, reference_number, subject, district, category, status, priority,
created_at and updated_at, omitting descriptions and related/private data.

~~~json
{
  "items": [],
  "pagination": {"page": 1, "page_size": 10, "total_items": 0, "total_pages": 0}
}
~~~

A page beyond the available range returns 200 with empty items and accurate totals.
Stable ordering prevents ambiguous ties; separate requests are not a frozen snapshot if new data
arrives between pages.

GET /api/v1/grievances/me/statistics uses a single owner-scoped GROUP BY query.
It returns total, pending, resolved and all five by_status counts, including explicit zeros.
pending = SUBMITTED + UNDER_REVIEW + IN_PROGRESS + REOPENED, equivalently total - resolved.

## Public departments

GET /api/v1/departments returns real active rows alphabetically, with id/name/description.
Optional q performs a literal case-insensitive name search (SQL wildcard characters are escaped).
GET /api/v1/departments/{department_id} returns the same fields plus is_active=true.
Inactive or unknown UUIDs return 404. Malformed UUIDs return 422. Officer/account data is never
part of public department responses.

## PowerShell walkthrough

Apply migrations and start the configured backend from backend:
~~~powershell
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
~~~

The local backend requires the persistent JWT key configured in Phase 2. For seeded department
data, configure SEED_*_PASSWORD values and run python -m scripts.seed as documented in README.
Do not overwrite an existing .env or reset other application data.

In another terminal:
~~~powershell
$api = 'http://localhost:8000/api/v1'
$origin = @{ Origin = 'http://localhost:5173' }
$secure = Read-Host 'Choose a test password (12-128 characters)' -AsSecureString
$password = [System.Net.NetworkCredential]::new('', $secure).Password
$email = 'phase3-' + [guid]::NewGuid().ToString('N') + '@example.test'
$registration = @{
    name = 'Fictional Phase Three Citizen'; email = $email
    mobile_number = '+919876543210'; password = $password
} | ConvertTo-Json
Invoke-RestMethod "$api/auth/register" -Method Post -Headers $origin -ContentType application/json -Body $registration

$credentials = @{ email = $email; password = $password } | ConvertTo-Json
$browser = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$auth = Invoke-RestMethod "$api/auth/login" -Method Post -Headers $origin -ContentType application/json -Body $credentials -WebSession $browser
$headers = @{ Authorization = 'Bearer ' + $auth.access_token }

$payload = @{
    district = 'Ernakulam'; category = 'Roads and Infrastructure'
    subject = 'Damaged fictional road near hospital'
    description = 'The fictional road near the community hospital has large potholes and needs repair.'
} | ConvertTo-Json
$grievance = Invoke-RestMethod "$api/grievances" -Method Post -Headers $headers -ContentType application/json -Body $payload

# Own list with pagination and status filter:
Invoke-RestMethod "$api/grievances/me?page=1&page_size=10&status=SUBMITTED&sort_order=desc" -Headers $headers
Invoke-RestMethod "$api/grievances/$($grievance.id)" -Headers $headers
Invoke-RestMethod "$api/grievances/track/$($grievance.reference_number)" -Headers $headers
Invoke-RestMethod "$api/grievances/$($grievance.id)/history" -Headers $headers
Invoke-RestMethod "$api/grievances/me/statistics" -Headers $headers

# Public database-backed departments:
$departments = Invoke-RestMethod "$api/departments"
Invoke-RestMethod "$api/departments/$($departments[0].id)"
~~~

These requests create a fictional user/grievance in the selected development database. Anonymous
tracking returns 401; another citizen's token returns 404; officers are denied with 403.
A user cannot provide a new official status/priority or directly create/edit history.

## Tests, schema and later work

Run python -m pytest -q with TEST_DATABASE_URL selecting an EMPTY dedicated *_test database.
The migration fixture verifies 0003 up/down, preserved audit text and private legacy defaults;
the full suite covers earlier auth behavior as well as the new workflows.
See 06_Setup_and_Testing.md for actual results and environmental limits.

Thirteen domain tables remain. Migration 0003 reuses the existing visibility enum and adds no
speculative indexes. Existing metadata/indexes support these queries; query tests enforce SQL
pagination, aggregate counts and constant relationship query counts.

Phase 4 still needs CMO assignments, status transitions, officer investigation, action-taken reports
and review/resolution. Existing hybrid permission helpers are ready to reuse.
AI suggestions remain separate from official grievance values; no Gemini, LangChain or embeddings
are required. Attachments remain a preserved database model only. Upload inputs and attachment
metadata/download URLs will be introduced with an explicit private-storage access/visibility
contract; no fake uploads or misleading empty attachment response were added.

