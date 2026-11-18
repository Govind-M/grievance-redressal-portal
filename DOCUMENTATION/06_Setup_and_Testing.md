# Setup and testing

The root README contains complete PowerShell startup commands for Docker/PostgreSQL, Python,
Alembic, seed and Vite. This document records verification and operational details.

## Environment variables

| Location | Variable | Meaning |
|---|---|---|
| root .env | POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT | Compose initialization and localhost port |
| backend/.env | APP_NAME, APP_ENV, APP_DEBUG | Application metadata and log verbosity |
| backend/.env | DATABASE_URL | Required PostgreSQL Psycopg URL; defaults only suit development |
| backend/.env | CORS_ORIGINS | Comma-separated exact browser origins |
| backend/.env | SEED_CITIZEN_PASSWORD, SEED_CMO_PASSWORD, SEED_OFFICER_PASSWORD | Required by seed, at least 12 characters |
| backend/.env | JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ISSUER, JWT_AUDIENCE | Persistent HS256 authentication configuration |
| backend/.env | ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS | Defaults 15 minutes / 7 days |
| backend/.env | AUTH_COOKIE_NAME/SECURE/SAMESITE/PATH/DOMAIN | HttpOnly refresh cookie configuration |
| backend/.env | AUTH_TRUSTED_ORIGINS | Exact CSRF origin allowlist |
| backend/.env | GEMINI_API_KEY | Optional future setting |
| process environment | TEST_DATABASE_URL | EMPTY dedicated database ending in _test |
| frontend/.env | VITE_API_BASE_URL | Public API base, never a secret |

APP_DEBUG is used instead of DEBUG because the supplied workstation sets an unrelated DEBUG=release.
No setting enables internal exception pages. Process environment overrides backend/.env.
Frontend environment variables are build-time public values.

Root .env, backend/.env and frontend/.env serve different processes; copying one does not configure
the others. Align backend DB credentials/port with Compose. Never commit populated files or keys.

## Executed verification — 17 November 2026

Environment: Windows, Python 3.14.0, Node 24.11.0, PostgreSQL 18. Docker and global npm unavailable.
An official npm CLI was downloaded under ignored .local/tooling; standard Node/npm works for clones.
Full Python resolved versions are recorded in backend/requirements-lock.txt; frontend/package-lock.json
records npm versions. Maintained dependency ranges remain in requirements.txt/requirements-dev.txt.

A separate cluster under .local/pgdata listened only on 127.0.0.1:55432, with local test role
phase1_local and databases phase1_dev/phase1_test. This disposable validation cluster uses local
trust authentication and must not be exposed or reused for deployment. The existing Windows
PostgreSQL service was not modified. Demo passwords for the CLI seed were generated into process
environment only and not saved. Set your own seed values for future development.

| Check executed | Outcome |
|---|---|
| python -m pytest -q with TEST_DATABASE_URL | 22 passed against real PostgreSQL |
| python -m compileall -q app scripts tests | passed |
| python -m ruff check app scripts tests alembic | passed after formatting |
| python -m alembic upgrade head | passed |
| python -m alembic current | 0001 (head) |
| python -m alembic check | no new upgrade operations |
| PostgreSQL migration upgrade → base → head | passed, including native enum teardown/recreation |
| python -m scripts.seed twice | passed; seven departments, three users; original hashes preserved |
| npm test | 12 passed, including all nine routes, fallback, disclaimer and Axios |
| npm run build | passed (Vite production assets including Tailwind CSS) |
| npm run dev -- --strictPort | Vite started on 127.0.0.1:5173 |
| uvicorn app.main:app --host 127.0.0.1 --port 8000 | startup passed |
| live GET /api/v1/health and /health/db | 200 healthy, real DB connected |
| live CORS OPTIONS request | 200 with configured origin |
| Vite /cmo/dashboard and /src/index.css | 200; transformed Tailwind .p-4 present |
| npm audit | zero vulnerabilities after test dependency update |
| alembic upgrade head --sql | passed; offline SQL generated |
| python -m pip check | no broken requirements |

One upstream deprecation warning remains: Starlette's TestClient currently supports httpx but
recommends httpx2. It does not fail checks. No visual UI polish or complete browser end-to-end
workflow is claimed. Route rendering is verified with Testing Library; development entry/CSS
are checked over HTTP.

During Phase 1 Docker was unavailable. Compose is present in Phase 2 and configuration validation
was executed, but the container runtime was not exercised.
PostgreSQL behavior was tested directly; it was not inferred from SQLite. Production deployment,
Python 3.12 specifically and other operating systems have not been runtime-tested.

## Re-running tests

Unit tests run without PostgreSQL and explicitly skip integration tests. To include integration,
create an empty dedicated PostgreSQL DB ending in _test and export TEST_DATABASE_URL in the shell.
The fixture refuses databases containing tables. It verifies original data across 0001/0002 up/down,
then a complete up/down/up, and removes its own schema afterward. Original domain fixtures use
rollback isolation; auth fixtures commit real data so concurrent request connections can see it.
Do not run two integration suites concurrently
against the same test DB.

Tests cover initialization, health success/failure, model mapper resolution, eleven tables,
all FKs/enums, nullable officer and actual partial unique assignment constraint, idempotent secure
seed, role/department rules, reference uniqueness/format, history immutability, feedback ratings,
report review metadata, file-size check, advisory AI values and UTC/timestamp handling.

On this workstation the sandbox blocked some cache/bytecode/formatter operations; they passed
when run with approved normal process permissions. If only pytest cache permissions fail, run
python -m pytest -q -p no:cacheprovider. Do not suppress migration or constraint errors.

## Current workstation database lifecycle

While the isolated cluster is running, prefix backend commands with:
```powershell
$env:DATABASE_URL = 'postgresql+psycopg://phase1_local@127.0.0.1:55432/phase1_dev'
```

Start/stop it using PostgreSQL's installed tools (from repository root):
```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D "$PWD/.local/pgdata" -l "$PWD/.local/postgres.log" -o '-h 127.0.0.1 -p 55432' -w start
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D "$PWD/.local/pgdata" -m fast -w stop
```

Use the Compose setup for a reproducible password-protected development environment.
Stop Uvicorn/Vite with Ctrl+C. Stop Compose using docker compose stop (retains the named volume).

## Git on this workstation

The repository was initialized without a commit or staging files. Windows reports that .git belongs
to the sandbox account, so Git under the normal user may report dubious ownership. An attempted
ownership correction was denied by Windows. Verification used a per-command exception scoped
to this newly created repository; no global Git security settings were changed:

```powershell
git -c safe.directory=C:/Govind/grievance-redressal-portal status
```

The .env files, .local cluster/tooling, virtual environment, node_modules and dist all match
ignore rules. No populated credential files are included in repository changes.

## Phase 2 verification — 18 November 2026

The authentication suite and original tests run against the same isolated PostgreSQL 18 cluster
on port 55432, using only the explicitly selected empty phase1_test database for fixture-owned
schema/data. Independent connections and real commits verify concurrency behavior.

The development phase1_dev database was upgraded from 0001 to 0002, with every row of all eleven
existing domain tables compared before/after and found unchanged. There are now thirteen domain
tables. Migration 0001 retains SHA-256
C155074D81878030B0C7DCBC4BC64A6D44A11BAC625F68165EAA2CE5CC81E67F.
Alembic current reports 0002 (head); alembic check reports no new upgrade operations.
The additional dependencies are PyJWT 2.15.1 and email-validator 2.4.0 (dnspython 2.9.2).

Final full Phase 2 run: 132 tests passed in 47.80 seconds, including all original tests,
the mobile-boundary case, independent application-instance token/revocation behavior and
configuration-error secret redaction.
Tests cover all three seeded login roles, safe validation errors, DB role changes, individually
blacklisted access identifiers, environment cookie flags, CSRF/session binding and failed-rotation
rollback. PostgreSQL races verify exactly one refresh success and one 401, durable replay
revocation, and exactly one registration success with one duplicate conflict.

The upstream Starlette/httpx TestClient deprecation warning remains non-fatal.
No Python 3.12-specific run, external deployment, full browser authentication UI or Compose
container startup is claimed. The frontend source/UI was not modified in this phase.

Detailed setup, stable secret generation, demo-only password recovery, exact PowerShell requests,
cookie/CSRF policy and a Mermaid sequence diagram are in [Authentication](08_Authentication.md).

| Final executed check | Outcome |
|---|---|
| python -m pytest -q with TEST_DATABASE_URL | 132 passed, one upstream deprecation warning |
| python -m ruff check --no-cache app scripts tests alembic | passed |
| python -m compileall -q app scripts tests alembic | passed |
| python -m pip check | no broken requirements |
| alembic upgrade head / current / check | 0002 (head), no new upgrade operations |
| Docker Compose config --quiet with example environment | passed; container runtime not started |
| npm test | 12 passed |
| npm run build | passed; same frontend asset output as Phase 1 |
| Live Uvicorn HTTP register/login/me/refresh/logout | 201 / 200 / 200 / 200 / 204 |
| Live reuse after logout (access and refresh) | both rejected with 401 |
| Final API health, DB health and OpenAPI paths on port 8000 | healthy; seven auth/profile paths present |

The HTTP walkthrough used a new disposable phase2_http_20261118_test database, which was removed
after its API process stopped. The development database was preserved. An ignored backend/.env
was created with the isolated database URL and a strong signing key generated once (not displayed),
so the current local API is ready after restarts. It is running on port 8000.
SEED_* passwords remain unconfigured; the existing fictional users' password hashes were not reset.
Choose local demo passwords and use the explicit development-only reset command when required.

## Phase 3 verification — 18 November 2026

New workflow/validation tests initially passed 103 cases against PostgreSQL 18. The full regression
run includes all original Phase 1/2 checks. Fixtures verify 0003 up/down and preservation of
preexisting history text with legacy remarks classified INTERNAL; the shared visibility enum
survives the downgrade to 0002.

Migration 0003 was applied to the isolated development database. Every value in every original
column of all thirteen domain tables was compared before/after and preserved.
No database records were reset. The only schema addition is grievance_history.remarks_visibility.
Alembic reports 0003 (head) and no new upgrade operations; pip check reports no broken dependencies.
There are no added dependencies, new tables or speculative indexes.

Coverage includes canonical districts/categories, length/privileged-field validation, atomic
submission/history rollback, successful savepoint collision recovery, five-attempt exhaustion,
owner/CMO/officer access, authenticated reference tracking, public-safe chronology and SQL privacy,
pagination/filter/sort totals, grouped statistics, active public departments, and constant query
counts as related updates grow. Future-state fixtures insert synthetic statuses/assignments in
tests only; they are not evidence of implemented CMO/officer workflow endpoints.

The previous foundation test's expectation that /grievances was absent was updated for the new
POST route: unrestricted GET remains unavailable (405), and /grievances/me requires authentication.
The frontend source/UI, AI model and earlier migration files remain unchanged.

See [Citizen Grievances](09_Citizen_Grievances.md) for exact API examples, controlled choices,
tracking authorization and the remaining Phase 4 work.

| Final executed Phase 3 check | Outcome |
|---|---|
| pytest test_grievances_postgres.py test_grievance_validation.py -q | 103 passed |
| python -m pytest -q with TEST_DATABASE_URL | 235 passed in 80.95 seconds |
| python -m ruff check --no-cache app scripts tests alembic | passed |
| python -m compileall -q app scripts tests alembic | passed |
| alembic current / check | 0003 (head); no new upgrade operations |
| python -m pip check | no broken requirements |
| Full original-column before/after comparison across 13 development tables | preserved |
| SHA-256 checks of 0001 and 0002 migration files | unchanged |
| Live HTTP citizen create | 201 with real initial SUBMITTED/MEDIUM history |
| Live HTTP list/detail/track/history/statistics | all 200 with stored data |
| Live HTTP public departments and department detail | 200; seven seeded rows |
| Live anonymous tracking / non-owner tracking / revoked tracking | 401 / 404 / 401 |
| Final API health/DB health/OpenAPI on port 8000 | healthy; all eight Phase 3 paths present |

The live walkthrough used a new disposable phase3_http_20261118_test database and an ephemeral
test-only signing configuration. Its process was stopped and the test database removed afterward.
The main API was then restarted on port 8000 with its existing persistent ignored local .env.
Development records and demo password hashes were preserved.

One existing upstream Starlette/httpx TestClient deprecation warning remains non-fatal.
The frontend source was unchanged; Phase 3 did not rerun its build/tests (the Phase 2 results above
remain historical). Docker container runtime, external hosting and Python 3.12 specifically were
not exercised. Real transaction/constraint behavior was verified on PostgreSQL 18, not SQLite.

