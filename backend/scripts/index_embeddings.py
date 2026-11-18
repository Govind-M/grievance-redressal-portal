"""Explicit bounded historical indexing; never run automatically or by the smoke test."""

import argparse
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Grievance, User
from app.db.session import get_session_factory
from app.integrations.embeddings import ensure_embedding
from app.modules.ai.runtime import AIRuntime
from app.modules.enums import UserRole


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Opt-in historical indexing (max 10 grievances/run). Requires separate explicit approval "
            "of embedding requests; not authorized by approval for the two-request live smoke test."
        )
    )
    parser.add_argument("--approved-live-requests", action="store_true")
    parser.add_argument("--admin-user-id", type=UUID, required=True)
    parser.add_argument("--limit", type=int, default=1, choices=range(1, 11))
    parser.add_argument("--after", type=UUID)
    args = parser.parse_args(argv)
    if not args.approved_live_requests:
        print("No approval: no embedding requests made.")
        return 2
    runtime = AIRuntime(get_settings())
    try:
        runtime.provider.check_allowed()
    except Exception:
        print("AI is disabled or unconfigured; no provider requests made.")
        return 2
    with get_session_factory()() as db:
        user = db.get(User, args.admin_user_id)
        if not user or not user.is_active or user.role != UserRole.CMO_ADMIN:
            print("An active CMO administrator is required.")
            return 2
        query = select(Grievance).order_by(Grievance.id).limit(args.limit)
        if args.after:
            query = query.where(Grievance.id > args.after)
        rows = list(db.scalars(query))
        for row in rows:
            try:
                runtime.charge(user.id)
                ensure_embedding(db, row, runtime)
                db.commit()
            except Exception:
                db.rollback()
                print(
                    "Indexing stopped safely; details suppressed. Earlier successful rows remain."
                )
                return 1
        print(
            f"Processed {len(rows)} grievances; unchanged vectors reused. No official records changed."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
