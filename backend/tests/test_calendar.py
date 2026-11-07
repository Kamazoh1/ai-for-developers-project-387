import pytest
from fastapi.testclient import TestClient

from tests.conftest import ClientFactory


def test_calendar_defaults(client: TestClient) -> None:
    response = client.get("/api/calendar")

    assert response.status_code == 200
    assert response.json() == {
        "timezone": "Europe/Moscow",
        "workingHours": {"start": "09:00:00", "end": "18:00:00"},
        "slotStepMinutes": 30,
        "bookingWindowDays": 14,
        "owner": {"name": "Алексей Иванов"},
    }


def test_calendar_timezone_comes_from_environment(make_client: ClientFactory) -> None:
    client = make_client(calendar_timezone="Asia/Tokyo")

    assert client.get("/api/calendar").json()["timezone"] == "Asia/Tokyo"


@pytest.mark.parametrize("bad_zone", ["Mars/Olympus", "", "not a zone"])
def test_invalid_timezone_stops_startup_with_a_clear_error(
    make_client: ClientFactory, bad_zone: str
) -> None:
    with pytest.raises(Exception, match="CALENDAR_TIMEZONE"):
        make_client(calendar_timezone=bad_zone)
