# Supabase PostgreSQL integration

Recruitment prototype, not an official Government of Kerala service.
Supabase is used exclusively as managed PostgreSQL. There is no Supabase Auth, browser database
client, REST replacement, Edge Function or second ORM. One FastAPI modular monolith selects one
database at a time through the existing session factory.

## Configuration and switching

Keep backend/.env ignored. Never paste a connection URL, password or API key into chat, logs,
documentation, frontend variables or Git.

~~~dotenv
DATABASE_TARGET=local
DATABASE_URL=<existing local Psycopg URL, unchanged>
SUPABASE_DATABASE_URL=<private session-pooler PostgreSQL URL>
SUPABASE_SSLROOTCERT=../.local/certificates/supabase-root.crt
DB_POOL_SIZE=3
DB_MAX_OVERFLOW=2
DB_POOL_TIMEOUT_SECONDS=10
DB_POOL_RECYCLE_SECONDS=300
DB_CONNECT_TIMEOUT_SECONDS=5
~~~

Local is always the default. There is no automatic failover between databases. Selecting Supabase
requires its separate URL; missing/invalid hosted configuration never falls back to local.
Hosted URLs accept postgresql:// or postgresql+psycopg:// and normalize only the driver.
Passwords must be URL-encoded. SQLAlchemy receives a URL object, so decoded special characters
are preserved rather than passing a password-masked string as credentials.

Hosted connections require port 5432 (direct or session pooler). Port 6543 transaction pooling
is rejected for this application/migration workflow. Identity/session overrides in URL query
parameters are rejected. TLS modes weaker than verify-full are rejected.

To run the API against Supabase in a separate PowerShell terminal:

~~~powershell
Set-Location backend
$env:DATABASE_TARGET = 'supabase'
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
# After stopping it, restore the shell default:
Remove-Item Env:DATABASE_TARGET
~~~

Restart the process when switching; settings and the normal engine/session factory are cached.
Local DATABASE_URL is never overwritten. Separate environments have separate users, sessions and
grievances; this task does not synchronize/migrate local records into Supabase.

app/db/engine.py is shared by application sessions, Alembic and hosted tooling. App pools use
pre-ping, bounded size/overflow/wait, recycling and rollback-on-return. Alembic/tooling uses
NullPool. Psycopg automatic prepared statements are disabled for the hosted pooler. A connection
hook discovers the existing vector namespace and sets a quoted public/extension search path.
No hostname is hardcoded in the engine. The guarded tool recognizes Supabase endpoint patterns
but never embeds a real project endpoint.

## TLS and certificate verification

Hosted connections always use sslmode=verify-full with certificate and hostname verification.
The CA path is SUPABASE_SSLROOTCERT, a URL sslrootcert path, or the standard certifi trust bundle
when no custom CA is configured. A missing file fails closed. There is no require/disable fallback.
The initial public trust-bundle probe failed certificate validation; using the official Supabase
root CA resolved it without weakening verification.

Download the root certificate from the project's Database Settings using trusted HTTPS. The
workstation certificate was saved under ignored .local/certificates, and backend/.env received
only its CA-path setting. The local database URL and all existing local records were preserved.
The trusted certificate is public, not a private key; do not trust a certificate harvested from
an unverified database connection.

Observed client-to-session-pooler TLS was active and verified through libpq. PostgreSQL's
pg_stat_ssl reported ssl=false for the backend session. Through a pooler, that describes the
pooler-to-PostgreSQL leg, not this client's TLS connection. Do NOT report fully verified end-to-end
TLS. Review the provider-managed internal transport with Supabase or use a suitable verified
direct endpoint if policy requires TLS on every hop. No managed transport policy was changed.

Official references: [connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres),
[CA/verify-full setup](https://supabase.com/docs/guides/database/psql),
[SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement).

## Guarded inspection and provisioning

The dedicated tool always selects SUPABASE_DATABASE_URL explicitly, regardless of the local
default, and disables AI in its settings. Inspect is read-only:

~~~powershell
Set-Location backend
.venv\Scripts\python.exe -m scripts.supabase_db inspect
~~~

It verifies DNS, authenticated database/user, public application schema, Supabase managed-schema
markers and client TLS. Output contains a non-secret target fingerprint, never a URL/password.
Before provisioning, review that inventory and its exact fingerprint:

~~~powershell
.venv\Scripts\python.exe -m scripts.supabase_db provision --confirm-target <fingerprint>
~~~

This command refuses local/ambiguous targets, fingerprint mismatches, conflicting public types/
functions and existing partial/unknown application schemas. It acquires an application advisory
lock, runs Alembic 0001 through 0006, protects only application objects and seeds the existing seven
canonical departments in one transaction. A failure rolls back the transaction. An already
complete 0006 application can be reverified/reference-seeded idempotently; no accounts are reset.
Supabase managed objects are not dropped, moved, reset or replaced.

No metadata.create_all(), manual revision stamping or competing migration system is used.
Migrations 0001–0005 are unchanged. Known environments were checked before correcting undeployed
0006: local development was 0004, hosted application schema/revision absent. Its compatibility
correction discovers/reuses vector's real namespace; when absent it creates the extension in
extensions if that schema exists, otherwise public. It does not move an installed extension.
The Vector(768) table is actually created; no silent skip or JSON/array substitute exists.

Alembic drift checks compare application metadata tables only, excluding unrelated managed
objects. They still compare all model columns, FKs, indexes and constraints. Runtime namespace
discovery also supports an already-existing vector installation outside public.

## Reference data and independent Data API security

Provisioning uses seed_departments(), extracted from the existing seed workflow. It inserts
missing canonical departments, preserving existing rows. It does not require passwords or create
citizens/officers/administrators. Hosted demo-account seeding/password reset is refused.
The seed CLI also supports --reference-only; use the guarded hosted provision command for initial
setup rather than running the normal demonstration seed against hosted data.

FastAPI JWT authorization does NOT protect tables independently exposed through Supabase Data API.
Provisioning enables RLS on all 15 application tables plus alembic_version, creates no permissive
policies, and revokes application-table privileges from PUBLIC, anon, authenticated and service_role.
It also revokes API execution privileges on the two application trigger functions. Effective
table permissions are checked before commit. No managed roles, global default privileges or
auth/storage/extension objects are changed.

The backend currently connects as the project owner role, which bypasses RLS; existing FastAPI
ownership/role/assignment checks remain authoritative for backend requests. A separate
least-privilege runtime role is recommended before production; it was not provisioned here.
Future migrations/new tables require the same explicit protection review.

Dashboard tasks still require operator review: disable the unused Data API (preferred), or review
exposed schemas/grants and Security Advisor warnings; configure network restrictions and SSL
enforcement; store runtime/migration secrets separately. SQL checks cannot prove the dashboard's
Data API toggle is disabled. No Supabase client key belongs in the React frontend.
See [Supabase API security](https://supabase.com/docs/guides/api/securing-your-api).

## Verification and safe hosted testing

~~~powershell
.venv\Scripts\python.exe -m scripts.supabase_db verify
~~~

Verify is read-only. It checks actual revision/tables, Alembic drift, PK/FK/check/unique/index
metadata, controlled enums, workflow partial indexes, immutable audit/timestamp triggers,
JSONB and vector dimensions. Synthetic vector expressions verify 768 dimensions, cosine
distance and dimension rejection. The existing SQLAlchemy similarity repository executes.

A separate explicit synthetic persistence probe is available:

~~~powershell
.venv\Scripts\python.exe -m scripts.supabase_db rollback-probe --confirm-target <fingerprint>
~~~

It inserts fictional temporary users/grievances/assignment/report, AI JSONB/report provenance
and vector rows inside one explicitly rolled-back transaction. It does not edit any existing
record, review a real report or make an official decision. It verifies ORM roundtrips/repository
ordering and confirms synthetic users are absent afterward. It never calls Gemini.
Do not use this as a substitute for a full business workflow suite in a separate disposable
project. Never point the existing schema-mutating pytest fixtures at the hosted application DB.
The fixtures now reject non-loopback database hosts before connecting.

## Actual results — 18 November 2026

| Check | Observed result |
|---|---|
| Connection | Port-5432 session pooler; PostgreSQL 17.12; database/user postgres |
| Client TLS | verify-full; valid Supabase CA; libpq ssl_in_use=true |
| Backend pg_stat_ssl | ssl=false; separate provider-managed transport review remains |
| Previous hosted revision | None; no application tables |
| Final hosted revision | 0006; all six migrations executed |
| Application tables | 15, plus Alembic version bookkeeping |
| Metadata | 15 PKs, 30 FKs, 14 checks, 7 unique constraints, 34 indexes |
| Audit/timestamp triggers | All four expected triggers present |
| Vector | pgvector 0.8.2 reused in extensions; actual vector(768) column |
| Vector SQL | Identical distance 0; orthogonal distance 1; wrong dimensions rejected |
| ORM persistence probe | AI JSONB/report FK and vector inserts passed; transaction rolled back |
| Schema drift | None |
| Security | RLS on 16 tables; anon/authenticated/service_role effective table access false |
| Seeded persistent rows | Seven departments; all other application tables empty |
| FastAPI | Health, DB health and public departments all 200; seven departments |
| Local development | Revision 0004, original data hash/counts and DATABASE_URL unchanged |
| Local pytest | 381 passed, 3 local vector skips, 17 upstream deprecation warnings |
| Gemini requests/backfills | 0 / none |

The three local skips remain local pgvector tests, not hosted test passes. Hosted vector SQL and
the rollback probe were verified separately, never by running full pytest on application data.
Ruff, compilation and dependency checks passed. Frontend tests/build were not rerun.

Troubleshooting: missing URL/CA, weak TLS mode, malformed credentials and transaction-pooler ports
fail safely; obtain correct values privately. Certificate failure is not a reason to disable
verification. Partial existing schemas require review, not resets/stamping. Extension/permission
failures require checking actual schema ownership; never relocate/drop managed extensions.
No live Gemini request, embedding backfill, deployment or new business feature was performed.
