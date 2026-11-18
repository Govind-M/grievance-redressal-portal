"""Consistent, versioned content and validated compatible vectors."""

import math

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Grievance
from app.modules.ai import repository
from app.modules.ai.content import fingerprint, source_content
from app.modules.ai.embedding_models import GrievanceEmbedding
from app.modules.ai.errors import AIUnavailable, InvalidAIOutput


def validated_vector(values, dimensions: int) -> list[float]:
    if not isinstance(values, (list, tuple)) or len(values) != dimensions:
        raise InvalidAIOutput()
    if any(
        isinstance(x, bool)
        or not isinstance(x, (int, float))
        or not math.isfinite(x)
        or abs(x) > 1e10
        for x in values
    ):
        raise InvalidAIOutput()
    norm = math.sqrt(sum(x * x for x in values))
    if norm <= 1e-12:
        raise InvalidAIOutput()
    return [float(x / norm) for x in values]


def ensure_embedding(db, row, runtime):
    if not repository.vectors_ready(db):
        raise AIUnavailable(
            "Semantic retrieval requires pgvector and migration 0006. "
            "Grievance analysis and manual workflows remain available."
        )
    settings = runtime.settings
    if len(row.subject) > 255 or len(row.description) > 10000:
        raise HTTPException(422, "Stored complaint exceeds the embedding input limit.")
    content = source_content(row)
    digest = fingerprint(content)
    existing = repository.embedding(
        db, row.id, settings.gemini_embedding_model, settings.ai_embedding_dimensions
    )
    if existing and existing.source_fingerprint == digest:
        return validated_vector(
            [float(x) for x in existing.embedding], settings.ai_embedding_dimensions
        )
    # No official row is locked across the external network call.
    try:
        vector = validated_vector(runtime.provider.embed(content), settings.ai_embedding_dimensions)
    except HTTPException:
        raise
    except TimeoutError:
        raise HTTPException(504, "AI embedding provider timed out.") from None
    except Exception:
        raise AIUnavailable("AI embedding provider is unavailable.") from None
    current = db.scalar(
        select(Grievance)
        .where(Grievance.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None or fingerprint(source_content(current)) != digest:
        raise HTTPException(409, "Grievance content changed during analysis; retry.")
    statement = insert(GrievanceEmbedding).values(
        grievance_id=row.id,
        model_name=settings.gemini_embedding_model,
        dimensions=settings.ai_embedding_dimensions,
        embedding=vector,
        source_fingerprint=digest,
    )
    from sqlalchemy import func

    statement = statement.on_conflict_do_update(
        index_elements=["grievance_id", "model_name", "dimensions"],
        set_={"embedding": vector, "source_fingerprint": digest, "updated_at": func.now()},
    )
    db.execute(statement)
    return vector
