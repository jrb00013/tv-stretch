from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models import IdempotencyRecord, utcnow

logger = structlog.get_logger(__name__)

#: How long a stored response stays replayable.
IDEMPOTENCY_TTL = timedelta(hours=24)

#: Client-supplied keys are bounded so the replay cache cannot be used as storage.
MAX_KEY_LENGTH = 128

REPLAY_HEADER = "Idempotent-Replay"
REPLAY_STATUS = "completed"
IN_FLIGHT_STATUS = "in_flight"


class IdempotencyConflict(Exception):
    """The same key was reused with a different payload, or is still in flight."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass
class IdempotencyDecision:
    #: ``fresh`` — caller should do the work; ``replay`` — return ``response``.
    action: str
    response: dict[str, Any] | None = None


def read_key(request: Any) -> str | None:
    """Extract and validate the ``Idempotency-Key`` header.

    Returns ``None`` when absent. Raises ``ValueError`` when present but unusable,
    so a malformed key never silently degrades into a second execution.
    """
    raw = None
    headers = getattr(request, "headers", None)
    if headers is not None:
        raw = headers.get("idempotency-key")
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        raise ValueError("Idempotency-Key must not be empty")
    if len(key) > MAX_KEY_LENGTH:
        raise ValueError(f"Idempotency-Key must be at most {MAX_KEY_LENGTH} characters")
    return key


def hash_request(endpoint: str, payload: dict[str, Any]) -> str:
    """Stable fingerprint of endpoint + payload, used to detect key reuse."""
    blob = json.dumps({"endpoint": endpoint, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def begin(
    session: Session,
    home_id: uuid.UUID,
    endpoint: str,
    key: str | None,
    payload: dict[str, Any],
) -> IdempotencyDecision:
    """Claim ``key`` for this request.

    Returns ``fresh`` when the caller should execute, ``replay`` with the stored
    response when this exact request already completed, and raises
    :class:`IdempotencyConflict` for key reuse with a different payload or a
    request that is still in flight.
    """
    if not key:
        return IdempotencyDecision(action="fresh")

    request_hash = hash_request(endpoint, payload)
    record = session.exec(
        select(IdempotencyRecord).where(
            IdempotencyRecord.home_id == home_id, IdempotencyRecord.key == key
        )
    ).first()

    if record is not None and record.expires_at <= utcnow():
        session.delete(record)
        session.commit()
        record = None

    if record is not None:
        if record.request_hash != request_hash:
            raise IdempotencyConflict(
                "Idempotency-Key was already used for a different request payload"
            )
        if record.status == IN_FLIGHT_STATUS:
            raise IdempotencyConflict("a request with this Idempotency-Key is still in flight")
        return IdempotencyDecision(
            action="replay", response=json.loads(record.response_json or "{}")
        )

    session.add(
        IdempotencyRecord(
            home_id=home_id,
            key=key,
            endpoint=endpoint,
            request_hash=request_hash,
            status=IN_FLIGHT_STATUS,
            expires_at=utcnow() + IDEMPOTENCY_TTL,
        )
    )
    session.commit()
    logger.info("idempotency_claimed", home_id=str(home_id), endpoint=endpoint)
    return IdempotencyDecision(action="fresh")


def complete(
    session: Session, home_id: uuid.UUID, key: str | None, response: dict[str, Any]
) -> None:
    """Store the response so retries replay it."""
    if not key:
        return
    record = session.exec(
        select(IdempotencyRecord).where(
            IdempotencyRecord.home_id == home_id, IdempotencyRecord.key == key
        )
    ).first()
    if record is None:
        return
    record.status = REPLAY_STATUS
    record.response_json = json.dumps(response)
    session.add(record)
    session.commit()


def purge_expired(session: Session, home_id: uuid.UUID | None = None) -> int:
    """Delete expired records. Returns how many were removed."""
    stmt = select(IdempotencyRecord).where(IdempotencyRecord.expires_at <= utcnow())
    if home_id is not None:
        stmt = stmt.where(IdempotencyRecord.home_id == home_id)
    rows = list(session.exec(stmt).all())
    for row in rows:
        session.delete(row)
    if rows:
        session.commit()
    return len(rows)
