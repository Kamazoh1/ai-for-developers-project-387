"""Free slots of the booking window: the rules, as pure functions of "now".

``window_slots`` answers "which slots could an event type of this length offer
over the booking window, ignoring bookings?". It knows the calendar timezone,
the working hours, the 30-minute start grid and the "strictly after now" rule,
and nothing about storage. Booked intervals are subtracted by the caller (the
booking flow), which keeps this unit testable on its own.

``is_slot_start`` is the same rules asked about one start; ``tests/test_slot_rules.py``
holds the two to agree.

Wall-clock arithmetic across daylight-saving changes is done on UTC instants.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app import settings
from app.schemas import ApiModel


class Slot(ApiModel):
    """A free interval; also the wire shape of the slots endpoint."""

    start: datetime
    end: datetime


class SlotDay(ApiModel):
    date: date
    slots: list[Slot]


def window_slots(now: datetime, timezone: ZoneInfo, duration_minutes: int) -> list[SlotDay]:
    """One ``SlotDay`` per day of the booking window, today first, empty days included.

    ``now`` is any timezone-aware instant. A slot belongs to the day of its start in
    ``timezone``; its ``start`` and ``end`` are in that zone's offset. Slots of today
    are kept only if they start strictly after ``now``.
    """
    today = now.astimezone(timezone).date()
    length = timedelta(minutes=duration_minutes)
    return [
        SlotDay(
            date=day,
            slots=[
                Slot(start=start.astimezone(timezone), end=(start + length).astimezone(timezone))
                for start in _day_starts(day, timezone, length)
                if start > now
            ],
        )
        for day in (today + timedelta(days=n) for n in range(settings.BOOKING_WINDOW_DAYS))
    ]


def is_slot_start(
    now: datetime, timezone: ZoneInfo, duration_minutes: int, start: datetime
) -> bool:
    """Whether ``start`` is the start of a slot ``window_slots`` offers, without building them.

    The same rules, checked directly: strictly after ``now``, on a day of the booking window,
    on the start grid of that day (counted from its opening instant) and ending by closing time.
    """
    if start <= now:
        return False
    day = start.astimezone(timezone).date()
    if not 0 <= (day - now.astimezone(timezone).date()).days < settings.BOOKING_WINDOW_DAYS:
        return False
    opens, closes = _working_hours(day, timezone)
    offset = start - opens
    return (
        offset >= timedelta(0)
        and offset % timedelta(minutes=settings.SLOT_STEP_MINUTES) == timedelta(0)
        and start + timedelta(minutes=duration_minutes) <= closes
    )


def _working_hours(day: date, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    """The opening and closing instants of ``day``, in UTC."""
    opens = datetime.combine(day, settings.WORKING_HOURS_START, tzinfo=timezone)
    closes = datetime.combine(day, settings.WORKING_HOURS_END, tzinfo=timezone)
    return opens.astimezone(UTC), closes.astimezone(UTC)


def _day_starts(day: date, timezone: ZoneInfo, length: timedelta) -> list[datetime]:
    """Starts, as UTC instants, of the slots of ``day`` that end by closing time."""
    opens, closes = _working_hours(day, timezone)
    step = timedelta(minutes=settings.SLOT_STEP_MINUTES)
    starts: list[datetime] = []
    start = opens
    while start + length <= closes:
        starts.append(start)
        start += step
    return starts
