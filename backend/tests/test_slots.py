"""Seam 1: the slots of an event type over HTTP, with "now" fixed by the test."""

from datetime import UTC, datetime, timedelta, timezone

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


def slots_of(client: TestClient, slug: str) -> list[dict]:
    response = client.get(f"/api/event-types/{slug}/slots")
    assert response.status_code == 200
    return response.json()["days"]


def starts(day: dict) -> list[str]:
    """Local start times of a day's slots, e.g. ``["09:00", "09:30"]``."""
    return [slot["start"][11:16] for slot in day["slots"]]


def test_unknown_event_type_is_not_found(client: TestClient) -> None:
    response = client.get("/api/event-types/nope/slots")

    assert response.status_code == 404
    assert response.json()["code"] == "event_type_not_found"


def test_window_has_fourteen_days_starting_today_including_empty_ones(
    make_client: ClientFactory,
) -> None:
    # 17:45 is too late for any 30-minute slot today: the day is listed, but empty.
    client = make_client(now=datetime(2026, 11, 5, 17, 45, tzinfo=MSK))
    days = slots_of(client, create_type(client, 30))

    assert [day["date"] for day in days] == [
        "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09",
        "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14",
        "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18",
    ]  # fmt: skip
    assert days[0]["slots"] == []
    assert days[1]["slots"] != []


def test_a_whole_day_of_thirty_minute_slots_on_the_grid(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    tomorrow = slots_of(client, create_type(client, 30))[1]

    assert starts(tomorrow) == [
        f"{hour:02d}:{minute:02d}" for hour in range(9, 18) for minute in (0, 30)
    ]
    assert tomorrow["slots"][0] == {
        "start": "2026-11-06T09:00:00+03:00",
        "end": "2026-11-06T09:30:00+03:00",
    }
    assert tomorrow["slots"][-1] == {
        "start": "2026-11-06T17:30:00+03:00",
        "end": "2026-11-06T18:00:00+03:00",
    }


def test_weekends_have_working_hours_too(make_client: ClientFactory) -> None:
    client = make_client(now=NOW)
    days = slots_of(client, create_type(client, 60))

    saturday, sunday = days[2], days[3]
    assert (saturday["date"], sunday["date"]) == ("2026-11-07", "2026-11-08")
    assert starts(saturday)[0] == "09:00"
    assert starts(sunday)[0] == "09:00"


@pytest.mark.parametrize(
    ("minutes", "last_start"),
    [
        (15, "17:30"),  # 17:30-17:45
        (60, "17:00"),  # 17:00-18:00 fits, 17:30-18:30 does not
        (45, "17:00"),  # 17:00-17:45 fits, 17:30-18:15 does not
        (90, "16:30"),
        (480, "10:00"),  # 10:00-18:00 is the last that fits
    ],
)
def test_slot_is_as_long_as_the_type_and_never_ends_after_18(
    make_client: ClientFactory, minutes: int, last_start: str
) -> None:
    client = make_client(now=NOW)
    tomorrow = slots_of(client, create_type(client, minutes))[1]

    assert starts(tomorrow)[0] == "09:00"
    assert starts(tomorrow)[-1] == last_start
    for slot in tomorrow["slots"]:
        length = datetime.fromisoformat(slot["end"]) - datetime.fromisoformat(slot["start"])
        assert length == timedelta(minutes=minutes)
        assert slot["end"][11:16] <= "18:00"


@pytest.mark.parametrize(
    ("now", "first_today"),
    [
        (datetime(2026, 11, 5, 8, 0, tzinfo=MSK), "09:00"),  # before working hours
        (datetime(2026, 11, 5, 10, 0, tzinfo=MSK), "10:30"),  # starting exactly now is not allowed
        (datetime(2026, 11, 5, 10, 1, tzinfo=MSK), "10:30"),
        (datetime(2026, 11, 5, 9, 59, 59, tzinfo=MSK), "10:00"),
        (datetime(2026, 11, 5, 17, 0, tzinfo=MSK), "17:30"),
    ],
)
def test_today_shows_only_slots_starting_strictly_after_now(
    make_client: ClientFactory, now: datetime, first_today: str
) -> None:
    client = make_client(now=now)
    today = slots_of(client, create_type(client, 30))[0]

    assert starts(today)[0] == first_today
    assert starts(today)[-1] == "17:30"


def test_the_window_follows_the_calendar_timezone(make_client: ClientFactory) -> None:
    # 20:00 UTC on 5 November is already 6 November 05:00 in Tokyo.
    client = make_client(
        calendar_timezone="Asia/Tokyo", now=datetime(2026, 11, 5, 20, 0, tzinfo=UTC)
    )
    days = slots_of(client, create_type(client, 30))

    assert days[0]["date"] == "2026-11-06"
    assert days[-1]["date"] == "2026-11-19"
    assert days[0]["slots"][0]["start"] == "2026-11-06T09:00:00+09:00"


def test_offsets_follow_daylight_saving_changes(make_client: ClientFactory) -> None:
    # New York leaves daylight saving on Sunday 1 November 2026: -04:00 before, -05:00 after.
    client = make_client(
        calendar_timezone="America/New_York", now=datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    )
    days = slots_of(client, create_type(client, 60))

    by_date = {day["date"]: day for day in days}
    assert by_date["2026-10-31"]["slots"][0]["start"] == "2026-10-31T09:00:00-04:00"
    assert by_date["2026-11-01"]["slots"][0]["start"] == "2026-11-01T09:00:00-05:00"
    assert by_date["2026-11-01"]["slots"][-1]["end"] == "2026-11-01T18:00:00-05:00"


def test_without_a_fixed_clock_the_real_time_is_used(client: TestClient) -> None:
    days = slots_of(client, create_type(client, 30))

    assert len(days) == 14
