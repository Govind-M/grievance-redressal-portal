# AI integration — planned

No AI SDK, network calls, prompts, embedding computation, vector extension or similarity search
is implemented in Phase 1. GEMINI_API_KEY is optional and unused.

The planned stack is Gemini with LangChain orchestration and Pydantic structured output, Gemini
embeddings and PostgreSQL pgvector. Use cases: citizen/CMO grievance classification and summary,
potential duplicate assessment, and action-taken report review.

ai_analyses already records model_name, analysis_type, optional grievance/requester/department,
category/priority suggestions, summary, reasoning and JSONB result_data with creation time.
A nullable grievance allows pre-submission analysis. Store model output separately from approved
administrative decisions. analysis_type is a bounded string to allow later workflow types without
an enum migration. JSONB supports structured results, including future report-review context.

Phase 2+ should implement typed result schemas, provenance, input/privacy limits, timeouts,
failure handling, prompt-injection boundaries, authorized access and evaluations. Introduce a
migration for pgvector only when embedding dimensions/model/storage strategy are selected.
Potential duplicates need administrative review; they must not automatically reject grievances.
AI action-report reviews remain advisory: only authorized CMO administrators decide resolution.

