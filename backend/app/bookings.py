"""Booking a slot (ADR 0002).

Checks run in a fixed order: request validation (``422 validation_error``, done by the
framework), then everything that does not depend on bookings (``422 invalid_slot``), then,
inside one write-locked transaction, the overlap check and the insert (``409 slot_taken``).
If the write lock is not free within the lock timeout the answer is ``503 service_busy``.
"""

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import AfterValidator, AwareDatetime, BeforeValidator, Field, StringConstraints

from app.clock import CalendarTimezone, Now, NowSource
from app.db import Database, get_db, lock_timeout_as_service_busy
from app.errors import ApiError, declare_errors
from app.event_types import find_event_type
from app.occupancy import conflicts_with_booking, from_stored, to_stored
from app.schemas import ApiModel
from app.slots import is_slot_start

GuestName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
GuestEmail = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=50, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]
# Optional; blank after trimming means "no topic", stored as an empty string.
# The length is checked on the raw string, as the contract says, and only then trimmed.
Topic = Annotated[str, Field(max_length=500), AfterValidator(str.strip)]


_RFC_3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


def _require_rfc_3339(value: object) -> object:
    """Only RFC 3339 text: pydantic's lax datetime would also take Unix timestamps."""
    if not isinstance(value, str) or not _RFC_3339.fullmatch(value):
        raise ValueError("must be an RFC 3339 date-time with an offset")
    return value


OffsetDateTime = Annotated[AwareDatetime, BeforeValidator(_require_rfc_3339)]


class CreateBooking(ApiModel):
    event_type_id: str
    start: OffsetDateTime
    guest_name: GuestName
    guest_email: GuestEmail
    topic: Topic = ""


class Booking(ApiModel):
    id: int
    event_type_id: str
    start: datetime
    end: datetime
    guest_name: str
    guest_email: str
    topic: str
    created_at: datetime


def invalid_slot() -> ApiError:
    return ApiError(422, "invalid_slot", "The start is not a free slot of this event type")


router = APIRouter()


@router.post(
    "/api/bookings",
    status_code=status.HTTP_201_CREATED,
    responses=declare_errors(409, 422, 503),
)
def create_booking(
    body: CreateBooking,
    db: Annotated[Database, Depends(get_db)],
    now: Now,
    clock: NowSource,
    timezone: CalendarTimezone,
) -> Booking:
    with db.connect() as connection:
        event_type = find_event_type(connection, body.event_type_id)
        if event_type is None:
            raise invalid_slot()
        duration = event_type.duration_minutes
        # A start is valid exactly when the slots endpoint would offer it, bookings aside.
        if not is_slot_start(now, timezone, duration, body.start):
            raise invalid_slot()

        end = body.start + timedelta(minutes=duration)
        # Check and insert under one write lock (ADR 0002); the connection is in autocommit mode.
        _begin_write(connection)
        try:
            # Waiting for the lock can take long: read the clock again, and check the start
            # against it, so the booking is neither of a slot that has started meanwhile nor
            # stamped with the time the request arrived.
            written_at = clock()
            if not is_slot_start(written_at, timezone, duration, body.start):
                raise invalid_slot()
            created_at = written_at.replace(microsecond=0)
            if conflicts_with_booking(connection, body.start, end):
                raise ApiError(409, "slot_taken", "The time overlaps an existing booking")
            booking_id = _insert(connection, body, end, created_at)
            connection.execute("COMMIT")
        except BaseException:
            _rollback(connection)
            raise

    return Booking(
        id=booking_id,
        event_type_id=body.event_type_id,
        start=body.start.astimezone(timezone),
        end=end.astimezone(timezone),
        guest_name=body.guest_name,
        guest_email=body.guest_email,
        topic=body.topic,
        created_at=created_at.astimezone(timezone),
    )


def _begin_write(connection: sqlite3.Connection) -> None:
    """Take the write lock, waiting up to the connection timeout; then ``503 service_busy``."""
    with lock_timeout_as_service_busy():
        connection.execute("BEGIN IMMEDIATE")


def _rollback(connection: sqlite3.Connection) -> None:
    """Undo the open transaction, if any, without replacing the error being handled.

    SQLite may already have ended the transaction itself (a failed COMMIT, a full disk);
    a ``ROLLBACK`` then would raise and hide the original error.
    """
    if connection.in_transaction:
        connection.execute("ROLLBACK")


def _insert(
    connection: sqlite3.Connection, body: CreateBooking, end: datetime, created_at: datetime
) -> int:
    cursor = connection.execute(
        "INSERT INTO bookings (event_type_id, start_utc, end_utc, guest_name, guest_email, "
        "topic, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            body.event_type_id,
            to_stored(body.start),
            to_stored(end),
            body.guest_name,
            body.guest_email,
            body.topic,
            to_stored(created_at),
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


@router.get("/api/admin/bookings")
def list_upcoming_bookings(
    db: Annotated[Database, Depends(get_db)], now: Now, timezone: CalendarTimezone
) -> list[Booking]:
    """Bookings that end later than now, earliest start first; no pagination."""
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT id, event_type_id, start_utc, end_utc, guest_name, guest_email, topic, "
            "created_at FROM bookings WHERE end_utc > ? ORDER BY start_utc",
            (to_stored(now),),
        ).fetchall()
    return [
        Booking(
            id=row["id"],
            event_type_id=row["event_type_id"],
            start=from_stored(row["start_utc"]).astimezone(timezone),
            end=from_stored(row["end_utc"]).astimezone(timezone),
            guest_name=row["guest_name"],
            guest_email=row["guest_email"],
            topic=row["topic"],
            created_at=from_stored(row["created_at"]).astimezone(timezone),
        )
        for row in rows
    ]
