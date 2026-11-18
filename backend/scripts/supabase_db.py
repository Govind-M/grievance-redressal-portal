"""Explicit hosted-only tooling. Never runs destructive pytest fixtures or live AI."""

import argparse
import hashlib
import json
import re
import socket
from uuid import uuid4

from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import BACKEND_DIR, Settings
from app.db import models
from app.db.base import Base
from app.db.engine import build_engine
from app.modules.enums import GrievanceStatus, Priority, ReviewStatus, UpdateVisibility, UserRole
from scripts.seed import seed_departments

APP_TABLES = set(Base.metadata.tables)
ENUM_NAMES = {"user_role", "priority", "grievance_status", "review_status", "update_visibility"}


class HostedSafetyError(RuntimeError):
    pass


def target_fingerprint(settings):
    url = settings.selected_database_url
    return hashlib.sha256(f"{url.host}|{url.username}|{url.database}".encode()).hexdigest()[:16]


def require_supabase_identity(settings, connection):
    if settings.database_target != "supabase":
        raise HostedSafetyError("This tool accepts only the explicit supabase target")
    url = settings.selected_database_url
    pooler = url.host.endswith(".pooler.supabase.com")
    direct = re.fullmatch(r"db\.[a-z0-9-]+\.supabase\.co", url.host) is not None
    if not (pooler or direct) or (
        pooler and not re.fullmatch(r"[a-zA-Z0-9_]+\.[a-z0-9-]+", url.username)
    ):
        raise HostedSafetyError(
            "Configured endpoint is not an identifiable Supabase session/direct target"
        )
    identity = dict(
        connection.execute(
            text(
                "SELECT current_database() AS database,current_user AS db_user,"
                "current_setting('server_version') AS server_version,current_schema() AS schema"
            )
        )
        .mappings()
        .one()
    )
    expected_user = url.username.rsplit(".", 1)[0] if pooler else url.username
    if (
        identity["database"] != url.database
        or identity["db_user"] != expected_user
        or identity["schema"] != "public"
    ):
        raise HostedSafetyError(
            "Connected identity/schema does not match the explicitly configured target"
        )
    schemas = inspect(connection).get_schema_names()
    if not {"auth", "storage", "extensions"}.issubset(schemas):
        raise HostedSafetyError("Supabase managed-schema identity markers are missing")
    tls = bool(connection.connection.driver_connection.pgconn.ssl_in_use)
    if not tls:
        raise HostedSafetyError("Client-to-database/pooler TLS is not active")
    return {
        **identity,
        "target_fingerprint": target_fingerprint(settings),
        "connection_method": "session pooler" if pooler else "direct",
        "client_tls_verified": tls,
        "sslmode": "verify-full",
        "backend_pg_stat_ssl": [
            dict(x)
            for x in connection.execute(
                text("SELECT ssl,version,cipher FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
            ).mappings()
        ],
        "schemas": schemas,
        "search_path": connection.scalar(text("SHOW search_path")),
    }


def inventory(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema="public"))
    revision = None
    if "alembic_version" in tables:
        revisions = connection.scalars(text("SELECT version_num FROM public.alembic_version")).all()
        if len(revisions) != 1:
            raise HostedSafetyError("Hosted Alembic version is ambiguous")
        revision = revisions[0]
    vector = (
        connection.execute(
            text(
                "SELECT e.extversion,n.nspname AS schema FROM pg_extension e "
                "JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'"
            )
        )
        .mappings()
        .first()
    )
    return {
        "application_tables": sorted(tables & APP_TABLES),
        "other_public_tables": sorted(tables - APP_TABLES - {"alembic_version"}),
        "revision": revision,
        "vector": dict(vector) if vector else None,
    }


def require_initializable(connection, state):
    if state["revision"] == "0006" and set(state["application_tables"]) == APP_TABLES:
        return  # Explicitly idempotent re-verification/reference seeding.
    if state["revision"] is not None or state["application_tables"]:
        raise HostedSafetyError(
            "Existing/partial application schema requires manual review; no migration attempted"
        )
    collisions = ENUM_NAMES & {x["name"] for x in inspect(connection).get_enums(schema="public")}
    functions = connection.scalars(
        text(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname IN ('reject_history_mutation','stamp_updated_at')"
        )
    ).all()
    if collisions or functions:
        raise HostedSafetyError("Existing public types/functions conflict with the migration chain")


def managed_catalog_fingerprint(connection):
    # Managed objects are observed only. No changes to auth/storage/extensions/roles/default grants.
    rows = connection.execute(
        text(
            "SELECT n.nspname,c.relname,c.relkind,c.relowner FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT IN ('public','pg_catalog','information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%' "
            "ORDER BY n.nspname,c.relname"
        )
    ).all()
    return hashlib.sha256(json.dumps([list(x) for x in rows]).encode()).hexdigest()


def harden_application_objects(connection):
    """Deny independent Data API access; backend owner retains its existing permissions."""
    roles = set(
        connection.scalars(
            text(
                "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role')"
            )
        ).all()
    )
    grantees = "PUBLIC" + "".join(
        ", " + connection.dialect.identifier_preparer.quote(x) for x in sorted(roles)
    )
    quote = connection.dialect.identifier_preparer.quote
    for table in sorted(APP_TABLES | {"alembic_version"}):
        qualified = "public." + quote(table)
        connection.execute(text(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY"))
        connection.execute(text(f"REVOKE ALL PRIVILEGES ON TABLE {qualified} FROM {grantees}"))
    for name in ("reject_history_mutation", "stamp_updated_at"):
        connection.execute(
            text(f"REVOKE EXECUTE ON FUNCTION public.{quote(name)}() FROM {grantees}")
        )
    for role in sorted(roles):
        for table in sorted(APP_TABLES | {"alembic_version"}):
            if connection.scalar(
                text(
                    "SELECT has_table_privilege(:role,:table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"
                ),
                {"role": role, "table": "public." + quote(table)},
            ):
                raise HostedSafetyError(
                    "An API role retains application table access; transaction rolled back"
                )


def provision(settings, expected):
    if expected != target_fingerprint(settings):
        raise HostedSafetyError("Confirmation fingerprint does not match the configured target")
    engine = build_engine(settings, migration=True)
    try:
        with engine.begin() as connection:
            require_supabase_identity(settings, connection)
            if not connection.scalar(text("SELECT pg_try_advisory_xact_lock(2026111802)")):
                raise HostedSafetyError("Another application provisioning operation is running")
            before = inventory(connection)
            require_initializable(connection, before)
            managed_before = managed_catalog_fingerprint(connection)
            config = Config(str(BACKEND_DIR / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            harden_application_objects(connection)
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                departments = seed_departments(db)
                db.commit()
            if managed_catalog_fingerprint(connection) != managed_before:
                raise HostedSafetyError(
                    "Managed catalog unexpectedly changed; transaction rolled back"
                )
            after = inventory(connection)
            if after["revision"] != "0006" or set(after["application_tables"]) != APP_TABLES:
                raise HostedSafetyError("Migration did not create the complete application schema")
            return {
                "previous_revision": before["revision"],
                "final_revision": after["revision"],
                "department_reference_count": len(departments),
                "managed_catalog_preserved": True,
                "data_api_table_access_revoked": True,
                "application_rls_enabled": True,
            }
    finally:
        engine.dispose()


def verify_schema(connection):
    state = inventory(connection)
    if state["revision"] != "0006" or set(state["application_tables"]) != APP_TABLES:
        raise HostedSafetyError("Hosted schema is not complete at 0006")
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["connection"] = connection
    command.check(config)
    inspector = inspect(connection)
    expected_enums = {
        "user_role": [x.value for x in UserRole],
        "grievance_status": [x.value for x in GrievanceStatus],
        "priority": [x.value for x in Priority],
        "update_visibility": [x.value for x in UpdateVisibility],
        "review_status": [x.value for x in ReviewStatus],
    }
    actual_enums = {
        x["name"]: x["labels"]
        for x in inspector.get_enums(schema="public")
        if x["name"] in expected_enums
    }
    if actual_enums != expected_enums:
        raise HostedSafetyError(
            "Native application enum values do not match the controlled choices"
        )
    for table, index_name, predicate in (
        ("department_assignments", "uq_department_assignments_active_grievance", "closed_at"),
        ("action_taken_reports", "uq_action_taken_reports_pending_grievance", "PENDING"),
    ):
        index = next(
            (x for x in inspector.get_indexes(table, schema="public") if x["name"] == index_name),
            None,
        )
        if not index or not index["unique"] or predicate not in str(index["dialect_options"]):
            raise HostedSafetyError("Expected workflow partial unique index is missing")
    pk_count = fk_count = check_count = unique_count = index_count = 0
    for table in sorted(APP_TABLES):
        pk_count += bool(inspector.get_pk_constraint(table, schema="public")["constrained_columns"])
        actual_fks = inspector.get_foreign_keys(table, schema="public")
        if len(actual_fks) != len(Base.metadata.tables[table].foreign_key_constraints):
            raise HostedSafetyError("Application foreign key metadata mismatch")
        fk_count += len(actual_fks)
        check_count += len(inspector.get_check_constraints(table, schema="public"))
        unique_count += len(inspector.get_unique_constraints(table, schema="public"))
        index_count += len(inspector.get_indexes(table, schema="public"))
    triggers = [
        dict(x)
        for x in connection.execute(
            text(
                "SELECT c.relname AS table_name,t.tgname AS trigger_name FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname"
            )
        ).mappings()
    ]
    expected_triggers = {
        "grievance_history_append_only",
        "grievance_escalations_immutable",
        "users_updated_at",
        "grievances_updated_at",
    }
    if not expected_triggers.issubset({x["trigger_name"] for x in triggers}):
        raise HostedSafetyError("Expected application audit/timestamp triggers are missing")
    vector_type = connection.scalar(
        text(
            "SELECT format_type(a.atttypid,a.atttypmod) FROM pg_attribute a "
            "WHERE a.attrelid='public.grievance_embeddings'::regclass AND a.attname='embedding'"
        )
    )
    if not vector_type.endswith("vector(768)"):
        raise HostedSafetyError("Embedding vector dimensions do not match 768")
    rls = connection.scalar(
        text(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relname=ANY(:tables) AND c.relrowsecurity"
        ),
        {"tables": sorted(APP_TABLES | {"alembic_version"})},
    )
    json_type = connection.scalar(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='ai_analyses' AND column_name='result_data'"
        )
    )
    if json_type != "jsonb":
        raise HostedSafetyError("AI analysis results are not JSONB")
    return {
        **state,
        "schema_drift": "none",
        "primary_keys": pk_count,
        "foreign_keys": fk_count,
        "check_constraints": check_count,
        "unique_constraints": unique_count,
        "indexes": index_count,
        "triggers": triggers,
        "vector_column": vector_type,
        "rls_enabled_tables_including_version": rls,
        "controlled_enums": actual_enums,
        "workflow_partial_indexes_verified": True,
        "ai_result_type": json_type,
    }


def verify_vectors(connection, settings):
    a = "[" + ",".join(["1"] + ["0"] * 767) + "]"
    b = "[" + ",".join(["0", "1"] + ["0"] * 766) + "]"
    result = dict(
        connection.execute(
            text(
                "SELECT vector_dims(CAST(:a AS vector(768))) AS dimensions,"
                "CAST(:a AS vector(768)) <=> CAST(:a AS vector(768)) AS same_distance,"
                "CAST(:a AS vector(768)) <=> CAST(:b AS vector(768)) AS orthogonal_distance"
            ),
            {"a": a, "b": b},
        )
        .mappings()
        .one()
    )
    if result != {"dimensions": 768, "same_distance": 0.0, "orthogonal_distance": 1.0}:
        raise HostedSafetyError("Synthetic vector expression returned unexpected values")
    from sqlalchemy.exc import DBAPIError

    try:
        with connection.begin_nested():
            connection.execute(text("SELECT CAST('[1,0]' AS vector(768))"))
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) not in ("22000", "22023"):
            raise
        result["incompatible_dimensions_rejected"] = True
    else:
        raise HostedSafetyError("Incompatible vector dimensions were accepted")
    from app.modules.ai.repository import similar

    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        source = models.Grievance(id=uuid4(), district="Ernakulam")
        similar(db, source, [1.0] + [0.0] * 767, settings)
        result["repository_cosine_query_executed"] = True
    return result


def rollback_probe(settings, expected):
    """Synthetic persistence/order checks, always rolled back. No existing row is edited."""
    if expected != target_fingerprint(settings):
        raise HostedSafetyError("Confirmation fingerprint does not match the configured target")
    from app.modules.ai.content import fingerprint, source_content
    from app.modules.ai.repository import similar

    engine = build_engine(settings, migration=True)
    ids = [uuid4() for _ in range(3)]
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                require_supabase_identity(settings, connection)
                state = inventory(connection)
                if state["revision"] != "0006":
                    raise HostedSafetyError("Rollback probe requires the complete 0006 schema")
                with Session(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                ) as db:
                    department = db.scalar(
                        select(models.Department).where(models.Department.name == "Public Works")
                    )
                    if not department:
                        raise HostedSafetyError("Reference department is missing")
                    people = [
                        models.User(
                            id=ids[0],
                            name="Synthetic rollback citizen",
                            email=f"rollback-{ids[0]}@example.test",
                            password_hash="not-a-login-hash",
                            role=UserRole.CITIZEN,
                        ),
                        models.User(
                            id=ids[1],
                            name="Synthetic rollback administrator",
                            email=f"rollback-{ids[1]}@example.test",
                            password_hash="not-a-login-hash",
                            role=UserRole.CMO_ADMIN,
                        ),
                        models.User(
                            id=ids[2],
                            name="Synthetic rollback officer",
                            email=f"rollback-{ids[2]}@example.test",
                            password_hash="not-a-login-hash",
                            role=UserRole.DEPARTMENT_OFFICER,
                            department_id=department.id,
                        ),
                    ]
                    db.add_all(people)
                    db.flush()
                    grievances = [
                        models.Grievance(
                            id=uuid4(),
                            citizen_id=ids[0],
                            reference_number="CMK-PROBE-" + uuid4().hex[:16],
                            district="Ernakulam",
                            category="Other",
                            subject=f"Synthetic rollback probe {index}",
                            description="Fictional data used only inside a rolled-back verification transaction.",
                        )
                        for index in range(3)
                    ]
                    db.add_all(grievances)
                    db.flush()
                    assignment = models.DepartmentAssignment(
                        grievance_id=grievances[0].id,
                        department_id=department.id,
                        officer_id=ids[2],
                        assigned_by=ids[1],
                        assignment_note="Synthetic rollback only",
                    )
                    db.add(assignment)
                    db.flush()
                    report = models.ActionTakenReport(
                        grievance_id=grievances[0].id,
                        assignment_id=assignment.id,
                        submitted_by=ids[2],
                        report_details="The synthetic report claims inspection.",
                    )
                    db.add(report)
                    db.flush()
                    analysis = models.AIAnalysis(
                        grievance_id=grievances[0].id,
                        report_id=report.id,
                        requested_by=ids[1],
                        model_name="synthetic-no-provider",
                        analysis_type="ACTION_REPORT_REVIEW",
                        result_data={"is_advisory": True, "synthetic": True},
                        summary="The report states a fictional inspection.",
                    )
                    db.add(analysis)
                    vectors = [
                        [1.0] + [0.0] * 767,
                        [0.9, 0.1] + [0.0] * 766,
                        [0.0, 1.0] + [0.0] * 766,
                    ]
                    for row, vector in zip(grievances, vectors, strict=True):
                        db.add(
                            models.GrievanceEmbedding(
                                grievance_id=row.id,
                                model_name=settings.gemini_embedding_model,
                                dimensions=768,
                                embedding=vector,
                                source_fingerprint=fingerprint(source_content(row)),
                            )
                        )
                    db.flush()
                    db.expire(analysis)
                    restored = db.get(models.AIAnalysis, analysis.id)
                    if restored.report_id != report.id or not restored.result_data["synthetic"]:
                        raise HostedSafetyError("AI provenance/JSONB roundtrip failed")
                    candidates = similar(db, grievances[0], vectors[0], settings)
                    if not candidates or candidates[0][0].id != grievances[1].id:
                        raise HostedSafetyError("Vector repository ordering/exclusion failed")
                    if any(candidate.id == grievances[0].id for candidate, _ in candidates):
                        raise HostedSafetyError("Vector query included its current grievance")
                    result = {
                        "ai_jsonb_roundtrip": True,
                        "report_provenance_roundtrip": True,
                        "vector_insert_roundtrip": True,
                        "repository_ordering_verified": True,
                    }
            finally:
                transaction.rollback()
            # Check outside the rolled-back transaction, before reporting success.
            remaining = connection.scalar(
                select(models.User.id).where(models.User.id.in_(ids)).limit(1)
            )
            if remaining is not None:
                raise HostedSafetyError(
                    "Synthetic rollback verification unexpectedly found a persisted row"
                )
            return {**result, "synthetic_transaction_rolled_back": True, "gemini_requests": 0}
    finally:
        engine.dispose()


def safe_error(exc):
    # Classify privately; never emit the raw message, URL, SQL parameters or credentials.
    message = str(exc).lower()
    sqlstate = getattr(getattr(exc, "orig", exc), "sqlstate", None)
    if isinstance(exc, HostedSafetyError):
        return {"error": str(exc)}
    if "certificate" in message:
        reason = "TLS certificate verification failed; check SUPABASE_SSLROOTCERT and hostname"
    elif sqlstate == "28P01":
        reason = "PostgreSQL authentication failed; check the private configured credentials"
    elif isinstance(exc, ValueError):
        reason = "Invalid hosted configuration; check target URL, TLS mode and CA path"
    else:
        reason = "Hosted operation failed; inspect configuration/permissions without exposing credentials"
    return {"error": reason, "error_type": type(exc).__name__, "sqlstate": sqlstate}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Explicit Supabase-only, no-Gemini database tooling"
    )
    parser.add_argument("operation", choices=["inspect", "provision", "verify", "rollback-probe"])
    parser.add_argument("--confirm-target", help="Fingerprint from the read-only inspect command")
    args = parser.parse_args(argv)
    engine = None
    try:
        settings = Settings(
            database_target="supabase", ai_enabled=False, ai_live_requests_enabled=False
        )
        url = settings.selected_database_url
        socket.getaddrinfo(url.host, url.port or 5432)
        engine = build_engine(settings, migration=True)
        if args.operation in ("provision", "rollback-probe"):
            if not args.confirm_target:
                raise HostedSafetyError("Provision requires --confirm-target from a prior inspect")
            result = (provision if args.operation == "provision" else rollback_probe)(
                settings, args.confirm_target
            )
        else:
            with engine.connect() as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                result = {
                    "identity": require_supabase_identity(settings, connection),
                    "inventory": inventory(connection),
                }
                if args.operation == "verify":
                    result["schema"] = verify_schema(connection)
                    result["vectors"] = verify_vectors(connection, settings)
        print(json.dumps(result, default=str))
        return 0
    except Exception as exc:
        print(json.dumps(safe_error(exc)))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
