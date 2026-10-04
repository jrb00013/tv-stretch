from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models import Node, utcnow

logger = structlog.get_logger(__name__)

#: Node liveness thresholds used to classify a node as online / stale / offline.
ONLINE_WINDOW = timedelta(seconds=60)
STALE_WINDOW = timedelta(minutes=5)

#: First redelivery delay after a failed ack; doubles on each further attempt.
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0


@dataclass
class CommandBatch:
    batch_id: str
    home_id: uuid.UUID
    commands: list[dict[str, Any]]
    status: str = "pending"
    created_at: datetime = field(default_factory=utcnow)
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 3
    expected_nodes: set[str] = field(default_factory=set)
    acked_nodes: set[str] = field(default_factory=set)
    failed_nodes: set[str] = field(default_factory=set)
    last_error: str | None = None
    settled_at: datetime | None = None

    @property
    def fully_acked(self) -> bool:
        """True once every node the batch was sent to has acked."""
        if not self.expected_nodes:
            # Target set unknown (no node connected at push time): the first ack settles it.
            return bool(self.acked_nodes)
        return self.expected_nodes.issubset(self.acked_nodes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "home_id": str(self.home_id),
            "status": self.status,
            "commands": self.commands,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at.isoformat(),
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "next_attempt_at": self.next_attempt_at.isoformat() if self.next_attempt_at else None,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "expected_nodes": sorted(self.expected_nodes),
            "acked_nodes": sorted(self.acked_nodes),
            "failed_nodes": sorted(self.failed_nodes),
            "last_error": self.last_error,
        }


class CommandQueue:
    """Delivery ledger for ``command_batch`` pushes to HDMI nodes.

    Batches stay tracked until every node has acked, the batch exhausts
    ``max_attempts`` (then it is kept as a dead letter for inspection), or the
    batch is completed explicitly. State is in-memory only: a restart drops
    in-flight batches, so lifecycle transitions are also written to ``EventLog``.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 2.0,
        max_dead_letters: int = 200,
        max_completed: int = 100,
    ) -> None:
        self._pending: dict[str, CommandBatch] = {}
        self._dead_letters: dict[str, CommandBatch] = {}
        self._completed: dict[str, CommandBatch] = {}
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff_seconds
        self._max_dead_letters = max_dead_letters
        self._max_completed = max_completed

    def enqueue(
        self,
        home_id: uuid.UUID,
        commands: list[dict[str, Any]],
        batch_id: str | None = None,
        expected_nodes: list[str] | None = None,
    ) -> str:
        bid = batch_id or str(uuid.uuid4())
        batch = CommandBatch(
            batch_id=bid,
            home_id=home_id,
            commands=commands,
            created_at=utcnow(),
            max_attempts=self._max_attempts,
            expected_nodes=set(expected_nodes or []),
        )
        self._pending[bid] = batch
        self._dead_letters.pop(bid, None)
        self._prune_dead_letters()
        logger.info(
            "command_batch_enqueued",
            batch_id=bid,
            home_id=str(home_id),
            count=len(commands),
            expected_nodes=len(batch.expected_nodes),
        )
        return bid

    def get(self, batch_id: str) -> CommandBatch | None:
        batch = self._pending.get(batch_id)
        if batch is not None:
            return batch
        dead = self._dead_letters.get(batch_id)
        if dead is not None:
            return dead
        return self._completed.get(batch_id)

    def mark_attempted(self, batch_id: str) -> CommandBatch | None:
        """Record a delivery attempt and open the next redelivery window.

        Once ``max_attempts`` is reached no further window is opened: the batch
        stops being redelivered but stays inspectable until a late ack completes
        it or a failure moves it to the dead-letter store.
        """
        batch = self._pending.get(batch_id)
        if batch is None:
            return None
        batch.attempts += 1
        batch.last_attempt_at = utcnow()
        if batch.attempts >= batch.max_attempts:
            batch.next_attempt_at = None
        else:
            batch.next_attempt_at = batch.last_attempt_at + timedelta(
                seconds=self._retry_backoff * (2 ** max(0, batch.attempts - 1))
            )
        logger.info(
            "command_batch_attempted",
            batch_id=batch_id,
            attempt=batch.attempts,
            next_attempt_at=batch.next_attempt_at.isoformat() if batch.next_attempt_at else None,
        )
        return batch

    def record_ack(
        self, batch_id: str, node_id: str, *, ok: bool, error: str | None = None
    ) -> None:
        """Apply a device ``ack`` to a tracked batch (idempotent per node)."""
        batch = self._pending.get(batch_id)
        if batch is None:
            logger.warning("command_batch_ack_untracked", batch_id=batch_id, node_id=node_id)
            return
        if ok:
            batch.acked_nodes.add(node_id)
            batch.failed_nodes.discard(node_id)
        else:
            batch.failed_nodes.add(node_id)
            batch.acked_nodes.discard(node_id)
            batch.last_error = error or "node reported failure"

        if batch.failed_nodes:
            self.mark_failed(batch_id, reason=batch.last_error or "node reported failure")
            return

        if batch.fully_acked:
            self.complete(batch_id)
            return

        logger.info(
            "command_batch_ack_partial",
            batch_id=batch_id,
            acked=sorted(batch.acked_nodes),
            expected=sorted(batch.expected_nodes),
            failed=sorted(batch.failed_nodes),
        )

    def complete(self, batch_id: str) -> None:
        batch = self._pending.pop(batch_id, None)
        if batch:
            batch.status = "complete"
            batch.settled_at = utcnow()
            self._remember_completed(batch)
            logger.info(
                "command_batch_complete",
                batch_id=batch_id,
                attempts=batch.attempts,
                acked=sorted(batch.acked_nodes),
            )

    def mark_failed(self, batch_id: str, *, reason: str = "delivery_failed") -> None:
        batch = self._pending.get(batch_id)
        if not batch:
            return
        batch.last_error = reason
        if batch.attempts >= batch.max_attempts:
            self._dead_letters[batch_id] = batch
            self._pending.pop(batch_id, None)
            batch.status = "failed"
            batch.settled_at = utcnow()
            logger.error(
                "command_batch_failed",
                batch_id=batch_id,
                attempts=batch.attempts,
                reason=reason,
            )
        else:
            batch.status = "retry"
            logger.warning("command_batch_retry", batch_id=batch_id, attempt=batch.attempts)

    #: Retained for callers written against the previous ``fail(batch_id)`` signature.
    fail = mark_failed

    def due_retries(self, now: datetime | None = None) -> list[CommandBatch]:
        """Tracked batches whose redelivery window has elapsed.

        Covers both explicit retries (``status == "retry"``) and batches that were
        never acked (e.g. pushed while every node was offline) — a node that
        reconnects inside the window still receives them.
        """
        ts = now or utcnow()
        return [
            b
            for b in self._pending.values()
            if b.next_attempt_at is not None and b.next_attempt_at <= ts
        ]

    def get_pending_for_home(self, home_id: uuid.UUID) -> list[CommandBatch]:
        return [b for b in self._pending.values() if b.home_id == home_id]

    def get_dead_letters_for_home(self, home_id: uuid.UUID) -> list[CommandBatch]:
        return [b for b in self._dead_letters.values() if b.home_id == home_id]

    def get_completed_for_home(self, home_id: uuid.UUID) -> list[CommandBatch]:
        return [b for b in self._completed.values() if b.home_id == home_id]

    def _remember_completed(self, batch: CommandBatch) -> None:
        """Keep a bounded tail of settled batches so acks stay inspectable."""
        self._completed[batch.batch_id] = batch
        while len(self._completed) > self._max_completed:
            oldest = next(iter(self._completed))
            self._completed.pop(oldest, None)

    def clear_home(self, home_id: uuid.UUID) -> int:
        """Drop tracked batches for a home (e.g. after the home is deleted)."""
        removed = 0
        for store in (self._pending, self._dead_letters, self._completed):
            for bid in [k for k, b in store.items() if b.home_id == home_id]:
                store.pop(bid)
                removed += 1
        return removed

    def _prune_dead_letters(self) -> None:
        """Keep the dead-letter store bounded on long-running servers."""
        if len(self._dead_letters) <= self._max_dead_letters:
            return
        ordered = sorted(self._dead_letters.values(), key=lambda b: b.settled_at or b.created_at)
        for batch in ordered[: len(self._dead_letters) - self._max_dead_letters]:
            self._dead_letters.pop(batch.batch_id, None)

    def stats(self) -> dict[str, Any]:
        by_home: dict[str, int] = {}
        for b in self._pending.values():
            key = str(b.home_id)
            by_home[key] = by_home.get(key, 0) + 1
        return {
            "pending_count": len(self._pending),
            "dead_letter_count": len(self._dead_letters),
            "completed_count": len(self._completed),
            "by_home": by_home,
        }


_command_queue: CommandQueue | None = None


def get_command_queue() -> CommandQueue:
    global _command_queue
    if _command_queue is None:
        _command_queue = CommandQueue(retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS)
    return _command_queue


def reset_command_queue() -> None:
    """Drop every tracked batch (test isolation)."""
    global _command_queue
    _command_queue = None


def check_node_health(session: Session, node_id: uuid.UUID) -> dict[str, Any]:
    node = session.get(Node, node_id)
    if not node:
        return {"error": "node_not_found"}

    if node.last_seen_at is None:
        return {"status": "unknown", "node_id": str(node_id)}

    elapsed = utcnow() - node.last_seen_at
    if elapsed < timedelta(seconds=60):
        status = "online"
    elif elapsed < timedelta(minutes=5):
        status = "stale"
    else:
        status = "offline"

    return {
        "status": status,
        "node_id": str(node_id),
        "room_id": str(node.room_id),
        "last_seen_at": node.last_seen_at.isoformat(),
        "firmware_version": node.firmware_version,
    }


def get_home_node_health(session: Session, home_id: uuid.UUID) -> dict[str, Any]:
    nodes = session.exec(select(Node).where(Node.home_id == home_id)).all()
    healths = [check_node_health(session, n.id) for n in nodes]
    online = sum(1 for h in healths if h.get("status") == "online")
    return {
        "home_id": str(home_id),
        "nodes": healths,
        "summary": {
            "total": len(nodes),
            "online": online,
            "offline": len(nodes) - online,
        },
    }
