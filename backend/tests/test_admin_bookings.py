"""Seam 1: the owner's list of upcoming bookings over HTTP, with "now" fixed by the test."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.conftest import ClientFactory
from tests.test_bookings import book, create_type

MSK = timezone(timedelta(hours=3))
# Thursday 5 November 2026, 10:00 in Moscow.
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=MSK)


def test_there_are_no_upcoming_bookings_before_anyone_books(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)

    response = client.get("/api/admin/bookings")

    assert response.status_code == 200
    assert response.json() == []


def test_upcoming_bookings_of_all_types_come_in_ascending_start_order(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    short = create_type(client, 30, "short")
    long = create_type(client, 60, "long")
    # Booked out of order, and across two types.
    book(client, long, "2026-11-07T15:00:00+03:00", guestName="Борис")
    book(client, short, "2026-11-06T09:00:00+03:00", guestName="Анна")
    book(client, short, "2026-11-06T13:30:00+03:00", guestName="Вера")

    response = client.get("/api/admin/bookings")

    assert response.status_code == 200
    assert [(b["start"], b["end"], b["eventTypeId"], b["guestName"]) for b in response.json()] == [
        ("2026-11-06T09:00:00+03:00", "2026-11-06T09:30:00+03:00", "short", "Анна"),
        ("2026-11-06T13:30:00+03:00", "2026-11-06T14:00:00+03:00", "short", "Вера"),
        ("2026-11-07T15:00:00+03:00", "2026-11-07T16:00:00+03:00", "long", "Борис"),
    ]


def test_a_booking_is_listed_with_every_field_of_the_contract(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 45)
    book(client, slug, "2026-11-06T10:00:00+03:00")

    assert client.get("/api/admin/bookings").json() == [
        {
            "id": 1,
            "eventTypeId": "call",
            "start": "2026-11-06T10:00:00+03:00",
            "end": "2026-11-06T10:45:00+03:00",
            "guestName": "Мария",
            "guestEmail": "maria@example.com",
            "topic": "",
            "createdAt": "2026-11-05T10:00:00+03:00",
        }
    ]


def test_the_owner_sees_the_topic_only_where_the_guest_left_one(
    make_client: ClientFactory,
) -> None:
    client = make_client(now=NOW)
    slug = create_type(client, 30)
    book(client, slug, "2026-11-06T09:00:00+03:00", topic="Про релиз")
    book(client, slug, "2026-11-06T10:00:00+03:00")

    listed = client.get("/api/admin/bookings").json()

    assert [b["topic"] for b in listed] == ["Про релиз", ""]


def test_a_database_from_before_topics_opens_and_lists_its_bookings_without_a_topic(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    old = tmp_path / "old.db"
    with closing(sqlite3.connect(old)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE event_types (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                description TEXT NOT NULL, duration_minutes INTEGER NOT NULL);
            CREATE TABLE bookings (id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type_id TEXT NOT NULL REFERENCES event_types(id),
                start_utc TEXT NOT NULL, end_utc TEXT NOT NULL, guest_name TEXT NOT NULL,
                guest_email TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO event_types VALUES ('call', 'Звонок', '', 30);
            INSERT INTO bookings VALUES (1, 'call', '2026-11-06T06:00:00Z',
                '2026-11-06T06:30:00Z', 'Мария', 'maria@example.com', '2026-11-05T07:00:00Z');
            """
        )

    client = make_client(now=NOW, database_path=old)
    assert [b["topic"] for b in client.get("/api/admin/bookings").json()] == [""]
    assert book(client, "call", "2026-11-06T10:00:00+03:00", topic="Новая").status_code == 201
    # Opening it a second time must not fail on the column that is already there.
    again = make_client(now=NOW, database_path=old)
    assert [b["topic"] for b in again.get("/api/admin/bookings").json()] == ["", "Новая"]


def test_a_meeting_in_progress_is_still_upcoming_until_it_ends(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    # The app refuses to book in the past, so book on Thursday for Friday 10:00-11:00 and
    # reopen the same database with a clock inside, and exactly at the end of, the meeting.
    first = make_client(now=NOW)
    slug = create_type(first, 60)
    book(first, slug, "2026-11-06T10:00:00+03:00")
    database = tmp_path / "calendar-1.db"

    during = make_client(database_path=database, now=datetime(2026, 11, 6, 10, 30, tzinfo=MSK))
    assert [b["id"] for b in during.get("/api/admin/bookings").json()] == [1]

    at_the_end = make_client(database_path=database, now=datetime(2026, 11, 6, 11, 0, tzinfo=MSK))
    assert at_the_end.get("/api/admin/bookings").json() == []


def test_a_finished_meeting_is_not_listed_but_a_later_one_is(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    first = make_client(now=NOW)
    slug = create_type(first, 30)
    book(first, slug, "2026-11-06T09:00:00+03:00", guestName="Ранняя")
    book(first, slug, "2026-11-06T14:00:00+03:00", guestName="Поздняя")

    later = make_client(
        database_path=tmp_path / "calendar-1.db", now=datetime(2026, 11, 6, 12, 0, tzinfo=MSK)
    )

    assert [b["guestName"] for b in later.get("/api/admin/bookings").json()] == ["Поздняя"]


def test_times_are_in_the_offset_of_the_calendar_timezone(make_client: ClientFactory) -> None:
    client = make_client(calendar_timezone="Asia/Tokyo", now=NOW)
    slug = create_type(client, 30)
    start = client.get(f"/api/event-types/{slug}/slots").json()["days"][1]["slots"][0]["start"]
    assert start.endswith("+09:00")
    book(client, slug, start)

    (listed,) = client.get("/api/admin/bookings").json()

    assert listed["start"] == start
    assert listed["end"].endswith("+09:00")
    assert listed["createdAt"].endswith("+09:00")
