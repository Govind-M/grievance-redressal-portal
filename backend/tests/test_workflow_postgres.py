"""Phase 4 HTTP contracts, audit privacy, row locks and PostgreSQL constraints."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from test_grievances_postgres import api as citizen_api  # noqa: F401
from test_grievances_postgres import create

from app.db.models import (
    ActionTakenReport,
    Department,
    DepartmentAssignment,
    Grievance,
    GrievanceEscalation,
    User,
)
from app.modules.enums import UserRole
from app.modules.grievances import workflow

pytestmark = pytest.mark.postgres
P = "/api/v1"


@pytest.fixture
def api(citizen_api):  # noqa: F811 - imported pytest fixture dependency
    api = citizen_api
    with api.db() as db:
        first = db.get(User, api.users["officer"])
        health = db.scalar(select(Department).where(Department.name == "Health"))
        for name, department, active in (
            ("colleague", first.department_id, True),
            ("outsider", health.id, True),
            ("inactive", first.department_id, False),
        ):
            user = User(
                name=f"Fictional {name}",
                email=f"{name}@example.test",
                password_hash=first.password_hash,
                role=UserRole.DEPARTMENT_OFFICER,
                department_id=department,
                is_active=active,
            )
            db.add(user)
            db.flush()
            api.users[name] = user.id
        api.department_id = first.department_id
        api.health_id = health.id
        db.commit()
    return api


def call(api, method, path, data=None, who="cmo", status=200, params=None):
    response = api.client.request(
        method, P + path, headers=api.headers(who), json=data, params=params
    )
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def begin(api, designated=False):
    row = create(api)
    gid = row["id"]
    call(
        api,
        "PATCH",
        f"/cmo/grievances/{gid}/review",
        {"remarks": "CMO secret review marker", "visibility": "INTERNAL"},
    )
    result = assign(api, gid, officer_id=str(api.users["officer"]) if designated else None)
    return gid, result


def assign(api, gid, reassign=False, **changes):
    return call(
        api,
        "POST",
        f"/cmo/grievances/{gid}/{'reassign' if reassign else 'assign'}",
        {
            "department_id": str(api.department_id),
            "assignment_note": "CMO secret assignment marker",
            **changes,
        },
    )


def report(api, gid, who="officer", status=201):
    return call(
        api,
        "POST",
        f"/officer/grievances/{gid}/reports",
        {"report_details": "Fictional repairs completed and inspected at the site."},
        who=who,
        status=status,
    )


def review_report(api, rid, decision="ACCEPTED", status=200):
    return call(
        api,
        "POST",
        f"/cmo/reports/{rid}/review",
        {"decision": decision, "review_remarks": "CMO report review reason marker"},
        status=status,
    )


@pytest.mark.parametrize("who", ["citizen", "officer"])
@pytest.mark.parametrize(
    "path",
    [
        "/cmo/dashboard/stats",
        "/cmo/grievances",
        "/cmo/reports",
        "/cmo/statistics/districts",
        "/cmo/statistics/departments",
    ],
)
def test_cmo_role_denials(api, who, path):
    call(api, "GET", path, who=who, status=403)


@pytest.mark.parametrize("who", ["citizen", "cmo"])
@pytest.mark.parametrize(
    "path",
    ["/officer/dashboard/stats", "/officer/grievances", "/officer/grievances/assigned-to-me"],
)
def test_officer_role_denials(api, who, path):
    call(api, "GET", path, who=who, status=403)


def test_complete_two_cycle_lifecycle(api):
    gid, assigned = begin(api, designated=True)
    assert assigned["status"] == "IN_PROGRESS"
    assert assigned["current_assignment"]["officer_id"] == str(api.users["officer"])
    assert assigned["due_at"] is not None
    assert len(assigned["history"]) == 3
    report1 = report(api, gid)
    assert report1["review_status"] == "PENDING"
    report(api, gid, status=409)
    returned = review_report(api, report1["id"], "RETURNED")
    assert returned["status"] == "IN_PROGRESS"
    assert len(returned["history"]) == 3
    report2 = report(api, gid)
    resolved = review_report(api, report2["id"])
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None
    assert resolved["current_assignment"] is None
    assert len(resolved["history"]) == 4
    review_report(api, report2["id"], status=409)
    call(api, "GET", f"/officer/grievances/{gid}", who="officer", status=404)
    tracked = call(api, "GET", f"/grievances/{gid}", who="citizen")
    assert tracked["status"] == "RESOLVED"
    reopened = call(
        api,
        "POST",
        f"/cmo/grievances/{gid}/reopen",
        {"reason": "Citizen reports recurring fictional damage."},
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["resolved_at"] is None
    assert len(reopened["reports"]) == 2
    call(api, "POST", f"/cmo/grievances/{gid}/resume", {}, status=409)
    assign(api, gid)
    report(api, gid, status=409)
    resumed = call(api, "POST", f"/cmo/grievances/{gid}/resume", {})
    assert resumed["status"] == "IN_PROGRESS"
    review_report(api, report2["id"], status=409)
    new_report = report(api, gid, who="colleague")
    assert new_report["assignment_id"] != report2["assignment_id"]
    again = review_report(api, new_report["id"])
    assert again["status"] == "RESOLVED"
    assert len(again["history"]) == 7
    assert len(again["assignments"]) == 2
    assert sum(r["review_status"] == "ACCEPTED" for r in again["reports"]) == 2


def test_hybrid_permissions_and_privacy(api):
    gid, _ = begin(api, designated=True)
    same = call(api, "GET", f"/officer/grievances/{gid}", who="colleague")
    assert not same["can_modify"]
    assert "CMO secret" not in str(same)
    for who, code in (("colleague", 403), ("outsider", 404)):
        call(
            api,
            "POST",
            f"/officer/grievances/{gid}/updates",
            {"message": "Fictional inspection update", "visibility": "INTERNAL"},
            who=who,
            status=code,
        )
        report(api, gid, who=who, status=code)
    call(api, "GET", f"/officer/grievances/{gid}", who="outsider", status=404)
    call(api, "GET", f"/officer/grievances/{gid}/reports", who="outsider", status=404)
    for visibility in ("INTERNAL", "PUBLIC"):
        call(
            api,
            "POST",
            f"/officer/grievances/{gid}/updates",
            {"message": f"{visibility} investigation marker", "visibility": visibility},
            who="officer",
            status=201,
        )
        call(
            api,
            "POST",
            f"/cmo/grievances/{gid}/remarks",
            {"message": f"{visibility} CMO marker", "visibility": visibility},
            status=201,
        )
    for suffix in (f"/grievances/{gid}", f"/grievances/track/{same['reference_number']}"):
        citizen = call(api, "GET", suffix, who="citizen")
        assert "PUBLIC investigation marker" in str(citizen)
        assert "PUBLIC CMO marker" in str(citizen)
        assert "INTERNAL" not in str(citizen)
        assert "CMO secret" not in str(citizen)
    colleague = call(api, "GET", f"/officer/grievances/{gid}", who="colleague")
    assert "INTERNAL investigation marker" in str(colleague)
    assert "INTERNAL CMO marker" not in str(colleague)
    assert "CMO secret" not in str(colleague)
    assert len(colleague["history"]) == 3
    admin = call(api, "GET", f"/cmo/grievances/{gid}")
    assert "CMO secret" in str(admin)
    assert admin["history"][1]["changed_by"] == str(api.users["cmo"])
    assert admin["citizen"]["email"] == "citizen@example.test"
    assert "password_hash" not in str(admin) and "storage_key" not in str(admin)


def test_department_only_reassign_and_pending_policy(api):
    gid, initial = begin(api)
    call(
        api,
        "POST",
        f"/officer/grievances/{gid}/updates",
        {"message": "Department colleague inspection"},
        who="colleague",
        status=201,
    )
    old = report(api, gid, who="colleague")
    call(
        api,
        "POST",
        f"/cmo/grievances/{gid}/reassign",
        {"department_id": str(api.health_id), "assignment_note": "Transfer after investigation."},
        status=409,
    )
    review_report(api, old["id"], "RETURNED")
    moved = assign(
        api,
        gid,
        reassign=True,
        department_id=str(api.health_id),
        officer_id=str(api.users["outsider"]),
    )
    assert moved["current_department_id"] == str(api.health_id)
    assert len(moved["assignments"]) == 2
    assert moved["assignments"][0]["closed_at"] is not None
    assert len(moved["history"]) == len(initial["history"])
    call(api, "GET", f"/officer/grievances/{gid}", who="officer", status=404)
    new = call(api, "GET", f"/officer/grievances/{gid}", who="outsider")
    assert new["reports"] == []
    assert "Department colleague inspection" not in str(new)
    report(api, gid, who="outsider")
    with api.db() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DepartmentAssignment)
                .where(
                    DepartmentAssignment.grievance_id == UUID(gid),
                    DepartmentAssignment.closed_at.is_(None),
                )
            )
            == 1
        )


@pytest.mark.parametrize(
    "invalid", ["other_department", "inactive_officer", "citizen", "unknown", "inactive_department"]
)
def test_invalid_assignment_atomic(api, invalid):
    row = create(api)
    gid = row["id"]
    call(api, "PATCH", f"/cmo/grievances/{gid}/review", {})
    data = {
        "department_id": str(api.department_id),
        "assignment_note": "Fictional assignment note.",
    }
    if invalid == "inactive_department":
        with api.db() as db:
            db.get(Department, api.department_id).is_active = False
            db.commit()
    else:
        data["officer_id"] = str(
            {
                "other_department": api.users["outsider"],
                "inactive_officer": api.users["inactive"],
                "citizen": api.users["citizen"],
                "unknown": uuid4(),
            }[invalid]
        )
    call(api, "POST", f"/cmo/grievances/{gid}/assign", data, status=422)
    after = call(api, "GET", f"/cmo/grievances/{gid}")
    assert after["status"] == "UNDER_REVIEW"
    assert after["assignments"] == []


def test_invalid_transitions(api):
    row = create(api)
    gid = row["id"]
    for action, data in (
        (
            "assign",
            {
                "department_id": str(api.department_id),
                "assignment_note": "Invalid early assignment.",
            },
        ),
        ("reopen", {"reason": "Not yet resolved fictional case."}),
        ("resume", {}),
    ):
        call(api, "POST", f"/cmo/grievances/{gid}/{action}", data, status=409)
    call(api, "PATCH", f"/cmo/grievances/{gid}/review", {})
    call(api, "PATCH", f"/cmo/grievances/{gid}/review", {}, status=409)


def test_priority_escalation_overdue_analytics(api):
    gid, _ = begin(api)
    unassigned = create(api, district="Kollam")
    with api.db() as db:
        db.get(Grievance, UUID(gid)).due_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()
    before = call(api, "GET", "/cmo/dashboard/stats")
    assert before["total"] == 2 and before["overdue"] == 1 and before["pending"] == 2
    assert call(api, "GET", "/officer/dashboard/stats", who="outsider")["total"] == 0
    officer_stats = call(api, "GET", "/officer/dashboard/stats", who="officer")
    assert officer_stats["total"] == 1 and officer_stats["unassigned_to_officer"] == 1
    assert officer_stats["overdue"] == 1
    district_stats = call(api, "GET", "/cmo/statistics/districts")
    assert len(district_stats) == 14
    assert sum(x["total"] for x in district_stats) == 2
    ernakulam = next(x for x in district_stats if x["district"] == "Ernakulam")
    assert ernakulam["overdue"] == 1
    deadline = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    for _ in range(2):
        escalated = call(
            api,
            "POST",
            f"/cmo/grievances/{gid}/escalate",
            {
                "reason": "Fictional overdue escalation reason",
                "priority": "HIGH",
                "new_deadline": deadline,
            },
            status=201,
        )
    assert len(escalated["escalations"]) == 2
    assert len(escalated["history"]) == 3
    assert escalated["escalations"][0]["previous_priority"] == "MEDIUM"
    assert not escalated["overdue"]
    call(
        api,
        "POST",
        f"/cmo/grievances/{gid}/escalate",
        {"reason": "Must not downgrade priority", "priority": "LOW"},
        status=409,
    )
    call(
        api,
        "POST",
        f"/cmo/grievances/{gid}/escalate",
        {"reason": "Must not set past deadline", "new_deadline": "2020-01-01T00:00:00Z"},
        status=422,
    )
    changed = call(
        api,
        "PATCH",
        f"/cmo/grievances/{gid}/priority",
        {"priority": "LOW", "reason": "Fictional de-escalation approved."},
    )
    assert len(changed["history"]) == 3
    assert changed["priority"] == "LOW"
    assign(api, gid, reassign=True, department_id=str(api.health_id))
    departments = call(api, "GET", "/cmo/statistics/departments")
    assert sum(x["total"] for x in departments) == 2
    assert next(x for x in departments if x["department_id"] is None)["total"] == 1
    assert (
        next(x for x in departments if x["department_id"] == str(api.department_id))["total"] == 0
    )
    assert next(x for x in departments if x["department_id"] == str(api.health_id))["total"] == 1
    report1 = report(api, gid, who="outsider")
    assert (
        call(api, "GET", "/officer/dashboard/stats", who="outsider")["reports_pending_review"] == 1
    )
    review_report(api, report1["id"])
    call(
        api,
        "POST",
        f"/cmo/grievances/{gid}/escalate",
        {"reason": "Already resolved cannot escalate"},
        status=409,
    )
    assert call(api, "GET", "/officer/dashboard/stats", who="outsider")["total"] == 0
    assert call(api, "GET", "/cmo/dashboard/stats")["resolved"] == 1
    assert unassigned["status"] == "SUBMITTED"


def test_list_filters_and_reports(api):
    gid, _ = begin(api, designated=True)
    other = create(api, district="Kollam", subject="Another fictional concern")
    r = report(api, gid)
    for params in (
        {"status": "IN_PROGRESS"},
        {"priority": "MEDIUM", "district": "Ernakulam"},
        {"department_id": str(api.department_id)},
        {"reference": gid[:0] + "CMK-"},
        {"subject": "Damaged fictional"},
        {"created_from": "2000-01-01T00:00:00Z"},
    ):
        result = call(api, "GET", "/cmo/grievances", params=params)
        assert gid in [x["id"] for x in result["items"]]
    assert call(api, "GET", "/cmo/grievances", params={"subject": "%"})["items"] == []
    assert call(api, "GET", "/cmo/grievances", params={"page": 9})["items"] == []
    first = call(api, "GET", "/cmo/grievances", params={"page_size": 1, "sort_order": "asc"})
    second = call(
        api, "GET", "/cmo/grievances", params={"page_size": 1, "page": 2, "sort_order": "asc"}
    )
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert first["pagination"]["total_items"] == 2
    for path in ("/officer/grievances", "/officer/grievances/assigned-to-me"):
        mine = call(api, "GET", path, who="officer")
        assert [x["id"] for x in mine["items"]] == [gid]
        assert other["id"] not in str(mine)
    assert call(api, "GET", "/officer/grievances/assigned-to-me", who="colleague")["items"] == []
    assert (
        call(
            api, "GET", "/officer/grievances", who="officer", params={"unassigned_to_officer": True}
        )["items"]
        == []
    )
    listed = call(
        api,
        "GET",
        "/cmo/reports",
        params={"review_status": "PENDING", "department_id": str(api.department_id)},
    )
    assert listed["items"][0]["id"] == r["id"]
    assert (
        call(api, "GET", "/cmo/reports", params={"department_id": str(api.health_id)})["items"]
        == []
    )


@pytest.mark.parametrize(
    "params",
    [
        {"sort_by": "password_hash"},
        {"page_size": 101},
        {"status": "ASSIGNED"},
        {"created_from": "2026-01-01"},
        {"created_from": "2030-01-01T00:00:00Z", "created_to": "2020-01-01T00:00:00Z"},
        {"assigned_to_me": True, "unassigned_to_officer": True},
        {"unexpected": "field"},
    ],
)
def test_validation(api, params):
    call(api, "GET", "/cmo/grievances", params=params, status=422)


def test_audit_failure_rolls_back_status_and_assignment(api, monkeypatch):
    row = create(api)
    gid = row["id"]
    call(api, "PATCH", f"/cmo/grievances/{gid}/review", {})
    original = workflow.transition

    def fail_after_transition(*args, **kwargs):
        original(*args, **kwargs)
        args[0].flush()
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(workflow, "transition", fail_after_transition)
    call(
        api,
        "POST",
        f"/cmo/grievances/{gid}/assign",
        {"department_id": str(api.department_id), "assignment_note": "Must fully roll back."},
        status=500,
    )
    after = call(api, "GET", f"/cmo/grievances/{gid}")
    assert after["status"] == "UNDER_REVIEW"
    assert len(after["history"]) == 2 and after["assignments"] == []


def test_database_constraints_and_escalation_immutability(api):
    gid, result = begin(api)
    report(api, gid)
    with api.db() as db:
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(
                    DepartmentAssignment(
                        grievance_id=UUID(gid),
                        department_id=api.department_id,
                        assigned_by=api.users["cmo"],
                    )
                )
                db.flush()
        existing = db.scalar(
            select(ActionTakenReport).where(ActionTakenReport.grievance_id == UUID(gid))
        )
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(
                    ActionTakenReport(
                        grievance_id=UUID(gid),
                        assignment_id=existing.assignment_id,
                        submitted_by=api.users["officer"],
                        report_details="Duplicate pending fictional report",
                    )
                )
                db.flush()
    call(
        api,
        "POST",
        f"/cmo/grievances/{gid}/escalate",
        {"reason": "Fictional escalation preserved"},
        status=201,
    )
    with api.db() as db:
        from sqlalchemy.exc import DBAPIError

        with pytest.raises(DBAPIError):
            with db.begin_nested():
                db.execute(text("UPDATE grievance_escalations SET reason = 'changed'"))
        assert db.scalar(select(func.count()).select_from(GrievanceEscalation)) == 1
    assert result["status"] == "IN_PROGRESS"


def test_revoked_session_and_no_cache(api):
    api.headers("cmo")
    token = api.tokens["cmo"]
    headers = {**api.headers("cmo"), "X-CSRF-Token": token["csrf_token"]}
    assert api.client.post(P + "/auth/logout", headers=headers).status_code == 204
    for path in ("/cmo/dashboard/stats", "/cmo/grievances", "/cmo/statistics/districts"):
        response = api.client.get(P + path, headers=api.headers("cmo"))
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
    assert api.client.get(P + "/officer/grievances").status_code == 401


def test_detail_query_count_bounded(api):
    gid, _ = begin(api)
    for index in range(5):
        call(
            api,
            "POST",
            f"/officer/grievances/{gid}/updates",
            {"message": f"Fictional update number {index}"},
            who="officer",
            status=201,
        )
    queries = []

    def track(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(api.connection, "before_cursor_execute", track)
    try:
        call(api, "GET", f"/cmo/grievances/{gid}")
    finally:
        event.remove(api.connection, "before_cursor_execute", track)
    assert len(queries) <= 12


def test_public_history_and_review_rollback(api, monkeypatch):
    row = create(api)
    gid = row["id"]
    call(
        api,
        "PATCH",
        f"/cmo/grievances/{gid}/review",
        {"remarks": "Public review acknowledgement", "visibility": "PUBLIC"},
    )
    assert "Public review acknowledgement" in str(
        call(api, "GET", f"/grievances/{gid}/history", who="citizen")
    )
    assign(api, gid)
    pending = report(api, gid)
    original = workflow.transition

    def fail_resolution(*args, **kwargs):
        original(*args, **kwargs)
        args[0].flush()
        raise RuntimeError("Synthetic resolution failure")

    monkeypatch.setattr(workflow, "transition", fail_resolution)
    review_report(api, pending["id"], status=500)
    after = call(api, "GET", f"/cmo/grievances/{gid}")
    assert after["status"] == "IN_PROGRESS"
    assert after["reports"][0]["review_status"] == "PENDING"
    assert after["reports"][0]["reviewed_at"] is None
    assert after["current_assignment"]["closed_at"] is None
    assert len(after["history"]) == 3
    monkeypatch.setattr(workflow, "transition", original)
    review_report(api, pending["id"])
    with api.db() as db:
        db.get(Grievance, UUID(gid)).due_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    stats = call(api, "GET", "/cmo/dashboard/stats")
    assert stats["overdue"] == 0 and stats["resolved"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"report_details": "too short"},
        {"report_details": "x" * 20001},
        {"report_details": "Valid fictional report with forbidden field", "status": "RESOLVED"},
    ],
)
def test_report_input_validation(api, payload):
    gid, _ = begin(api)
    call(api, "POST", f"/officer/grievances/{gid}/reports", payload, who="officer", status=422)


def test_transition_service_cannot_resolve_without_report(api):
    gid, _ = begin(api)
    with api.db() as db:
        admin = db.get(User, api.users["cmo"])
        row = workflow.lock_grievance(db, UUID(gid))
        with pytest.raises(workflow.WorkflowConflict):
            workflow.transition(db, row, workflow.Status.RESOLVED, admin)
        assert row.status == workflow.Status.IN_PROGRESS
