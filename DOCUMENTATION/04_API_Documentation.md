# API documentation

Base URL: http://localhost:8000/api/v1. Implemented API version: 1.0.0.
OpenAPI: /docs, /redoc, /openapi.json. Health endpoints are unauthenticated.

| Method | Path | Result |
|---|---|---|
| GET | /api/v1/health | 200 process health |
| GET | /api/v1/health/db | 200 real PostgreSQL SELECT 1; 503 unavailable |

Process health:
```json
{"status":"healthy","service":"CM Kerala Grievance API","version":"1.0.0"}
```

Database health:
```json
{"status":"healthy","database":"connected"}
```

Unavailable response (503):
```json
{"detail":"Database unavailable"}
```

Unexpected errors return 500 with {"detail":"Internal server error"}; no exception internals.
CORS permits GET/POST/PATCH, Authorization/Content-Type/X-CSRF-Token and credentials from explicit
configured origins. Wildcard origins are rejected. Auth/profile/grievance responses use Cache-Control:
no-store. Validation responses omit raw inputs so passwords cannot be reflected in errors.

CMO/officer assignment, investigation, report review, escalation and analytics endpoints are now
implemented. See [Phase 4 contracts and complete request examples](10_Administrative_Workflow.md).
Feedback, contact and upload endpoints remain deferred. Explicit role-specific DTOs omit hashes,
tokens and object storage keys. CMO/officer responses also use Cache-Control: no-store.

## Advisory AI — Phase 5

POST /ai/analyze-grievance is citizen-only; POST /cmo/grievances/{id}/ai-analyze,
POST /cmo/grievances/{id}/detect-duplicates and POST /cmo/reports/{id}/ai-analyze are CMO-only.
All use existing active-session JWT validation and return is_advisory=true with no-store headers.
They never change official decisions. Live execution defaults off. See [AI contracts and
errors](05_AI_Integration.md). Duplicate retrieval requires pgvector/migration 0006;
classification/report analysis work at core migration 0005.

## Authentication and profiles — implemented

All paths below are relative to /api/v1. POST auth operations require an explicit trusted Origin;
missing/untrusted origins return 403. Protected operations require Authorization: Bearer.

| Method | Path | Success | Authentication / request |
|---|---|---|---|
| POST | /auth/register | 201 safe citizen profile | name, email, mobile_number, password JSON |
| POST | /auth/login | 200 access token, CSRF token, safe user; refresh cookie | email, password JSON |
| POST | /auth/refresh | 200 rotated access/refresh pair | refresh cookie + X-CSRF-Token |
| POST | /auth/logout | 204, clears cookie | valid access JWT + X-CSRF-Token |
| POST | /auth/logout-all | 204, clears cookie | valid access JWT + X-CSRF-Token |
| GET | /auth/me | 200 safe user | valid access JWT |
| PATCH | /users/me | 200 safe updated user | valid access JWT; name/mobile_number only |

Registration always creates CITIZEN. Extra role/department/account-status fields are rejected (422);
duplicate normalized email returns 409, including concurrent inserts. Passwords are 12–128
characters; names are 2–150 printable characters including a letter; mobiles have 8–15 digits,
optional leading +, and at most 15 total characters to fit the existing schema.
Email is normalized/validated without DNS/mailbox verification; reserved .test demo domains work.

Invalid credentials: 401 {"detail":"Invalid email or password."}.
Invalid/expired/revoked authentication: 401 {"detail":"Invalid or expired authentication."}
with WWW-Authenticate: Bearer. Insufficient role/assignment permission returns 403.
Repeated logout returns 401 because its token's session has already been revoked.
Missing JWT configuration disables login/protected APIs with 503 in development; health stays available.

Token response shape (refresh JWT is deliberately absent):
```json
{
  "access_token": "<access JWT>",
  "token_type": "bearer",
  "expires_in": 900,
  "csrf_token": "<session-bound CSRF proof>",
  "user": {
    "id": "<UUID>", "name": "Fictional Citizen", "email": "citizen@example.test",
    "mobile_number": null, "role": "CITIZEN", "department_id": null,
    "is_active": true, "created_at": "<UTC timestamp>"
  }
}
```

Exact requests, lifecycle and cookie configuration: [Authentication guide](08_Authentication.md).

## Citizen grievances and public departments — Phase 3

All paths are relative to /api/v1. Use Authorization: Bearer for grievance requests. No anonymous
reference tracking is provided. Cookie/CSRF authentication behavior from Phase 2 is unchanged;
grievance submission uses the explicit Bearer token, not cookie authentication.

| Method | Path | Access / result |
|---|---|---|
| POST | /grievances | CITIZEN, 201 grievance receipt with actual initial history |
| GET | /grievances/me | CITIZEN, 200 owned paginated list |
| GET | /grievances/me/statistics | CITIZEN, 200 database aggregate counts |
| GET | /grievances/track/{reference_number} | owner or CMO, 200 public-safe timeline |
| GET | /grievances/{grievance_id}/history | owner or CMO, 200 chronological history |
| GET | /grievances/{grievance_id} | owner or CMO, 200 public-safe details |
| GET | /departments | public, alphabetically sorted active departments |
| GET | /departments/{department_id} | public, active department details |

Submission requires only district/category/subject/description. See the controlled choices and
request/response examples in [Citizen Grievances](09_Citizen_Grievances.md).
Official state starts SUBMITTED/MEDIUM, with no current department or resolution timestamp.
The authenticated citizen owns the row; client-supplied official/ownership fields are rejected (422).

List query defaults: page=1, page_size=10 (1–100), sort_by=created_at, sort_order=desc.
page is bounded to 1–1,000,000. Optional status/category/district filters are applied in SQL.
sort_by accepts created_at/updated_at only; sort_order accepts asc/desc. UUID breaks ties.
Response is {items: [...], pagination: {page,page_size,total_items,total_pages}}.
An empty result has items=[] and total_pages=0; an out-of-range page remains 200 with empty items.

Tracking normalizes references to uppercase; lookups remain authenticated and ownership-scoped.
Details include description, official state, assigned department name and actual timestamps,
history and public updates. Tracking is a smaller response without the complaint description.
Private remarks, assignment instructions, user identifiers/contact details, AI suggestions and
storage keys are excluded. Internal history text is null; the official transition remains visible.
History is ordered by created_at then UUID, and uses role labels rather than personal actor details.

Missing/invalid/revoked/inactive authentication returns 401; wrong role returns 403.
Unknown or non-owned grievances return the identical 404 {"detail":"Grievance not found."}.
Malformed UUID/invalid payload/filter returns 422. Five exhausted reference collisions return
503 {"detail":"Unable to allocate a reference. Please retry."}. Database operational failures
return 503 {"detail":"Database unavailable"}. Other failures retain sanitized 500 handling.

Department list optionally accepts q (literal case-insensitive name search, max 150 characters).
It returns id/name/description only. Detail additionally returns is_active=true.
Inactive/nonexistent departments return 404; malformed department UUID returns 422.
All records come from PostgreSQL, not hardcoded response data.

