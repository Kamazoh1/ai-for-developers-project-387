"""SQLite storage.

One file database whose path comes from settings. The schema is created at
startup (``Database.create_schema``), idempotently. Connections are short-lived:
open one per unit of work with ``Database.connect()``. They run in autocommit
mode, so a unit of work that needs a transaction opens it explicitly; the
booking flow (``bookings.create_booking``, ADR 0002) uses ``BEGIN IMMEDIATE``.
"""

import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager

from fastapi import Request

from app.errors import ApiError

SCHEMA = """
CREATE TABLE IF NOT EXISTS event_types (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type_id TEXT NOT NULL REFERENCES event_types(id),
    start_utc     TEXT NOT NULL,
    end_utc       TEXT NOT NULL,
    guest_name    TEXT NOT NULL,
    guest_email   TEXT NOT NULL,
    topic         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str, lock_timeout_seconds: float) -> None:
        self.path = path
        # How long a writer waits for the database lock before giving up (ADR 0002).
        self.lock_timeout_seconds = lock_timeout_seconds

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection]:
        """A connection in autocommit mode with rows addressable by column name."""
        with closing(
            sqlite3.connect(self.path, timeout=self.lock_timeout_seconds, isolation_level=None)
        ) as connection:
            connection.row_factory = sqlite3.Row
            yield connection

    def create_schema(self) -> None:
        with self.connect() as connection:
            # WAL lets readers proceed while a booking transaction holds the write lock.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            self._add_topic_column(connection)

    @staticmethod
    def _add_topic_column(connection: sqlite3.Connection) -> None:
        """Databases made before bookings had a topic get the column; their rows get ''."""
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(bookings)")}
        if "topic" in columns:
            return
        try:
            connection.execute("ALTER TABLE bookings ADD COLUMN topic TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError as error:
            # Another process started at the same moment and added it first.
            if "duplicate column" not in str(error):
                raise


@contextmanager
def lock_timeout_as_service_busy() -> Generator[None]:
    """Turn "the write lock was not free within the lock timeout" into ``503 service_busy``.

    Wrap any statement that takes the write lock. The request changed nothing and can be retried.
    """
    try:
        yield
    except sqlite3.OperationalError as error:
        if error.sqlite_errorcode is not None and (
            error.sqlite_errorcode & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        ):
            raise ApiError(503, "service_busy", "The service is busy, try again") from error
        raise


def get_db(request: Request) -> Database:
    """FastAPI dependency: the app's database (created by ``create_app``)."""
    return request.app.state.db
