"""Schema creation on a database that predates a column."""

import sqlite3
from pathlib import Path

from app.db import Database


def test_a_database_created_before_the_topic_column_gets_it_on_startup(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as old:
        old.executescript(
            """
            CREATE TABLE event_types (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                description TEXT NOT NULL, duration_minutes INTEGER NOT NULL
            );
            CREATE TABLE bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type_id TEXT NOT NULL REFERENCES event_types(id),
                start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
                guest_name TEXT NOT NULL, guest_email TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO event_types VALUES ('call', 'Звонок', '', 30);
            INSERT INTO bookings (event_type_id, start_utc, end_utc, guest_name, guest_email,
                created_at) VALUES ('call', '2026-11-06T07:00:00', '2026-11-06T07:30:00',
                'Мария', 'maria@example.com', '2026-11-05T07:00:00');
            """
        )

    database = Database(str(path), lock_timeout_seconds=5)
    database.create_schema()
    database.create_schema()  # idempotent: a second start changes nothing

    with database.connect() as connection:
        topics = connection.execute("SELECT topic FROM bookings").fetchall()
    assert [row["topic"] for row in topics] == [""]
