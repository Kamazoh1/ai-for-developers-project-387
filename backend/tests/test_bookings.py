"""Seam 1: booking a slot over HTTP, with "now" fixed by the test."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ClientFactory

MSK = timezone(timedelta(hours=3))
# Thursday 5 November 2026, 10:00 in Moscow.
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=MSK)


def create_type(client: TestClient, minutes: int, slug: str = "call") -> str:
    body = {"id": slug, "name": "Звонок", "durationMinutes": minutes}
    assert client.post("/api/admin/event-types", json=body).status_code == 201
    return slug


def book(client: TestClient, slug: str, start: str, **overrides: object):
    body = {
        "eventTypeId": slug,
        "start": start,
        "guestName": "Мария",
        "guestEmail": "maria@example.com",
    }
    return client.post("/api/bookings", json={**body, **overrides})


def free_starts(client: TestClient, slug: str, date: str) -> list[str]:
    """Local start times of the free slots of one day, e.g. ``["09:00", "09:30"]``."""
    days = client.get(f"/api/event-types/{slug}/slots").json()["days"]
    (day,) = [day for day in days if day["date"] == date]
    return [slot["start"][11:16] for slot in day["slots"]]


def test_booking_a_free_slot_returns_the_booking_with_the_end_computed_by_the_server(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 45)

    response = book(client, slug, "2026-11-06T10:00:00+03:00")

    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "eventTypeId": "call",
        "start": "2026-11-06T10:00:00+03:00",
        "end": "2026-11-06T10:45:00+03:00",
        "guestName": "Мария",
        "guestEmail": "maria@example.com",
        "topic": "",
        "createdAt": "2026-11-05T10:00:00+03:00",
    }


def test_a_topic_is_optional_trimmed_and_returned(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    with_topic = book(client, slug, "2026-11-06T10:00:00+03:00", topic="  Обсудить релиз  ")
    blank = book(client, slug, "2026-11-06T11:00:00+03:00", topic="   ")

    assert with_topic.status_code == 201
    assert with_topic.json()["topic"] == "Обсудить релиз"
    assert blank.status_code == 201
    assert blank.json()["topic"] == ""


def test_a_topic_may_have_500_characters_but_not_501(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    ok = book(client, slug, "2026-11-06T10:00:00+03:00", topic="т" * 500)
    too_long = book(client, slug, "2026-11-06T11:00:00+03:00", topic="т" * 501)

    assert ok.status_code == 201
    assert too_long.status_code == 422
    assert too_long.json()["code"] == "validation_error"
    assert [f["field"] for f in too_long.json()["fields"]] == ["topic"]
    assert "11:00" in free_starts(client, slug, "2026-11-06")


def test_a_conflicting_booking_with_a_topic_is_refused_and_its_topic_is_not_kept(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)
    assert book(client, slug, "2026-11-06T10:00:00+03:00", topic="Первая").status_code == 201

    refused = book(client, slug, "2026-11-06T10:00:00+03:00", topic="Вторая")

    assert refused.status_code == 409
    assert refused.json()["code"] == "slot_taken"
    listed = client.get("/api/admin/bookings").json()
    assert [b["topic"] for b in listed] == ["Первая"]


def test_a_booked_interval_disappears_from_the_slots_at_once(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)
    assert "10:00" in free_starts(client, slug, "2026-11-06")

    book(client, slug, "2026-11-06T10:00:00+03:00")

    starts = free_starts(client, slug, "2026-11-06")
    assert "10:00" not in starts
    assert "09:30" in starts
    assert "10:30" in starts


def test_a_booking_blocks_overlapping_intervals_of_any_type_but_not_the_adjacent_ones(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    hour = create_type(client, 60, "hour")
    half = create_type(client, 30, "half")
    assert book(client, hour, "2026-11-06T10:00:00+03:00").status_code == 201

    # Of the other type, 10:00 and 10:30 lie inside 10:00-11:00; 09:30 and 11:00 only touch it.
    starts = free_starts(client, half, "2026-11-06")
    assert "09:30" in starts
    assert "10:00" not in starts
    assert "10:30" not in starts
    assert "11:00" in starts

    for taken in ("2026-11-06T10:00:00+03:00", "2026-11-06T10:30:00+03:00"):
        conflict = book(client, half, taken)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "slot_taken"
    assert book(client, half, "2026-11-06T11:00:00+03:00").status_code == 201
    assert book(client, half, "2026-11-06T09:30:00+03:00").status_code == 201


def test_a_longer_booking_that_contains_a_booked_interval_is_taken(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    hour = create_type(client, 60, "hour")
    half = create_type(client, 30, "half")
    assert book(client, half, "2026-11-06T10:30:00+03:00").status_code == 201

    # 10:00-11:00 contains the booked 10:30-11:00.
    assert book(client, hour, "2026-11-06T10:00:00+03:00").status_code == 409


def test_the_same_guest_cannot_double_book_either(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)
    assert book(client, slug, "2026-11-06T10:00:00+03:00").status_code == 201

    again = book(client, slug, "2026-11-06T10:00:00+03:00")

    assert again.status_code == 409
    assert again.json()["code"] == "slot_taken"


def test_the_start_may_be_given_in_any_offset_and_is_compared_as_an_instant(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    response = book(client, slug, "2026-11-06T07:00:00Z")  # 10:00 in Moscow

    assert response.status_code == 201
    assert response.json()["start"] == "2026-11-06T10:00:00+03:00"
    assert book(client, slug, "2026-11-06T10:00:00+03:00").status_code == 409


def test_bookings_are_kept_between_server_restarts(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    path = tmp_path / "shared.db"
    first = make_client(now=NOW, database_path=path)
    slug = create_type(first, 30)
    assert book(first, slug, "2026-11-06T10:00:00+03:00").status_code == 201

    second = make_client(now=NOW, database_path=path)

    assert "10:00" not in free_starts(second, slug, "2026-11-06")
    assert book(second, slug, "2026-11-06T10:00:00+03:00").status_code == 409


@pytest.mark.parametrize(
    ("why", "start"),
    [
        ("off the 30-minute grid", "2026-11-06T10:15:00+03:00"),
        ("with seconds", "2026-11-06T10:00:30+03:00"),
        ("before working hours", "2026-11-06T08:30:00+03:00"),
        ("at closing time", "2026-11-06T18:00:00+03:00"),
        ("running past closing time", "2026-11-06T17:30:00+03:00"),  # 60 minutes
        ("on the 15th day, outside the window", "2026-11-19T10:00:00+03:00"),
        ("in the past", "2026-11-04T10:00:00+03:00"),
        ("at exactly now", "2026-11-05T10:00:00+03:00"),
        ("already started today", "2026-11-05T09:30:00+03:00"),
    ],
)
def test_a_start_that_is_not_a_slot_is_rejected(
    make_client: ClientFactory, why: str, start: str
) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 60)

    response = book(client, slug, start)

    assert response.status_code == 422, why
    assert response.json()["code"] == "invalid_slot"


def test_the_last_day_of_the_window_can_be_booked(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    assert book(client, slug, "2026-11-18T10:00:00+03:00").status_code == 201


def test_an_unknown_event_type_is_an_invalid_slot(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)

    response = book(client, "nope", "2026-11-06T10:00:00+03:00")

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_slot"


def test_an_invalid_and_taken_slot_at_once_is_invalid_not_taken(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    path = tmp_path / "shared.db"
    earlier = make_client(now=NOW, database_path=path)
    slug = create_type(earlier, 30)
    assert book(earlier, slug, "2026-11-05T11:00:00+03:00").status_code == 201

    # Later the same day the booked slot has started, and is still booked.
    later = make_client(now=datetime(2026, 11, 5, 12, 0, tzinfo=MSK), database_path=path)
    response = book(later, slug, "2026-11-05T11:00:00+03:00")

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_slot"


def test_names_and_emails_are_trimmed(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    response = book(
        client,
        slug,
        "2026-11-06T10:00:00+03:00",
        guestName="  Мария  ",
        guestEmail="  maria@example.com ",
    )

    assert response.status_code == 201
    assert response.json()["guestName"] == "Мария"
    assert response.json()["guestEmail"] == "maria@example.com"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("guestName", ""),
        ("guestName", "   "),
        ("guestName", "я" * 101),
        ("guestEmail", ""),
        ("guestEmail", "   "),
        ("guestEmail", "not-an-email"),
        ("guestEmail", "a@b"),
        ("guestEmail", "two words@example.com"),
        ("guestEmail", "a" * 40 + "@example.com"),  # 52 characters
        ("guestEmail", 42),
    ],
)
def test_invalid_guest_details_name_the_field(
    make_client: ClientFactory, field: str, value: object
) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    response = book(client, slug, "2026-11-06T10:00:00+03:00", **{field: value})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert [error["field"] for error in body["fields"]] == [field]
    assert "10:00" in free_starts(client, slug, "2026-11-06")


def test_the_limits_of_guest_details_are_accepted(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    response = book(
        client,
        slug,
        "2026-11-06T10:00:00+03:00",
        guestName="я" * 100,
        guestEmail="a" * 38 + "@example.com",  # 50 characters
    )

    assert response.status_code == 201


def test_validation_comes_before_the_slot_check(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)

    response = book(client, "nope", "2026-11-06T10:15:00+03:00", guestEmail="bad")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_a_start_without_an_offset_is_a_validation_error(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    response = book(client, slug, "2026-11-06T10:00:00")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["fields"][0]["field"] == "start"


def test_a_numeric_unix_timestamp_is_not_an_rfc_3339_start(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)

    for start in (1793000000, 1793000000.0, "1793000000"):
        body = {"eventTypeId": slug, "start": start, "guestName": "Мария"}
        response = client.post("/api/bookings", json={**body, "guestEmail": "maria@example.com"})

        assert response.status_code == 422, start
        assert response.json()["code"] == "validation_error"
        assert response.json()["fields"][0]["field"] == "start"


def test_a_failure_that_already_ended_the_transaction_is_not_masked_by_the_rollback(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    path = tmp_path / "shared.db"
    client = make_client(now=NOW, database_path=path)
    slug = create_type(client, 30)
    other = sqlite3.connect(path, isolation_level=None)
    # SQLite itself ends the transaction when the insert fails, as it can on a full disk.
    other.execute(
        "CREATE TRIGGER fail_insert BEFORE INSERT ON bookings "
        "BEGIN SELECT RAISE(ROLLBACK, 'insert failed'); END"
    )
    other.close()

    with pytest.raises(sqlite3.IntegrityError, match="insert failed"):
        book(client, slug, "2026-11-06T10:00:00+03:00")
