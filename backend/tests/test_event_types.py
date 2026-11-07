import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ClientFactory

INTRO = {
    "id": "intro-call",
    "name": "Знакомство",
    "description": "Короткий созвон",
    "durationMinutes": 15,
}


def test_no_event_types_at_first(client: TestClient) -> None:
    response = client.get("/api/event-types")

    assert response.status_code == 200
    assert response.json() == []


def test_owner_creates_an_event_type_and_guests_see_it(client: TestClient) -> None:
    created = client.post("/api/admin/event-types", json=INTRO)

    assert created.status_code == 201
    assert created.json() == INTRO
    assert client.get("/api/event-types").json() == [INTRO]


def test_event_types_are_listed_in_creation_order(client: TestClient) -> None:
    second = {**INTRO, "id": "a-second", "name": "Второй"}
    client.post("/api/admin/event-types", json=INTRO)
    client.post("/api/admin/event-types", json=second)

    assert [t["id"] for t in client.get("/api/event-types").json()] == ["intro-call", "a-second"]


def test_event_types_survive_a_restart(make_client: ClientFactory, tmp_path: Path) -> None:
    database = tmp_path / "shared.db"
    make_client(database_path=database).post("/api/admin/event-types", json=INTRO)

    restarted = make_client(database_path=database)

    assert restarted.get("/api/event-types").json() == [INTRO]


def test_description_is_optional(client: TestClient) -> None:
    body = {"id": "quick", "name": "Быстрый", "durationMinutes": 5}

    created = client.post("/api/admin/event-types", json=body)

    assert created.status_code == 201
    assert created.json() == {**body, "description": ""}


@pytest.mark.parametrize("slug", ["a", "intro-call", "0-9", "-", "a" * 40, "ab12-cd"])
def test_valid_slugs_are_accepted(client: TestClient, slug: str) -> None:
    assert client.post("/api/admin/event-types", json={**INTRO, "id": slug}).status_code == 201


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"id": ""}, "id"),
        ({"id": "a" * 41}, "id"),
        ({"id": "Intro"}, "id"),
        ({"id": "intro call"}, "id"),
        ({"id": "intro_call"}, "id"),
        ({"id": "intro\n"}, "id"),
        ({"id": "звонок"}, "id"),
        ({"id": 5}, "id"),
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "x" * 101}, "name"),
        ({"description": "x" * 501}, "description"),
        ({"durationMinutes": 0}, "durationMinutes"),
        ({"durationMinutes": 4}, "durationMinutes"),
        ({"durationMinutes": 7}, "durationMinutes"),
        ({"durationMinutes": 485}, "durationMinutes"),
        ({"durationMinutes": -5}, "durationMinutes"),
        ({"durationMinutes": 30.5}, "durationMinutes"),
        ({"durationMinutes": "30"}, "durationMinutes"),
        ({"durationMinutes": True}, "durationMinutes"),
        ({"durationMinutes": None}, "durationMinutes"),
    ],
    ids=lambda value: str(value)[:24],
)
def test_bad_values_are_rejected_with_the_field_named(
    client: TestClient, changes: dict[str, object], field: str
) -> None:
    response = client.post("/api/admin/event-types", json={**INTRO, **changes})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["message"], str)
    assert [f["field"] for f in body["fields"]] == [field]
    assert isinstance(body["fields"][0]["message"], str)
    assert client.get("/api/event-types").json() == []


@pytest.mark.parametrize("duration", [5, 30, 480])
def test_boundary_values_are_accepted(client: TestClient, duration: int) -> None:
    body = {**INTRO, "name": "x" * 100, "description": "y" * 500, "durationMinutes": duration}

    assert client.post("/api/admin/event-types", json=body).status_code == 201


def test_every_bad_field_is_reported(client: TestClient) -> None:
    response = client.post(
        "/api/admin/event-types", json={"id": "BAD", "name": "", "durationMinutes": 7}
    )

    assert response.status_code == 422
    assert sorted(f["field"] for f in response.json()["fields"]) == [
        "durationMinutes",
        "id",
        "name",
    ]


def test_missing_fields_are_named(client: TestClient) -> None:
    response = client.post("/api/admin/event-types", json={})

    assert response.status_code == 422
    assert sorted(f["field"] for f in response.json()["fields"]) == [
        "durationMinutes",
        "id",
        "name",
    ]


@pytest.mark.parametrize("content", ["not json", "[]", "null"])
def test_a_malformed_body_is_a_validation_error(client: TestClient, content: str) -> None:
    response = client.post(
        "/api/admin/event-types", content=content, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["fields"]


def test_a_duplicate_id_is_a_conflict(client: TestClient) -> None:
    client.post("/api/admin/event-types", json=INTRO)

    response = client.post("/api/admin/event-types", json={**INTRO, "name": "Другое"})

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "event_type_exists"
    assert isinstance(body["message"], str)
    assert "fields" not in body
    assert client.get("/api/event-types").json() == [INTRO]


def test_creating_a_type_that_cannot_get_the_write_lock_in_time_gets_503_service_busy(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    database = tmp_path / "shared.db"
    client = make_client(database_path=database, lock_timeout_seconds=0.2)
    other = sqlite3.connect(database, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # another server process holds the write lock

    busy = client.post("/api/admin/event-types", json=INTRO)

    assert busy.status_code == 503
    assert busy.json()["code"] == "service_busy"
    other.execute("ROLLBACK")
    other.close()
    # Nothing was written, and the owner can simply try again.
    assert client.post("/api/admin/event-types", json=INTRO).status_code == 201


def test_guest_opens_one_event_type_by_id(client: TestClient) -> None:
    client.post("/api/admin/event-types", json=INTRO)
    client.post("/api/admin/event-types", json={**INTRO, "id": "other", "name": "Другое"})

    response = client.get("/api/event-types/intro-call")

    assert response.status_code == 200
    assert response.json() == INTRO


@pytest.mark.parametrize("event_type_id", ["missing", "Intro-Call", "intro call", "звонок"])
def test_an_unknown_event_type_is_not_found(client: TestClient, event_type_id: str) -> None:
    client.post("/api/admin/event-types", json=INTRO)

    response = client.get(f"/api/event-types/{event_type_id}")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "event_type_not_found"
    assert isinstance(body["message"], str)
    assert "fields" not in body
