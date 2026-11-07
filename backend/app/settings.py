"""Calendar configuration.

The calendar timezone (ADR 0001) and the SQLite database path are configurable;
the remaining parameters and the owner profile are constants exposed read-only
by the API.
"""

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMEZONE_ENV = "CALENDAR_TIMEZONE"
DEFAULT_TIMEZONE = "Europe/Moscow"

DATABASE_PATH_ENV = "DATABASE_PATH"
DEFAULT_DATABASE_PATH = "call-calendar.db"  # relative to the working directory

# A built frontend to serve next to the API (the container image sets it). Off by default:
# in development Vite serves the frontend and proxies `/api`.
STATIC_DIR_ENV = "STATIC_DIR"

# How long a booking waits for the database write lock before `503 service_busy` (ADR 0002).
# Tests shorten it to see the 503 without waiting.
LOCK_TIMEOUT_ENV = "DATABASE_LOCK_TIMEOUT_SECONDS"
DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0

WORKING_HOURS_START = time(9, 0)
WORKING_HOURS_END = time(18, 0)
SLOT_STEP_MINUTES = 30
BOOKING_WINDOW_DAYS = 14
OWNER_NAME = "Алексей Иванов"


@dataclass(frozen=True)
class Settings:
    calendar_timezone: str
    database_path: str
    lock_timeout_seconds: float
    static_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        name = os.environ.get(TIMEZONE_ENV, DEFAULT_TIMEZONE)
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(
                f"{TIMEZONE_ENV}={name!r} is not a valid IANA time zone "
                f"(expected a name like {DEFAULT_TIMEZONE!r})"
            ) from error
        return cls(
            calendar_timezone=name,
            database_path=os.environ.get(DATABASE_PATH_ENV, DEFAULT_DATABASE_PATH),
            lock_timeout_seconds=_lock_timeout(),
            static_dir=_static_dir(),
        )


def _static_dir() -> Path | None:
    raw = os.environ.get(STATIC_DIR_ENV, "").strip()
    if not raw:
        return None
    directory = Path(raw)
    if not directory.is_dir():
        raise ValueError(f"{STATIC_DIR_ENV}={raw!r} is not a directory")
    return directory


def _lock_timeout() -> float:
    raw = os.environ.get(LOCK_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_LOCK_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        seconds = -1.0
    if seconds < 0:
        raise ValueError(f"{LOCK_TIMEOUT_ENV}={raw!r} is not a non-negative number of seconds")
    return seconds
