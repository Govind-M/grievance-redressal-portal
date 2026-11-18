"""Stable content serialization, shared by indexing and stale-candidate validation."""

import hashlib
import json


def source_content(row) -> str:
    return json.dumps(
        {
            "format": "grievance-v1",
            "district": row.district,
            "category": row.category,
            "subject": row.subject,
            "description": row.description,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
