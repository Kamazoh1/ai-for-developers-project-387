"""Seam 2: the pure slot rules. The direct check of one start must agree with the slot list.

``is_slot_start`` is what booking uses to validate a single start; ``window_slots`` is what the
slots endpoint offers. They must accept exactly the same starts, for every duration, around
midnight, in the window's last day and across daylight-saving changes.
"""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.slots import is_slot_start, window_slots

MSK = ZoneInfo("Europe/Moscow")
BERLIN = ZoneInfo("Europe/Berlin")
DURATIONS = [5, 30, 45, 60, 90, 120, 480]


def offered_starts(now: datetime, zone: ZoneInfo, minutes: int) -> set[datetime]:
    return {slot.start for day in window_slots(now, zone, minutes) for slot in day.slots}


def probes(now: datetime, zone: ZoneInfo) -> list[datetime]:
    """Every 5 minutes from a day before the window to a day after it, as UTC instants."""
    first = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (first - timedelta(days=1)).astimezone(UTC)
    return [start + timedelta(minutes=5 * n) for n in range((16 * 24 * 12) + 1)]


@pytest.mark.parametrize("minutes", DURATIONS)
@pytest.mark.parametrize(
    ("zone", "now"),
    [
        (MSK, datetime(2026, 11, 5, 10, 0, tzinfo=timezone(timedelta(hours=3)))),
        (MSK, datetime(2026, 11, 5, 23, 59, 59, tzinfo=timezone(timedelta(hours=3)))),
        (MSK, datetime(2026, 11, 5, 9, 0, tzinfo=timezone(timedelta(hours=3)))),
        (MSK, datetime(2026, 11, 5, 17, 45, tzinfo=timezone(timedelta(hours=3)))),
        # Daylight-saving changes inside the window: 2026-03-29 and 2026-10-25 in Berlin.
        (BERLIN, datetime(2026, 3, 25, 12, 0, tzinfo=UTC)),
        (BERLIN, datetime(2026, 10, 20, 12, 0, tzinfo=UTC)),
    ],
)
def test_the_direct_check_accepts_exactly_the_starts_the_window_offers(
    minutes: int, zone: ZoneInfo, now: datetime
) -> None:
    offered = offered_starts(now, zone, minutes)
    assert offered, "the scenario must offer something"

    accepted = {at for at in probes(now, zone) if is_slot_start(now, zone, minutes, at)}

    assert accepted == {start.astimezone(UTC) for start in offered}


def test_a_start_one_minute_either_side_of_a_slot_is_rejected() -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=timezone(timedelta(hours=3)))
    for minutes in DURATIONS:
        for start in offered_starts(now, MSK, minutes):
            assert is_slot_start(now, MSK, minutes, start)
            assert not is_slot_start(now, MSK, minutes, start + timedelta(minutes=1))
            assert not is_slot_start(now, MSK, minutes, start - timedelta(minutes=1))
