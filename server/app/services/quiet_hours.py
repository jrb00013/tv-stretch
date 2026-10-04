from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlmodel import Session

from app.models import EventLog, QuietHours, utcnow

logger = structlog.get_logger(__name__)

#: Sentinel reason returned by callers when a handoff is suppressed.
SUPPRESSED_REASON = "quiet_hours"

MINUTES_PER_DAY = 24 * 60


def parse_weekdays(raw: str) -> set[int]:
    """Parse ``"1,2,3"`` into ISO weekday numbers, ignoring junk entries."""
    days: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 7:
            days.add(int(part))
    return days


def format_weekdays(days: set[int] | list[int] | tuple[int, ...]) -> str:
    return ",".join(str(d) for d in sorted(set(days)))


def is_quiet_now(
    quiet: QuietHours | None,
    now: datetime | None = None,
) -> bool:
    """Whether ``now`` falls inside the home's quiet-hours window.

    Windows may wrap past midnight (``start_minute > end_minute``); the weekday
    list applies to the day the window *starts*, so a 22:00-07:00 window listed
    for Monday covers Monday night into Tuesday morning. All times are UTC.
    """
    if quiet is None or not quiet.enabled:
        return False

    ts = now or utcnow()
    minute_of_day = ts.hour * 60 + ts.minute
    weekday = ts.isoweekday()
    start = quiet.start_minute
    end = quiet.end_minute
    days = parse_weekdays(quiet.weekdays)

    if start <= end:
        return weekday in days and start <= minute_of_day < end

    # Wrapping window: either we are in the tail of the start day, or in the early
    # hours that belong to a window that started the previous day.
    if minute_of_day >= start:
        return weekday in days
    previous_day = weekday - 1 if weekday > 1 else 7
    return previous_day in days and minute_of_day < end


@dataclass
class QuietHoursDecision:
    suppressed: bool
    reason: str | None = None
    #: Minutes until the window ends, useful for client copy ("quiet for 6h 12m").
    minutes_remaining: int | None = None


def evaluate(
    session: Session,
    home_id: uuid.UUID,
    now: datetime | None = None,
) -> QuietHoursDecision:
    """Load the home's quiet hours and decide whether to suppress a handoff."""
    quiet = session.get(QuietHours, home_id)
    if not is_quiet_now(quiet, now):
        return QuietHoursDecision(suppressed=False)

    ts = now or utcnow()
    end = quiet.end_minute
    minute_of_day = ts.hour * 60 + ts.minute
    if end > minute_of_day:
        remaining = end - minute_of_day
    else:
        remaining = MINUTES_PER_DAY - minute_of_day + end
    logger.info(
        "handoff_suppressed",
        home_id=str(home_id),
        reason=SUPPRESSED_REASON,
        minutes_remaining=remaining,
    )
    return QuietHoursDecision(
        suppressed=True, reason=SUPPRESSED_REASON, minutes_remaining=remaining
    )


def minutes_until_end(quiet: QuietHours | None, now: datetime | None = None) -> int | None:
    """Minutes from ``now`` until the window ends (``None`` when not quiet)."""
    if not is_quiet_now(quiet, now):
        return None
    ts = now or utcnow()
    minute_of_day = ts.hour * 60 + ts.minute
    if quiet.end_minute > minute_of_day:
        return quiet.end_minute - minute_of_day
    return MINUTES_PER_DAY - minute_of_day + quiet.end_minute


def get_quiet_hours(session: Session, home_id: uuid.UUID) -> QuietHours | None:
    return session.get(QuietHours, home_id)


def log_suppressed(
    session: Session,
    home_id: uuid.UUID,
    room_id: uuid.UUID,
    decision: QuietHoursDecision,
    *,
    source: str,
) -> None:
    """Record a suppressed handoff so operators can see why the TV did not switch."""
    session.add(
        EventLog(
            home_id=home_id,
            kind="handoff_suppressed",
            payload_json=json.dumps(
                {
                    "room_id": str(room_id),
                    "source": source,
                    "reason": decision.reason,
                    "minutes_remaining": decision.minutes_remaining,
                }
            ),
        )
    )
    session.commit()


def next_transition(quiet: QuietHours | None, now: datetime | None = None) -> datetime | None:
    """Next instant the window starts or ends — lets clients schedule a refresh."""
    if quiet is None or not quiet.enabled:
        return None
    ts = now or utcnow()
    today = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in (0, 1, 2):
        day = today + timedelta(days=offset)
        for minute in (quiet.start_minute, quiet.end_minute):
            candidate = day + timedelta(minutes=minute)
            if candidate > ts:
                return candidate
    return None


__all__ = [
    "MINUTES_PER_DAY",
    "SUPPRESSED_REASON",
    "QuietHoursDecision",
    "evaluate",
    "format_weekdays",
    "get_quiet_hours",
    "is_quiet_now",
    "log_suppressed",
    "minutes_until_end",
    "next_transition",
    "parse_weekdays",
]
