# CM Kerala Public Grievance Redressal Portal

This is a recruitment demonstration prototype, not an official Government of Kerala service.

Phases 1–4 foundation, authentication and complete backend grievance lifecycle for the WhiteMatrix Software Solutions
AI Full Stack Engineer machine test.
Citizens will submit grievances; the CMO will review and forward them; departments will investigate
and submit action-taken reports; the CMO will approve resolution and citizens will provide feedback.

## Implemented scope

One React application, one synchronous FastAPI backend, and one PostgreSQL application database.
Phase 1 includes eleven domain models, Alembic migrations, fictional seed data, health endpoints,
minimal route placeholders, tests, environment examples and seven architecture/setup documents.
Phase 2 adds citizen registration, unified login, access/refresh JWTs, PostgreSQL sessions,
atomic refresh rotation/replay detection, logout/logout-all, safe profiles, role dependencies and
hybrid assignment permission helpers. Phase 3 adds citizen grievance submission, owned listing,
secure details/tracking/history, aggregate statistics and public active-department APIs.
Phase 4 adds CMO administration, hybrid assignments, officer investigations, report review,
resolution/reopening, audited escalation and database-driven dashboard analytics.
There are fourteen domain tables and migrations 0001–0004; earlier migrations are unchanged.
AI, file uploads, citizen feedback APIs and frontend authentication/final UI remain deferred.
See the [Phase 4 API and end-to-end walkthrough](DOCUMENTATION/10_Administrative_Workflow.md).

## Stack and repository

- Python 3.12+, FastAPI, Pydantic v2/Settings, SQLAlchemy 2.x, Alembic, Psycopg 3.
- PostgreSQL 18; native UUID, ENUM, JSONB and timezone-aware timestamps.
- React 19, Vite 7, JavaScript/JSX, React Router 7, Axios, Tailwind 4.
- pytest for backend and real PostgreSQL integration; Vitest/Testing Library for frontend.
- Argon2id passwords, PyJWT HS256, HttpOnly refresh cookies and session-bound CSRF tokens.

```text
frontend/src/   app routing/providers, layouts, shared placeholders, services, tests
backend/app/   core settings/logging/security, db sessions/base/registry, domain modules
backend/alembic/versions/   0001 foundation, 0002 authentication, 0003 privacy, 0004 workflow
backend/scripts/seed.py    transactional idempotent fictional seed
backend/tests/            unit and PostgreSQL integration checks
DOCUMENTATION/            project, architecture, schema, API, AI, setup, user guide
docker-compose.yml        PostgreSQL only, persistent named volume
```

Auth models/schemas/services/routes live in backend/app/modules/auth. Reusable authentication
dependencies and assignment helpers live in core. CMO/officer routers coordinate centralized
workflow operations; SQL repositories and analytics provide scoped lists and aggregate counts.

## Local setup (PowerShell)

Prerequisites: Python 3.12+, Node >=22.12 with npm, and Docker Compose or an accessible PostgreSQL
server. Use two terminals for backend and frontend. Commands below start at the repository root.

### PostgreSQL

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env: choose a local database password.
docker compose up -d postgres
docker compose ps
```

Compose binds only to localhost. Its defaults are user `cm_user`, database `cm_kerala`, port 5432.
Set POSTGRES_PASSWORD in root .env and put the same password/port in backend DATABASE_URL.
URL-encode special characters in credentials. Changes to initialization credentials do not change
existing databases in the named volume.

### Backend, migrations and seed

```powershell
python -m venv backend/.venv
Set-Location backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit backend/.env: DATABASE_URL, a strong persistent JWT_SECRET_KEY, and three
# SEED_*_PASSWORD values (12 to 128 characters). See .env.example for key generation.
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m scripts.seed
.venv\Scripts\python.exe -m scripts.seed
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

On POSIX use `.venv/bin/python` instead. Install only requirements.txt for runtime; the optional
requirements-lock.txt records the exact full verification environment. Future schema changes need a
new Alembic revision. Startup never creates schema tables. Downgrade removes data: use only on a
disposable database or after a backup.

Fictional accounts: `citizen@example.test`, `cmo@example.test`, `officer@example.test`.
Seven fictional departments are seeded. The officer belongs to Public Works. Existing accounts,
password hashes and departments are preserved on reruns. All three roles can use the login API;
there is no frontend login interface. If the Phase 1 demo passwords are unknown, explicitly run
`python -m scripts.seed --reset-demo-passwords` with APP_ENV=development and configured passwords.
This resets only the three named fictional accounts and revokes their sessions, preserving all
other users/departments/grievances. Ordinary seeding never resets passwords.

### Frontend (second terminal, repository root)

```powershell
Set-Location frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Routes: /, /about, /how-it-works, /departments, /contact, /faq,
/citizen/dashboard, /cmo/dashboard, /officer/dashboard. Unknown paths render a fallback.
Every route displays the prototype disclaimer. Role routes are public development placeholders;
frontend authentication integration and route guards remain deferred. No final design has been selected.

The current workstation has Node without a global npm command. For this workspace only, the
downloaded npm CLI is available under the ignored .local folder. After entering frontend,
substitute `node ../.local/tooling/package/bin/npm-cli.js` for `npm`, for example:

```powershell
node ../.local/tooling/package/bin/npm-cli.js run dev
```

A fresh clone should use the normal Node/npm installation.

## Configuration and endpoints

Backend loads backend/.env independently of the working directory; process environment takes
precedence. DATABASE_URL uses `postgresql+psycopg://`. CORS_ORIGINS is a comma-separated list
(default http://localhost:5173 and http://127.0.0.1:5173). APP_ENV selects environment metadata.
APP_DEBUG controls application log verbosity; error responses always hide internals.
APP_DEBUG avoids collision with a host-level DEBUG variable. A persistent JWT_SECRET_KEY of at least
32 bytes is required for login/protected APIs; development health checks still work without it.
Production rejects missing/weak keys, insecure cookies and non-HTTPS browser origins. Gemini
configuration remains optional/unused. Frontend VITE_API_BASE_URL defaults to http://localhost:8000/api/v1.

Authentication endpoints: POST /auth/register, /auth/login, /auth/refresh, /auth/logout,
/auth/logout-all; GET /auth/me; PATCH /users/me (all under /api/v1).
POST auth requests need a trusted Origin. Refresh/logout/logout-all additionally need the
X-CSRF-Token returned at login. Access JWTs authenticate through Authorization: Bearer.
See [Authentication setup and exact requests](DOCUMENTATION/08_Authentication.md).

Citizen grievance APIs: POST /grievances; GET /grievances/me, /grievances/me/statistics,
/grievances/{id}, /grievances/{id}/history and /grievances/track/{reference}.
Citizen-specific operations use Bearer JWTs and current database session validation. Details,
tracking and history also allow CMO readers. Other citizens receive 404; officers receive 403.
Public department APIs: GET /departments and /departments/{id}.
See [Citizen grievance API walkthrough](DOCUMENTATION/09_Citizen_Grievances.md).

- GET http://127.0.0.1:8000/api/v1/health — process health, does not require the DB.
- GET http://127.0.0.1:8000/api/v1/health/db — real SELECT 1; HTTP 503 on failure.
- http://127.0.0.1:8000/docs — interactive OpenAPI; /redoc and /openapi.json also available.

## Checks

```powershell
Set-Location backend
.venv\Scripts\python.exe -m compileall -q app scripts tests
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check app scripts tests alembic
.venv\Scripts\python.exe -m alembic check
Set-Location ../frontend
npm test
npm run build
```

Without TEST_DATABASE_URL, PostgreSQL integration tests are explicitly skipped.
To run them, create an EMPTY dedicated database with a name ending in _test:

```powershell
# From repository root, after Compose is healthy:
docker compose exec postgres createdb -U cm_user cm_kerala_test
Set-Location backend
$env:TEST_DATABASE_URL = 'postgresql+psycopg://cm_user:YOUR_URL_ENCODED_PASSWORD@localhost:5432/cm_kerala_test'
.venv\Scripts\python.exe -m pytest -q
```

The fixture refuses existing tables, verifies incremental migration data preservation and up/down/up,
then removes its generated test schema. Auth tests use real commits and separate connections for
race tests; Phase 1 fixtures use rollback isolation. Do not use an application database.

## Verification and next phase

On 17 November 2026: 22 backend tests passed with real PostgreSQL 18, 12 frontend tests passed,
production build succeeded, compileall/lint passed, Alembic head/current/check succeeded, and live
FastAPI/Vite/Tailwind/CORS checks passed. The seed CLI ran twice successfully. npm audit reported
zero vulnerabilities. The full record and workstation details are in
[Setup and Testing](DOCUMENTATION/06_Setup_and_Testing.md).

Phase 2 verification on 18 November 2026: 132 backend tests passed against PostgreSQL, all 12
frontend regression tests passed, and the production build succeeded. A live HTTP walkthrough
verified registration, login, refresh, logout and revoked-token rejection. See the full results in
[Setup and Testing](DOCUMENTATION/06_Setup_and_Testing.md). Migration 0002 was applied to the
isolated development database with all eleven original tables' records verified unchanged.
The original migration's SHA-256 is unchanged. Compose configuration validation passed;
container runtime remains unverified. PostgreSQL integration tests use the isolated local cluster.

Phase 3 validates the 14 districts and 12 centralized categories, trims text without truncation,
and rejects privileged request fields. Submissions start SUBMITTED/MEDIUM without a department.
Grievance/history commit atomically; reference conflicts retry through savepoints up to five times.
Internal update text is SQL-filtered; internal history remarks are SQL-redacted while all official
status transitions remain visible. Existing migrations and records are preserved.

Phase 3 verification: 235 backend tests passed, including every Phase 1/2 regression and 103 new
validation/workflow cases. Ruff, compilation, Alembic current/check and pip check passed.
Live HTTP creation, listing, detail, tracking, history, statistics and department checks passed;
anonymous/revoked tracking returned 401 and another citizen's lookup returned 404.
See [Setup and Testing](DOCUMENTATION/06_Setup_and_Testing.md) for the execution record.

Phase 4 enforces CMO-only status decisions, active department/officer permissions, one active
assignment and one pending report, grievance-row locks and atomic audit writes. Resolution closes
the assignment. Reopening preserves accepted reports/history and requires a new assignment before
resume; an old report cannot resolve the new cycle. DEFAULT_RESOLUTION_DAYS=14 is a configurable
prototype assumption, not an official government SLA. Frontend design, AI and storage remain later work.

The current workstation has an ignored backend/.env configured for the isolated database and a
persistent generated signing key. The updated API is running on http://127.0.0.1:8000.
Demo password variables remain empty until you choose them; ordinary registration/login is ready.
Use the documented explicit demo reset if you need to recover the unknown Phase 1 demo passwords.

