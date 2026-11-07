from datetime import time

from fastapi import FastAPI

from app import bookings, event_types, settings
from app.clock import Clock, system_clock
from app.db import Database
from app.errors import install_error_handlers, install_openapi_cleanup
from app.frontend import install_frontend
from app.schemas import ApiModel


class WorkingHours(ApiModel):
    start: time
    end: time


class Owner(ApiModel):
    name: str


class CalendarSettings(ApiModel):
    timezone: str
    working_hours: WorkingHours
    slot_step_minutes: int
    booking_window_days: int
    owner: Owner


def create_app(now: Clock | None = None) -> FastAPI:
    """Build the app. Reads settings from the environment and refuses to start on bad ones.

    There is no module-level ``app``: importing this module has no side effects. Servers
    start it as a factory: ``uvicorn --factory app.main:create_app``.

    ``now`` replaces the system clock (tests fix it); it returns a timezone-aware datetime.
    """
    config = settings.Settings.from_env()
    app = FastAPI(title="Call Calendar")
    install_error_handlers(app)
    install_openapi_cleanup(app)

    app.state.clock = now or system_clock
    app.state.calendar_timezone = config.calendar_timezone

    app.state.db = Database(config.database_path, config.lock_timeout_seconds)
    app.state.db.create_schema()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/calendar")
    def get_calendar() -> CalendarSettings:
        return CalendarSettings(
            timezone=config.calendar_timezone,
            working_hours=WorkingHours(
                start=settings.WORKING_HOURS_START, end=settings.WORKING_HOURS_END
            ),
            slot_step_minutes=settings.SLOT_STEP_MINUTES,
            booking_window_days=settings.BOOKING_WINDOW_DAYS,
            owner=Owner(name=settings.OWNER_NAME),
        )

    app.include_router(event_types.router)
    app.include_router(bookings.router)

    # Last, so that it only catches what no route above answers.
    if config.static_dir is not None:
        install_frontend(app, config.static_dir)

    return app
