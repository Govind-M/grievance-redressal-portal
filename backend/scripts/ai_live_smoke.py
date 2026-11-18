"""OPT-IN ONLY. Never imported/executed by startup, pytest, seed or migration code."""

import argparse
import json
from uuid import UUID

from app.core.config import Settings
from app.integrations.embeddings import validated_vector
from app.integrations.gemini import GeminiProvider
from app.modules.ai.prompts import CLASSIFY
from app.modules.ai.schemas import GrievanceAnalysisResult


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Live Gemini verification: at most ONE classification + ONE embedding, zero retries. "
            "Run only after the user has explicitly approved these two provider requests."
        )
    )
    parser.add_argument(
        "--approved-live-requests",
        action="store_true",
        help="Attest explicit user approval of exactly these two live requests.",
    )
    args = parser.parse_args(argv)
    if not args.approved_live_requests:
        print("Not authorized: no live requests made. Obtain explicit approval first.")
        return 2
    settings = Settings(ai_enabled=True, ai_live_requests_enabled=True, ai_max_retries=0)
    provider = GeminiProvider(settings)
    try:
        provider.check_allowed()
    except Exception:
        print("Provider configuration unavailable; live requests made: 0.")
        return 2
    # Synthetic examples only. No production grievance/profile data or database mutation.
    department_id = UUID("00000000-0000-4000-8000-000000000001")
    payload = json.dumps(
        {
            "complaint": {
                "district": "Ernakulam",
                "subject": "Fictional road inspection",
                "description": "A fictional community road has potholes requiring inspection.",
            },
            "active_departments": [{"id": str(department_id), "name": "Fictional Public Works"}],
            "allowed_categories": ["Roads and Infrastructure"],
        }
    )
    outcomes = {}
    attempts = {"classification": 0, "embedding": 0}
    try:
        attempts["classification"] = 1
        result = provider.structured(CLASSIFY, payload, GrievanceAnalysisResult)
        if result.suggested_department_id not in (None, department_id):
            raise ValueError("Invalid department")
        outcomes["classification"] = "passed"
    except Exception:
        outcomes["classification"] = "failed (provider details suppressed)"
    try:
        attempts["embedding"] = 1
        vector = validated_vector(
            provider.embed("Fictional road inspection in Ernakulam."),
            settings.ai_embedding_dimensions,
        )
        outcomes["embedding"] = f"passed ({len(vector)} dimensions)"
    except Exception:
        outcomes["embedding"] = "failed (provider details suppressed)"
    print(json.dumps({"request_attempts": attempts, "automatic_retries": 0, "results": outcomes}))
    return 0 if all(value.startswith("passed") for value in outcomes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
