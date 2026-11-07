"""Booked intervals: the storage side of the overlap rule (ADR 0002).

Intervals are half-open ``[start, end)`` and compared as instants, whatever the
event type: ``a`` and ``b`` conflict when ``a.start < b.end`` and ``a.end > b.start``.
Instants are stored in UTC as fixed-format text (``2026-11-06T07:00:00Z``), which
sorts and compares chronologically.
"""

import sqlite3
from datetime import UTC, datetime

from app.slots import Slot, SlotDay

_STORED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def to_stored(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime(_STORED_FORMAT)


def from_stored(text: str) -> datetime:
    return datetime.strptime(text, _STORED_FORMAT).replace(tzinfo=UTC)


def booked_intervals(
    connection: sqlite3.Connection, after: datetime
) -> list[tuple[datetime, datetime]]:
    """Bookings that end later than ``after``: the only ones that can block a slot after it."""
    rows = connection.execute(
        "SELECT start_utc, end_utc FROM bookings WHERE end_utc > ?", (to_stored(after),)
    ).fetchall()
    return [(from_stored(row["start_utc"]), from_stored(row["end_utc"])) for row in rows]


def conflicts_with_booking(connection: sqlite3.Connection, start: datetime, end: datetime) -> bool:
    row = connection.execute(
        "SELECT 1 FROM bookings WHERE start_utc < ? AND end_utc > ? LIMIT 1",
        (to_stored(end), to_stored(start)),
    ).fetchone()
    return row is not None


def without_booked(days: list[SlotDay], booked: list[tuple[datetime, datetime]]) -> list[SlotDay]:
    """The slots of ``days`` that overlap none of the ``booked`` intervals."""

    def is_free(slot: Slot) -> bool:
        return not any(slot.start < end and slot.end > start for start, end in booked)

    return [
        SlotDay(date=day.date, slots=[slot for slot in day.slots if is_free(slot)]) for day in days
    ]
