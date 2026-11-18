# Integration boundaries

gemini.py owns lazy opt-in LangChain structured chat and Google GenAI embeddings.
embeddings.py validates vectors, fingerprints content and coordinates idempotent storage.
No provider call runs at startup. AI_ENABLED and AI_LIVE_REQUESTS_ENABLED default false.
Pytest blocks real Gemini and non-loopback network calls. Private object storage remains deferred.

