"""Seam 1: concurrent bookings over HTTP on a file-based SQLite database (ADR 0002).

Requests really run in parallel threads against the real app; a barrier releases them together.
Several rounds on different slots make a missing write lock show up reliably: with a plain
``BEGIN`` or autocommit the check-then-insert race lets two requests through, or a lock upgrade
fails with a 500.
"""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import ClientFactory

MSK = timezone(timedelta(hours=3))
# Thursday 5 November 2026, 10:00 in Moscow.
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=MSK)
ROUNDS = 8
PARALLEL = 10


def create_type(client: TestClient, minutes: int, slug: str) -> str:
    body = {"id": slug, "name": "Звонок", "durationMinutes": minutes}
    assert client.post("/api/admin/event-types", json=body).status_code == 201
    return slug


def booking_body(slug: str, start: str, guest: int = 0) -> dict[str, str]:
    return {
        "eventTypeId": slug,
        "start": start,
        "guestName": f"Гость {guest}",
        "guestEmail": f"guest{guest}@example.com",
    }


def post_in_parallel(client: TestClient, bodies: list[dict[str, str]]) -> list[int]:
    """Status codes of all bookings, sent at the same moment from separate threads."""
    barrier = threading.Barrier(len(bodies))

    def send(body: dict[str, str]) -> int:
        barrier.wait()
        return client.post("/api/bookings", json=body).status_code

    with ThreadPoolExecutor(max_workers=len(bodies)) as pool:
        return list(pool.map(send, bodies))


def day(round_number: int) -> str:
    return f"2026-11-{6 + round_number:02d}"


def test_ten_parallel_requests_for_one_slot_give_one_created_and_nine_slot_taken(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30, "call")

    for round_number in range(ROUNDS):
        start = f"{day(round_number)}T10:00:00+03:00"
        statuses = post_in_parallel(
            client, [booking_body(slug, start, guest) for guest in range(PARALLEL)]
        )

        assert sorted(statuses) == [201] + [409] * 9, f"round {round_number}"


def test_parallel_requests_for_overlapping_intervals_of_different_types_give_one_booking(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    hour = create_type(client, 60, "hour")
    half = create_type(client, 30, "half")

    for round_number in range(ROUNDS):
        # 10:00-11:00 against 10:30-11:00, several guests each.
        bodies = [booking_body(hour, f"{day(round_number)}T10:00:00+03:00", g) for g in range(5)]
        bodies += [booking_body(half, f"{day(round_number)}T10:30:00+03:00", g) for g in range(5)]

        statuses = post_in_parallel(client, bodies)

        assert sorted(statuses) == [201] + [409] * 9, f"round {round_number}"


def test_parallel_requests_for_adjacent_intervals_both_succeed(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    hour = create_type(client, 60, "hour")
    half = create_type(client, 30, "half")

    for round_number in range(ROUNDS):
        # 10:00-11:00 and 11:00-11:30 touch but do not overlap.
        bodies = [
            booking_body(hour, f"{day(round_number)}T10:00:00+03:00"),
            booking_body(half, f"{day(round_number)}T11:00:00+03:00"),
        ]

        assert post_in_parallel(client, bodies) == [201, 201], f"round {round_number}"


def test_a_booking_waits_for_the_write_lock_of_another_connection_and_then_succeeds(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    database = tmp_path / "shared.db"
    client = make_client(now=NOW, database_path=database, lock_timeout_seconds=10)
    slug = create_type(client, 30, "call")
    other = sqlite3.connect(database, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")  # another server process is writing
    threading.Timer(0.3, lambda: other.execute("COMMIT")).start()

    response = client.post("/api/bookings", json=booking_body(slug, "2026-11-06T10:00:00+03:00"))

    assert response.status_code == 201
    other.close()


def test_a_booking_that_cannot_get_the_write_lock_in_time_gets_503_service_busy(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    database = tmp_path / "shared.db"
    client = make_client(now=NOW, database_path=database, lock_timeout_seconds=0.2)
    slug = create_type(client, 30, "call")
    other = sqlite3.connect(database, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")  # another server process holds the write lock

    busy = client.post("/api/bookings", json=booking_body(slug, "2026-11-06T10:00:00+03:00"))

    assert busy.status_code == 503
    assert busy.json()["code"] == "service_busy"
    other.execute("ROLLBACK")
    other.close()
    # Nothing was written, and the guest can simply try again.
    retry = client.post("/api/bookings", json=booking_body(slug, "2026-11-06T10:00:00+03:00"))
    assert retry.status_code == 201


def test_a_slot_that_started_while_waiting_for_the_write_lock_is_rejected_as_invalid(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    database = tmp_path / "shared.db"
    clock = {"now": NOW}
    client = make_client(now=lambda: clock["now"], database_path=database, lock_timeout_seconds=10)
    slug = create_type(client, 30, "call")
    other = sqlite3.connect(database, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")  # another server process is writing

    def release_after_the_slot_has_started() -> None:
        clock["now"] = datetime(2026, 11, 5, 10, 45, tzinfo=MSK)
        other.execute("COMMIT")

    threading.Timer(0.3, release_after_the_slot_has_started).start()

    # Valid at 10:00 when the request arrives, already started at 10:45 when the lock is free.
    response = client.post("/api/bookings", json=booking_body(slug, "2026-11-05T10:30:00+03:00"))

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_slot"
    other.close()
    assert client.get("/api/admin/bookings").json() == []


def test_created_at_is_the_time_the_booking_was_written_not_the_time_the_request_arrived(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    database = tmp_path / "shared.db"
    clock = {"now": NOW}
    client = make_client(now=lambda: clock["now"], database_path=database, lock_timeout_seconds=10)
    slug = create_type(client, 30, "call")
    other = sqlite3.connect(database, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")

    def release_later() -> None:
        clock["now"] = datetime(2026, 11, 5, 10, 20, tzinfo=MSK)
        other.execute("COMMIT")

    threading.Timer(0.3, release_later).start()

    response = client.post("/api/bookings", json=booking_body(slug, "2026-11-06T10:00:00+03:00"))

    assert response.status_code == 201
    assert response.json()["createdAt"] == "2026-11-05T10:20:00+03:00"
    other.close()
