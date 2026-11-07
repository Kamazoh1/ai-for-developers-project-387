"""Event types: storage and the public and admin endpoints (ADR 0003)."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import Field, StringConstraints

from app.clock import CalendarTimezone, Now
from app.db import Database, get_db, lock_timeout_as_service_busy
from app.errors import ApiError, declare_errors
from app.occupancy import booked_intervals, without_booked
from app.schemas import ApiModel
from app.slots import SlotDay, window_slots

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,40}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
# Strict: a JSON string or boolean is not a number of minutes.
DurationMinutes = Annotated[int, Field(strict=True, ge=5, le=480, multiple_of=5)]


class EventType(ApiModel):
    id: str
    name: str
    description: str
    duration_minutes: int


class CreateEventType(ApiModel):
    id: Slug
    name: Name
    description: Description = ""
    duration_minutes: DurationMinutes


router = APIRouter()


@router.get("/api/event-types")
def list_event_types(db: Annotated[Database, Depends(get_db)]) -> list[EventType]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT id, name, description, duration_minutes FROM event_types ORDER BY rowid"
        ).fetchall()
    return [EventType(**dict(row)) for row in rows]


def find_event_type(connection: sqlite3.Connection, event_type_id: str) -> EventType | None:
    row = connection.execute(
        "SELECT id, name, description, duration_minutes FROM event_types WHERE id = ?",
        (event_type_id,),
    ).fetchone()
    return None if row is None else EventType(**dict(row))


def event_type_not_found() -> ApiError:
    return ApiError(404, "event_type_not_found", "No event type with this id")


@router.get("/api/event-types/{id}", responses=declare_errors(404))
def get_event_type(id: str, db: Annotated[Database, Depends(get_db)]) -> EventType:
    with db.connect() as connection:
        event_type = find_event_type(connection, id)
    if event_type is None:
        raise event_type_not_found()
    return event_type


class Slots(ApiModel):
    days: list[SlotDay]


@router.get("/api/event-types/{id}/slots", responses=declare_errors(404))
def get_slots(
    id: str,
    db: Annotated[Database, Depends(get_db)],
    now: Now,
    timezone: CalendarTimezone,
) -> Slots:
    with db.connect() as connection:
        event_type = find_event_type(connection, id)
        if event_type is None:
            raise event_type_not_found()
        booked = booked_intervals(connection, now)
    days = without_booked(window_slots(now, timezone, event_type.duration_minutes), booked)
    return Slots(days=days)


@router.post(
    "/api/admin/event-types",
    status_code=status.HTTP_201_CREATED,
    responses=declare_errors(409, 422, 503),
)
def create_event_type(body: CreateEventType, db: Annotated[Database, Depends(get_db)]) -> EventType:
    try:
        with db.connect() as connection, lock_timeout_as_service_busy():
            connection.execute(
                "INSERT INTO event_types (id, name, description, duration_minutes) "
                "VALUES (?, ?, ?, ?)",
                (body.id, body.name, body.description, body.duration_minutes),
            )
    except sqlite3.IntegrityError as error:
        # The primary key is the only constraint that can fail on this insert.
        raise ApiError(
            409, "event_type_exists", "An event type with this id already exists"
        ) from error
    return EventType(**body.model_dump())
