# Phase 5 — advisory AI integration

Recruitment prototype, not an official Government of Kerala service.
Four backend AI endpoints are implemented with mocked provider verification. Live Gemini requests
made during implementation: **0**. Real pgvector SQL is unverified on this host: PostgreSQL 18
does not advertise the server-side vector extension. AI defaults disabled.

## Architecture

~~~mermaid
flowchart LR
    API["Authenticated AI endpoints"] --> Service["Role/input/output validation"]
    Service --> Chains["LangChain prompts + Pydantic structured output"]
    Chains --> Gemini["Opt-in Gemini chat"]
    Service --> Embedding["Opt-in Gemini embedding"]
    Embedding --> Vectors[("Optional PostgreSQL pgvector")]
    Vectors --> Candidates["Bounded candidate shortlist"]
    Candidates --> Chains
    Service --> Results[("Existing ai_analyses: advisory results only")]
    Manual["Existing CMO/officer workflow"] --> Official[("Official decisions")]
~~~

app/integrations/gemini.py owns lazy provider clients, native structured output, bounded timeouts
and sanitized failures. app/modules/ai contains strict schemas, separated system/user prompts,
services, SQL projections, router, hash/result cache and throttle. integrations/embeddings.py
validates/normalizes vectors and coordinates idempotent storage.

LangChain core supplies ChatPromptTemplate and runnable pipelines; langchain-google-genai supplies
ChatGoogleGenerativeAI. No agent framework or umbrella LangChain package is needed. Embeddings use
the Google GenAI SDK with explicit task, dimensions, timeout and one total attempt.
No client/network request is created at startup. Provider tracing is explicitly disabled.

AI services never call official workflow mutators or change category, priority, status, department,
officer assignment, report review status or history. Only existing authorized endpoints decide.
All manual workflows and citizen submission remain independent of AI availability.

## API contracts and roles

All endpoints require an active JWT session and return is_advisory=true with Cache-Control: no-store.

| POST path, relative to /api/v1 | Role | Persistence |
|---|---|---|
| /ai/analyze-grievance | CITIZEN | No draft/grievance record created |
| /cmo/grievances/{id}/ai-analyze | CMO_ADMIN | Appends classification AIAnalysis |
| /cmo/grievances/{id}/detect-duplicates | CMO_ADMIN | Embedding cache and appended assessment |
| /cmo/reports/{id}/ai-analyze | CMO_ADMIN | Appends report-linked AIAnalysis |

Citizen input reuses district validation and trimmed subject 5–255/description 20–10000 characters.
Extra fields and null bytes are rejected. CMO endpoints read actual stored content, not replacement
request text. Missing resources return 404; wrong roles 403; invalid/revoked authentication 401.

~~~json
{
  "district": "Ernakulam",
  "subject": "Fictional road damage near a hospital",
  "description": "A fictional road near the community hospital has reported potholes requiring inspection."
}
~~~

Classification returns suggested_department_id (UUID or null), canonical department ID/name,
suggested_category from the existing 12 choices, priority LOW/MEDIUM/HIGH, summary (10–500),
department_reasoning/priority_reasoning (1–1000 each), missing_information (max 10 strings, each
1–500), model_name, optional saved analysis_id/created_at and is_advisory.
Null department means unknown/no match. Active departments with actual IDs are supplied to the
model and revalidated after generation. Invented IDs/categories/priorities/extra fields fail 502.

Report review returns report_summary, reported_actions, apparently_addressed_issues,
potentially_unresolved, missing_evidence and follow_up_questions. Lists have at most 10 bounded
items. The prompt describes claimed actions, never independently verified physical facts.
Context includes complaint/category/report plus at most five officer-authored updates from the
report's own assignment (2000 characters each), never CMO notes or profile/contact details.
There is no public/unrestricted AI history API.

## Model choices and official references

Defaults: gemini-3.5-flash-lite for chat; gemini-embedding-001 for 768-dimensional text embeddings
with SEMANTIC_SIMILARITY task. gemini-embedding-2 is also allowed, with separate model-compatible
vectors. Dimensionality is fixed at 768; changing it requires a schema change.
Chat uses with_structured_output(schema, method="json_schema"), then strict Pydantic validation.
Model identifiers were checked against public documentation, not live paid/model-list requests.
Account access, quota and actual output quality remain unverified.

Sources: [Google models](https://ai.google.dev/gemini-api/docs/models),
[Google embeddings](https://ai.google.dev/gemini-api/docs/embeddings),
[LangChain structured output](https://reference.langchain.com/python/langchain-google-genai/chat_models/ChatGoogleGenerativeAI/with_structured_output),
[pgvector SQLAlchemy](https://github.com/pgvector/pgvector-python#sqlalchemy).
Installed versions are recorded in backend/requirements-lock.txt.

## Settings and quota protection

| Setting | Default / constraint |
|---|---|
| GEMINI_API_KEY | Optional SecretStr; never displayed/logged |
| AI_ENABLED | false |
| AI_LIVE_REQUESTS_ENABLED | false; explicit approval required before enabling |
| GEMINI_CHAT_MODEL | gemini-3.5-flash-lite |
| GEMINI_EMBEDDING_MODEL | gemini-embedding-001 or gemini-embedding-2 |
| AI_EMBEDDING_DIMENSIONS | 768 |
| AI_REQUEST_TIMEOUT_SECONDS | 30, range 1–120 |
| AI_MAX_RETRIES | 0; at most 2 malformed-output retries, not transport retries |
| AI_MAX_OUTPUT_TOKENS | 2048, range 256–4096 |
| AI_MAX_INPUT_CHARACTERS | 50000 serialized-context characters |
| AI_DUPLICATE_CANDIDATE_LIMIT | 5, range 1–10 |
| AI_DUPLICATE_SIMILARITY_THRESHOLD | 0.75 cosine similarity, not probability |
| AI_REQUESTS_PER_MINUTE | 5 per authenticated user per worker |
| AI_CACHE_SECONDS | 60, range 0–300 |

Transport/embedding SDK retries are disabled: one attempt. Repeated classification/report requests
reuse user-scoped hash/result caches within the short TTL; no raw draft is retained. CMO analyses
still append records for traceability. Failures are never fabricated or cached as successful output.
Throttling is bounded worker-local memory, not durable distributed enforcement. Workers/restarts
can multiply/reset limits; concurrent identical first requests may each call Gemini. Configure
provider/project quotas before deployment. No Redis was introduced.

Pytest refuses real provider execution even with a configured key/live flags. An autouse socket
guard rejects non-loopback connections, and tracing is disabled. All chat/embedding test results
are mocks. Public documentation browsing and package downloads do not consume Gemini quota.

## Persistence, privacy and errors

Existing ai_analyses stores grievance/requester/model/type, canonical suggestions and validated
JSONB. Migration 0005 adds nullable indexed report_id with RESTRICT FK. Classification/report
JSON includes source fingerprint and prompt version. Duplicate results include retrieval scores,
embedding model/dimensions and provenance. No raw prompts or credentials are stored.
Pre-submission drafts are not persisted; cached draft results expire quickly.

Complaint/report content is untrusted JSON in a user message, separate from system instructions.
No execution tools, code, URLs or automatic official decisions are exposed. Profile data is not
loaded into prompts, but user-entered complaint text may itself contain personal data. Production
needs an explicit sharing/redaction/retention policy. Prompt boundaries are not proof of perfect
injection resistance; render output safely and retain human review.

503 covers disabled/missing configuration, provider failures/unsupported models and missing vector
capability; 429 quota/throttling; 504 timeouts; 502 invalid structured output. Errors suppress
provider exception text. Failed result persistence rolls back the AI transaction. A successfully
cached embedding can survive a later duplicate comparison failure; it is not an official decision.

## pgvector, embeddings and duplicates

0006 enables CREATE EXTENSION IF NOT EXISTS vector and creates grievance_embeddings:
UUID, grievance FK, model_name, dimensions, Vector(768), SHA-256 source fingerprint and UTC
created/updated timestamps. Unique grievance/model/dimension permits idempotent upserts.
No ANN index is needed at assessment scale. Downgrade retains the potentially shared extension.

Canonical versioned content contains subject, description, district/category, never profile data.
Vectors must be finite, nonzero, numeric and exactly 768-dimensional; they are normalized.
Unchanged fingerprints avoid repeat calls. Content is rechecked after generation; a race returns
409 rather than persisting mismatched content. The short content-check lock is released before
the duplicate-comparison chat request.

Retrieval uses cosine distance, compatible model/dimensions, same district, current-ID exclusion,
threshold and SQL LIMIT. Category need not match. Stale fingerprints are dropped from the bounded
shortlist, which may reduce result count. Candidate descriptions are 2000-character excerpts.
The model must assess exactly the supplied IDs: unknown/repeated/missing candidates are rejected.
The response combines server-owned IDs/references/scores with potential-duplicate flags/reasons.
No reasonable candidates means an empty result and no chat call. No automatic reject/merge/delete.

Historical grievances are not automatically indexed. A separately approved bounded indexing
script exists; startup, submission, migrations and seed never run a backfill.

## Safe migration paths and local blocker

The PostgreSQL 18 instance on localhost:55432 has no vector entry in pg_available_extensions.
The Python package does not install the server extension. No server files were changed.

Without pgvector, core classification/report analysis remains available:
~~~powershell
.venv\Scripts\python.exe -m alembic upgrade 0005
~~~

After the operator installs the compatible server extension and grants creation permission:
~~~powershell
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic check
~~~

0006 fails with actionable guidance when vector is absent, rather than replacing vectors with
JSON/arrays. Isolated tests validate 0005 here; capable hosts exercise full head and real vector
SQL tests. Never run destructive migration tests against development data. No development
migration was applied during this implementation.

## Separate live verification — approval required

A configured key is NOT permission to use it. First obtain explicit approval for exactly one
grievance-analysis request and one embedding request. Only after approval:
~~~powershell
Set-Location backend
.venv\Scripts\python.exe -m scripts.ai_live_smoke --approved-live-requests
~~~

The script requires the approval flag, uses synthetic data, forces zero retries and attempts at
most one request of each kind. It reports attempt counts and sanitized outcomes, never secrets
or full responses. It makes zero calls if credentials are unavailable, does not touch the database
and does not run duplicate detection/backfills. This command was NOT executed live.

Historical indexing requires separate approval beyond that smoke test. scripts.index_embeddings
requires --approved-live-requests, --admin-user-id (active CMO UUID), --limit (1–10, default 1)
and optional --after UUID. It requires live gates/pgvector, reuses unchanged vectors and does not
modify official grievance values. It was NOT executed.

See [setup/testing](06_Setup_and_Testing.md) and [handoff](Development_Handoff.md) for actual results.
Live Gemini and real pgvector SQL remain unverified. No frontend, file storage, feedback/contact
API or deployment work was added. Phase 6 can use the preserved manual backend independently.

