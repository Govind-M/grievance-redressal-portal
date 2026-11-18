# Development handoff — Phase 5

## Latest: Supabase integration

Supabase is an explicit second PostgreSQL environment selected with DATABASE_TARGET=supabase;
local remains the default and its URL/data/revision 0004 are unchanged. Hosted migrations reached
0006, all 15 application tables exist, vector 0.8.2 remains in extensions, and seven canonical
departments were seeded without accounts. No Gemini request/backfill ran.
See [configuration, commands, security and results](11_Supabase_PostgreSQL.md).

Shared engine construction is app/db/engine.py. Dedicated guarded tooling is scripts/supabase_db.py
(inspect/provision/verify/rollback-probe). 0006 was corrected before its first known application
deployment to resolve the existing extension namespace; 0001–0005 remain unchanged.
Hosted schema drift/read-only vector queries and explicitly rolled-back AI/vector persistence
checks passed. Local pytest: 381 passed, 3 local vector skips, 17 upstream warnings.
Ruff/compilation/dependency checks passed.

Strict client CA/hostname verification is enabled; pg_stat_ssl reports the separate managed
backend hop without TLS. Operator review of that hop, Data API dashboard settings, network
restrictions and a least-privilege runtime role remains. Backend currently connects as the owner;
FastAPI RBAC remains mandatory. The earlier Phase 5 local-only blocker narrative below is
historical, not the latest hosted capability state.

Recruitment prototype, not an official Government of Kerala service.
Repository: C:\Govind\grievance-redressal-portal. Branch observed: main.
Read AGENTS.md before changes; preserve preexisting uncommitted instructions and all user edits.
No implementation commits or staging were performed in Phase 5.

## Current implemented state

Phases 1–4 manual backend workflows remain intact: authentication/session revocation, citizen
ownership, CMO administration, hybrid assignments, officer investigation, report decisions,
resolution/reopening, history privacy, escalation and aggregate analytics.

Phase 5 adds four advisory POST endpoints:

- /api/v1/ai/analyze-grievance — CITIZEN, no draft/grievance persistence.
- /api/v1/cmo/grievances/{id}/ai-analyze — CMO classification, appends AIAnalysis.
- /api/v1/cmo/grievances/{id}/detect-duplicates — CMO compatible-vector retrieval and assessment.
- /api/v1/cmo/reports/{id}/ai-analyze — CMO report review assistance, no official decision.

Implementation is in modules/ai, integrations/gemini.py and integrations/embeddings.py.
Use existing core dependencies and SQLAlchemy session factory; no second persistence architecture.
No frontend, attachments, feedback/contact APIs, deployment or autonomous agents were added.

## Verification actually performed

Full mocked backend run: **357 passed, 3 skipped, 17 upstream deprecation warnings**, 143.82s.
The new AI subset passed 78 tests; earlier Phase 1–4 regression passed all 279 tests.
Ruff, compilation and pip check passed. Old migrations 0001–0004 match HEAD unchanged.
See [full command/results record](06_Setup_and_Testing.md).

Tests validate core migration 0005 up/down, retained legacy records, metadata consistency,
safe missing-vector failure, schemas, role denial, privacy, no official mutations, error handling,
fingerprints, vector SQL construction, duplicate validation, cache/throttling and live-call guards.
The three skipped tests require real pgvector SQL; do not report those features as runtime verified.
Re-run tests against a dedicated empty *_test database, never a populated/development database.
The fixture creates/downgrades its test schema and is not a read-only diagnostic.

## Database and blocker

Repository head: 0006. Development database observed read-only: **0004**; no migration applied here.
0005 adds nullable ai_analyses.report_id with FK/index; mandatory analysis/report support can run
at that revision. Optional 0006 enables vector and creates Vector(768) grievance_embeddings.
Current localhost:55432 PostgreSQL 18 has no server-side vector extension available.
Do not modify PostgreSQL installation files without appropriate operator authorization.

To enable core functionality after reviewing the migration:
~~~powershell
Set-Location backend
.venv\Scripts\python.exe -m alembic upgrade 0005
~~~

After installing server pgvector, upgrade head and run the full vector-capable suite/schema check.
No arrays/JSON fallback masquerades as vector storage. The extension is intentionally retained on
downgrade because other schemas may depend on it.

## Quota and credentials — non-negotiable

Live Gemini requests made: **0**. Live chat/embedding/model availability is NOT verified.
AI_ENABLED=false and AI_LIVE_REQUESTS_ENABLED=false by default. Do not read, print, log or commit
the key. A key in backend/.env is not authorization to use it. Pytest blocks real provider calls
even if flags/key are present, and blocks non-loopback sockets. All AI tests use mocks.

Before any real request, obtain explicit user approval. Initial live verification is limited to
ONE classification + ONE embedding, zero retries, through the separate scripts.ai_live_smoke
--approved-live-requests command. It uses synthetic data and prints sanitized attempt counts.
Only its --help and no-approval path were exercised. No live smoke test or embedding backfill ran.
Historical indexing needs separate approval; the bounded scripts.index_embeddings command is
never launched by startup, seed, migrations, submission or smoke testing.

Defaults are gemini-3.5-flash-lite and gemini-embedding-001 at 768 dimensions; public official docs
were checked, not live provider APIs. Package versions are in requirements-lock.txt.
See [AI documentation](05_AI_Integration.md) for all settings, limitations and request contracts.

## Remaining work / safe next steps

1. Review changes; run a fresh mocked baseline if the checkout changes.
2. Apply core 0005 when appropriate; keep development data intact.
3. Install/enable server pgvector with operator approval, migrate 0006 and verify the three real
   SQL tests. Account-specific model access and output quality need separate live verification.
4. Obtain the explicit two-request Gemini approval before live smoke testing.
5. Production hardening: distributed quotas/cache, PII sharing/redaction/retention policy, safe UI
   rendering, model-output evaluations, load tests and observability that never captures prompts.
6. Phase 6 can add separately authorized private storage, feedback and contact APIs using existing
   foundations. Optional AI availability must not become a prerequisite for manual workflows.

Some historical Phase 4 documentation discrepancies remain (profile GET alias, anonymous tracking
wording, active officer statistics examples). Preserve source compatibility; do not refactor
working routes to match historical prose.
