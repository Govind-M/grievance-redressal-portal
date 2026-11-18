"""Run from backend: python -m scripts.seed. Fictional data only."""

import argparse
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.models import Department, User, UserSession
from app.db.session import get_session_factory
from app.modules.enums import UserRole

DEPARTMENTS = (
    "Public Works",
    "Health",
    "General Education",
    "Water Resources",
    "Local Self Government",
    "Transport",
    "Revenue",
)
ACCOUNTS = (
    ("Demo Citizen", "citizen@example.test", UserRole.CITIZEN, "seed_citizen_password"),
    ("Demo CMO Administrator", "cmo@example.test", UserRole.CMO_ADMIN, "seed_cmo_password"),
    (
        "Demo Public Works Officer",
        "officer@example.test",
        UserRole.DEPARTMENT_OFFICER,
        "seed_officer_password",
    ),
)


def seed_departments(session: Session) -> dict[str, Department]:
    """Reference-only seed: no accounts/passwords and no updates to pre-existing rows."""
    session.execute(text("SELECT pg_advisory_xact_lock(2026111701)"))
    departments = {}
    for name in DEPARTMENTS:
        department = session.scalar(select(Department).where(Department.name == name))
        if department is None:
            department = Department(
                name=name, description=f"Fictional demonstration department: {name}", is_active=True
            )
            session.add(department)
            session.flush()
        departments[name] = department
    return departments


def seed(session: Session, settings: Settings, *, reset_passwords: bool = False) -> None:
    """Atomic, serialized and idempotent. Existing accounts/passwords are preserved."""
    if settings.database_target != "local":
        raise ValueError("Hosted targets permit reference-only seeding, not demo accounts")
    # Validate all secrets before mutating anything; caller owns the transaction.
    if reset_passwords and settings.app_env != "development":
        raise ValueError("Demo password reset is restricted to APP_ENV=development")
    for _, _, _, key in ACCOUNTS:
        secret = getattr(settings, key)
        if not secret or not 12 <= len(secret.get_secret_value()) <= 128:
            raise ValueError(f"{key.upper()} must contain 12 to 128 characters")
    departments = seed_departments(session)
    for name, email, role, key in ACCOUNTS:
        user = session.scalar(select(User).where(User.email == email).with_for_update())
        if user is None:
            department = (
                departments["Public Works"] if role == UserRole.DEPARTMENT_OFFICER else None
            )
            if department is not None and not department.is_active:
                raise ValueError("Cannot seed an officer into an inactive department")
            session.add(
                User(
                    name=name,
                    email=email,
                    role=role,
                    department=department,
                    password_hash=hash_password(getattr(settings, key).get_secret_value()),
                    is_active=True,
                )
            )
        elif reset_passwords:
            if (
                user.role != role
                or not user.is_active
                or (
                    role == UserRole.DEPARTMENT_OFFICER
                    and (
                        user.department_id != departments["Public Works"].id
                        or not departments["Public Works"].is_active
                    )
                )
            ):
                raise ValueError("Existing demo account does not match the expected active role")
            user.password_hash = hash_password(getattr(settings, key).get_secret_value())
            session.execute(
                update(UserSession)
                .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC), revocation_reason="demo_password_reset")
            )
    session.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed fictional demonstration records")
    parser.add_argument(
        "--reset-demo-passwords",
        action="store_true",
        help="Development only: reset exactly the three demo passwords",
    )
    parser.add_argument(
        "--reference-only",
        action="store_true",
        help="Seed canonical departments only; never create accounts",
    )
    args = parser.parse_args()
    with get_session_factory()() as session, session.begin():
        if args.reference_only:
            if args.reset_demo_passwords:
                raise ValueError("Reference-only seeding cannot reset passwords")
            seed_departments(session)
        else:
            if get_settings().database_target != "local":
                raise ValueError("Hosted databases permit only --reference-only seeding")
            seed(session, get_settings(), reset_passwords=args.reset_demo_passwords)
    print("Fictional demonstration seed completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print connection strings, credentials, SQL parameters or raw DB errors.
        logging.error(
            "Seed failed (%s). Check database, migrations and seed settings.", type(exc).__name__
        )
        raise SystemExit(1) from None
