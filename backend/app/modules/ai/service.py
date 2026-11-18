"""Advisory pipelines only. These services never call the official workflow mutators."""

import json
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError

from app.integrations.embeddings import ensure_embedding, fingerprint
from app.modules.ai import prompts, repository
from app.modules.ai import schemas as dto
from app.modules.ai.errors import AIUnavailable, InvalidAIOutput
from app.modules.enums import UserRole
from app.modules.grievances.choices import Category


def require_role(user, role):
    if not user.is_active or user.role != role:
        raise HTTPException(403, "Insufficient permissions.")


def encode(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def complaint(row):
    # No profile, contact details, assignment notes or status history.
    # Bounds also apply to imported/legacy records, not only API-created input.
    if len(row.subject) > 255 or len(row.description) > 10000:
        raise HTTPException(422, "Stored complaint exceeds the AI input limit.")
    return {"district": row.district, "subject": row.subject, "description": row.description}


def structured(runtime, prompt, payload, schema):
    encoded = encode(payload)
    if len(encoded) > runtime.settings.ai_max_input_characters:
        raise HTTPException(422, "AI context exceeds the configured input limit.")
    try:
        return schema.model_validate(runtime.provider.structured(prompt, encoded, schema))
    except ValidationError:
        raise InvalidAIOutput() from None
    except (HTTPException,):
        raise
    except TimeoutError:
        raise HTTPException(
            504, "AI provider timed out. Manual workflows remain available."
        ) from None
    except Exception:
        raise AIUnavailable() from None


def classify(db, runtime, user, data):
    if not runtime.settings.ai_enabled:
        raise AIUnavailable("AI is disabled. Manual workflows remain available.")
    departments = repository.active_departments(db)
    payload = {
        "complaint": complaint(data),
        "active_departments": [{"id": str(x.id), "name": x.name} for x in departments],
        "allowed_categories": [x.value for x in Category],
    }
    # Bound DB-authored configuration too: don't silently omit eligible departments.
    if len(departments) > 100 or len(encode(payload)) > 30000:
        raise HTTPException(422, "AI department/context limit exceeded.")
    key = (
        str(user.id),
        "classification-v1",
        runtime.settings.gemini_chat_model,
        fingerprint(encode(payload)),
    )
    cached = runtime.cached(key)
    result = cached or structured(runtime, prompts.CLASSIFY, payload, dto.GrievanceAnalysisResult)
    department = None
    if result.suggested_department_id is not None:
        # Revalidate after the external call; department activation can change meanwhile.
        active = {x.id: x.name for x in repository.active_departments(db)}
        if result.suggested_department_id not in active or result.suggested_department_id not in {
            x.id for x in departments
        }:
            raise InvalidAIOutput()
        department = dto.DepartmentSuggestion(
            id=result.suggested_department_id, name=active[result.suggested_department_id]
        )
    if not cached:
        runtime.remember(key, result)
    return dto.AnalysisResponse(
        **result.model_dump(),
        suggested_department=department,
        model_name=runtime.settings.gemini_chat_model,
    )


def citizen_analysis(db, user, data, runtime):
    require_role(user, UserRole.CITIZEN)
    runtime.charge(user.id)
    # Intentionally do not store pre-submission drafts or create grievances.
    return classify(db, runtime, user, data)


def saved_response(db, user, runtime, row, result, kind, report_id=None):
    saved = repository.save_analysis(
        db,
        grievance_id=row.id,
        report_id=report_id,
        requested_by=user.id,
        analysis_type=kind,
        model_name=runtime.settings.gemini_chat_model,
        result_data=result.model_dump(mode="json"),
        suggested_department_id=getattr(result, "suggested_department_id", None),
        suggested_category=getattr(result, "suggested_category", None),
        suggested_priority=getattr(result, "suggested_priority", None),
        summary=getattr(result, "summary", getattr(result, "report_summary", None)),
    )
    return saved


def cmo_analysis(db, user, grievance_id: UUID, runtime):
    require_role(user, UserRole.CMO_ADMIN)
    row = repository.grievance(db, grievance_id)
    if row is None:
        raise HTTPException(404, "Grievance not found.")
    runtime.charge(user.id)
    try:
        result = classify(db, runtime, user, row)
        saved = saved_response(db, user, runtime, row, result, "GRIEVANCE_CLASSIFICATION")
        saved.result_data = {
            **saved.result_data,
            "source_fingerprint": fingerprint(encode(complaint(row))),
            "prompt_version": "classification-v1",
        }
        response = result.model_copy(
            update={"analysis_id": saved.id, "created_at": saved.created_at}
        )
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def report_analysis(db, user, report_id: UUID, runtime):
    require_role(user, UserRole.CMO_ADMIN)
    report = repository.report(db, report_id)
    if report is None:
        raise HTTPException(404, "Report not found.")
    row = repository.grievance(db, report.grievance_id)
    if not runtime.settings.ai_enabled:
        raise AIUnavailable("AI is disabled. Manual workflows remain available.")
    runtime.charge(user.id)
    if len(report.report_details) > 20000:
        raise HTTPException(422, "Stored report exceeds the AI input limit.")
    payload = {
        "complaint": complaint(row),
        "category": row.category,
        "report": report.report_details,
        "investigation_updates": repository.investigation_context(db, report),
    }
    key = (
        str(user.id),
        "report-review-v1",
        runtime.settings.gemini_chat_model,
        str(report_id),
        fingerprint(encode(payload)),
    )
    try:
        result = runtime.cached(key) or structured(
            runtime, prompts.REPORT_REVIEW, payload, dto.ActionTakenAIReview
        )
        runtime.remember(key, result)
        saved = saved_response(db, user, runtime, row, result, "ACTION_REPORT_REVIEW", report_id)
        saved.result_data = {
            **saved.result_data,
            "source_fingerprint": fingerprint(encode(payload)),
            "prompt_version": "report-review-v1",
        }
        response = dto.ReportAnalysisResponse(
            **result.model_dump(),
            report_id=report_id,
            analysis_id=saved.id,
            model_name=saved.model_name,
            created_at=saved.created_at,
        )
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def detect_duplicates(db, user, grievance_id: UUID, runtime):
    require_role(user, UserRole.CMO_ADMIN)
    row = repository.grievance(db, grievance_id)
    if row is None:
        raise HTTPException(404, "Grievance not found.")
    if not runtime.settings.ai_enabled:
        raise AIUnavailable("AI is disabled. Manual workflows remain available.")
    runtime.charge(user.id)
    try:
        complaint(row)
        vector = ensure_embedding(db, row, runtime)
        # Embeddings are an independent idempotent cache. Release the short content-check lock
        # before the comparison chat request; AI must not hold workflow locks over that call.
        db.commit()
        candidates = repository.similar(db, row, vector, runtime.settings)
        if len(candidates) > runtime.settings.ai_duplicate_candidate_limit:
            raise InvalidAIOutput()
        mapping = {x.id: (x, distance) for x, distance in candidates}
        if row.id in mapping or len(mapping) != len(candidates):
            raise InvalidAIOutput()
        decisions = dto.DuplicateAssessmentResult(candidates=[])
        if candidates:
            payload = {
                "complaint": complaint(row),
                "candidates": [
                    {
                        "id": str(candidate.id),
                        **complaint(candidate),
                        "description": candidate.description[:2000],
                        "description_is_excerpt": len(candidate.description) > 2000,
                    }
                    for candidate, _distance in candidates
                ],
            }
            decisions = structured(
                runtime, prompts.DUPLICATES, payload, dto.DuplicateAssessmentResult
            )
        if len(decisions.candidates) != len(mapping) or {
            x.grievance_id for x in decisions.candidates
        } != set(mapping):
            raise InvalidAIOutput()
        result = dto.DuplicateAssessmentResult(candidates=decisions.candidates)
        saved = saved_response(db, user, runtime, row, result, "DUPLICATE_ASSESSMENT")
        response = dto.DuplicateResponse(
            candidates=[
                dto.DuplicateCandidate(
                    **item.model_dump(),
                    reference_number=mapping[item.grievance_id][0].reference_number,
                    similarity_score=max(-1.0, min(1.0, 1.0 - mapping[item.grievance_id][1])),
                )
                for item in decisions.candidates
            ],
            analysis_id=saved.id,
            created_at=saved.created_at,
            model_name=saved.model_name,
        )
        # Persist exact returned retrieval scores/references, not just model decisions.
        saved.result_data = {
            **response.model_dump(mode="json"),
            "embedding_model": runtime.settings.gemini_embedding_model,
            "embedding_dimensions": runtime.settings.ai_embedding_dimensions,
            "prompt_version": "duplicates-v1",
            "source_fingerprint": fingerprint(encode(complaint(row))),
        }
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
