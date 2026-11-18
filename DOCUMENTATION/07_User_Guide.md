# Development user guide

This is a recruitment demonstration prototype, not an official Government of Kerala service.

Start PostgreSQL, migrate and optionally seed, then start FastAPI and Vite as described in README.
Open http://127.0.0.1:5173. Each page displays its title, "Module under development" and the
prototype disclaimer. No final navigation or design has been implemented; enter paths directly.

| Path | Placeholder |
|---|---|
| / | Home |
| /about | About Us |
| /how-it-works | How It Works |
| /departments | Departments |
| /contact | Contact Us |
| /faq | FAQ |
| /citizen/dashboard | Citizen Dashboard |
| /cmo/dashboard | CMO Dashboard |
| /officer/dashboard | Officer Dashboard |
| any other path | Page not found |

There are no login forms or route guards. Seeded users are fictional database fixtures, and
credentials have no frontend login workflow in Phase 3. Backend registration/login/profile and
session endpoints are functional; see [exact API examples](08_Authentication.md).
Citizens can submit, list and track grievances through the backend API. Use the
[citizen API walkthrough](09_Citizen_Grievances.md) after logging in.
CMO/officer assignment, investigation, report and resolution APIs are implemented; their UI remains
deferred. Use the [complete administrative walkthrough](10_Administrative_Workflow.md) with separate
citizen, CMO and officer bearer tokens.

To check backend readiness, visit /api/v1/health and /api/v1/health/db on port 8000.
The first tests the API process; the second tests the actual database. If DB health returns 503,
check PostgreSQL, backend DATABASE_URL and migrations without sharing your credentials.
Developer API documentation is at /docs.

Administrators begin review, choose an active department and optionally an officer, then inspect
investigation updates and accept/return reports. Only acceptance resolves a case. To reopen, provide
a reason, assign a fresh investigation, resume and obtain a new report. Officers see their active
department queue; specifically assigned cases are read-only for colleagues. Resolution closes the
assignment and removes it from the active officer queue. AI, uploads and final frontend remain later work.

