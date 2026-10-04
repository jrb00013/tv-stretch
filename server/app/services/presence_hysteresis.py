from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import structlog

from app.models import utcnow

logger = structlog.get_logger(__name__)

Action = Literal["handoff", "wait"]


@dataclass
class Candidate:
    """A room that has been reported occupied but has not yet earned a handoff."""

    room_id: uuid.UUID
    first_seen_at: datetime
    last_seen_at: datetime
    reports: int = 0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "room_id": str(self.room_id),
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "reports": self.reports,
            "confidence": self.confidence,
        }


@dataclass
class DwellDecision:
    action: Action
    #: Seconds of dwell still required (``0`` when ``action == "handoff"``).
    remaining_seconds: float = 0.0
    candidate: Candidate | None = None


@dataclass
class ReleaseDecision:
    release: bool
    remaining_seconds: float = 0.0


@dataclass
class HomePresenceState:
    candidate: Candidate | None = None
    #: First time the active room was reported below the confidence threshold.
    vacant_since: datetime | None = None


class PresenceTracker:
    """Dwell hysteresis and vacancy release for sensor-driven presence.

    A single frame above threshold is not evidence that somebody settled in — SLAM
    noise, someone crossing the doorway or a pet all produce one. A handoff only
    fires once occupancy has been reported continuously for ``dwell_seconds``; a gap
    longer than ``max_gap_seconds`` restarts the clock.

    State is in-memory per home (a restart clears pending dwell); that is deliberate,
    since re-arming a dwell timer on boot would delay every handoff for no reason.
    """

    def __init__(
        self,
        *,
        dwell_seconds: float = 2.0,
        max_gap_seconds: float = 30.0,
        release_seconds: float = 0.0,
        now_fn: Callable[[], datetime] = utcnow,
    ) -> None:
        self.dwell_seconds = dwell_seconds
        self.max_gap_seconds = max_gap_seconds
        self.release_seconds = release_seconds
        self._now = now_fn
        self._homes: dict[uuid.UUID, HomePresenceState] = {}

    def _state(self, home_id: uuid.UUID) -> HomePresenceState:
        state = self._homes.get(home_id)
        if state is None:
            state = HomePresenceState()
            self._homes[home_id] = state
        return state

    def observe(
        self,
        home_id: uuid.UUID,
        room_id: uuid.UUID,
        confidence: float,
        *,
        now: datetime | None = None,
    ) -> DwellDecision:
        """Register an above-threshold reading and decide whether to hand off."""
        ts = now or self._now()
        state = self._state(home_id)

        if self.dwell_seconds <= 0:
            state.candidate = None
            return DwellDecision(action="handoff")

        candidate = state.candidate
        if (
            candidate is None
            or candidate.room_id != room_id
            or (ts - candidate.last_seen_at) > timedelta(seconds=self.max_gap_seconds)
        ):
            state.candidate = Candidate(
                room_id=room_id,
                first_seen_at=ts,
                last_seen_at=ts,
                confidence=confidence,
            )
            candidate = state.candidate
            logger.info(
                "presence_candidate_started",
                home_id=str(home_id),
                room_id=str(room_id),
                dwell_seconds=self.dwell_seconds,
            )

        candidate.last_seen_at = ts
        candidate.reports += 1
        candidate.confidence = confidence

        waited = (ts - candidate.first_seen_at).total_seconds()
        if waited >= self.dwell_seconds:
            state.candidate = None
            return DwellDecision(action="handoff", candidate=candidate)

        remaining = round(self.dwell_seconds - waited, 3)
        return DwellDecision(action="wait", remaining_seconds=remaining, candidate=candidate)

    def observe_vacancy(
        self,
        home_id: uuid.UUID,
        active_room_id: uuid.UUID | None,
        *,
        now: datetime | None = None,
    ) -> ReleaseDecision:
        """Register a below-threshold reading; release the active room once sustained."""
        ts = now or self._now()
        state = self._state(home_id)

        if self.release_seconds <= 0 or active_room_id is None:
            state.vacant_since = None
            return ReleaseDecision(release=False)

        if state.vacant_since is None:
            state.vacant_since = ts
            return ReleaseDecision(release=False, remaining_seconds=round(self.release_seconds, 3))

        vacant_for = (ts - state.vacant_since).total_seconds()
        if vacant_for >= self.release_seconds:
            state.vacant_since = None
            logger.info(
                "presence_release",
                home_id=str(home_id),
                room_id=str(active_room_id),
                vacant_seconds=round(vacant_for, 3),
            )
            return ReleaseDecision(release=True)

        return ReleaseDecision(
            release=False, remaining_seconds=round(self.release_seconds - vacant_for, 3)
        )

    def clear_active(self, home_id: uuid.UUID) -> None:
        """Forget dwell/vacancy state after a handoff or manual change."""
        state = self._homes.get(home_id)
        if state is not None:
            state.candidate = None
            state.vacant_since = None

    def clear_home(self, home_id: uuid.UUID) -> None:
        self._homes.pop(home_id, None)

    def snapshot(self, home_id: uuid.UUID) -> dict:
        state = self._homes.get(home_id) or HomePresenceState()
        return {
            "dwell_seconds": self.dwell_seconds,
            "max_gap_seconds": self.max_gap_seconds,
            "release_seconds": self.release_seconds,
            "candidate": state.candidate.to_dict() if state.candidate else None,
            "vacant_since": state.vacant_since.isoformat() if state.vacant_since else None,
        }


_tracker: PresenceTracker | None = None


def get_presence_tracker() -> PresenceTracker:
    global _tracker
    if _tracker is None:
        from app.config import settings

        _tracker = PresenceTracker(
            dwell_seconds=settings.presence_dwell_seconds,
            max_gap_seconds=settings.presence_dwell_max_gap_seconds,
            release_seconds=settings.presence_release_seconds,
        )
    return _tracker


def reset_presence_tracker() -> None:
    """Drop all tracked presence state (test isolation)."""
    global _tracker
    _tracker = None


__all__ = [
    "Candidate",
    "DwellDecision",
    "HomePresenceState",
    "PresenceTracker",
    "ReleaseDecision",
    "get_presence_tracker",
    "reset_presence_tracker",
]
