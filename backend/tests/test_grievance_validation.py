import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import create_app
from app.modules.grievances.choices import Category, District
from app.modules.grievances.schemas import GrievanceCreate, GrievanceListQuery


def payload(**changes):
    return {
        "district": "Ernakulam",
        "category": "Roads and Infrastructure",
        "subject": "Fictional damaged road",
        "description": "A fictional road needs repair near the community hospital.",
        **changes,
    }


@pytest.mark.parametrize("district", list(District))
def test_all_districts_are_canonicalized(district):
    data = GrievanceCreate(**payload(district="  " + district.value.swapcase() + "  "))
    assert data.district is district


@pytest.mark.parametrize("category", list(Category))
def test_all_categories_are_canonicalized(category):
    data = GrievanceCreate(
        **payload(category="  " + "  ".join(category.value.lower().split()) + " ")
    )
    assert data.category is category


@pytest.mark.parametrize(
    "changes",
    [
        {"district": ""},
        {"district": "Trivandrum"},
        {"district": "   "},
        {"district": 12},
        {"category": "Undefined category"},
        {"category": "  "},
        {"subject": " tiny "},
        {"subject": " " * 10},
        {"subject": "x" * 256},
        {"subject": "\x00invalid"},
        {"description": "short"},
        {"description": " " * 30},
        {"description": "x" * 10001},
        {"description": "description with null\x00character"},
        {"description": None},
    ],
)
def test_submission_validation(changes):
    with pytest.raises(ValueError):
        GrievanceCreate(**payload(**changes))


def test_text_lengths_are_checked_after_trimming_without_truncation():
    data = GrievanceCreate(
        **payload(subject=" " + "s" * 255 + " ", description="\n" + "d" * 10000 + "\n")
    )
    assert data.subject == "s" * 255
    assert data.description == "d" * 10000
    assert len(District) == 14 and len(Category) == 12


@pytest.mark.parametrize(
    "changes",
    [
        {"page": 0},
        {"page": 1000001},
        {"page_size": 0},
        {"page_size": 101},
        {"sort_by": "subject"},
        {"sort_order": "sideways"},
        {"status": "UNKNOWN"},
        {"citizen_id": "another citizen"},
    ],
)
def test_list_query_is_bounded_and_allowlisted(changes):
    with pytest.raises(ValueError):
        GrievanceListQuery(**changes)


def test_database_operational_failure_is_sanitized():
    class Unavailable:
        def scalars(self, *args, **kwargs):
            raise OperationalError(
                "SQL containing sensitive values",
                {},
                Exception("connection password should not leak"),
            )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: Unavailable()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/departments")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
