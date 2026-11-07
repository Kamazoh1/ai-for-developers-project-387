"""The calendar's clock and timezone, as FastAPI dependencies.

"Now" is an app dependency so tests can fix it: ``create_app(now=...)`` replaces
the real clock. Request handlers take ``Now`` and ``CalendarTimezone`` instead of
reading the system time or the environment themselves.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Request

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


def get_now(request: Request) -> datetime:
    """The current instant, timezone-aware."""
    return request.app.state.clock()


def get_clock(request: Request) -> Clock:
    """The clock itself, for a handler that must read the time again after waiting."""
    return request.app.state.clock


def get_calendar_timezone(request: Request) -> ZoneInfo:
    return ZoneInfo(request.app.state.calendar_timezone)


Now = Annotated[datetime, Depends(get_now)]
NowSource = Annotated[Clock, Depends(get_clock)]
CalendarTimezone = Annotated[ZoneInfo, Depends(get_calendar_timezone)]
