from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models import Node, utcnow

logger = structlog.get_logger(__name__)


@dataclass
class CommandBatch:
    batch_id: str
    home_id: uuid.UUID
    commands: list[dict[str, Any]]
    status: str = "pending"
    created_at: datetime = field(default_factory=utcnow)
    last_attempt_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 3


class CommandQueue:
    def __init__(self) -> None:
        self._pending: dict[str, CommandBatch] = {}
        self._max_attempts = 3

    def enqueue(
        self,
        home_id: uuid.UUID,
        commands: list[dict[str, Any]],
        batch_id: str | None = None,
    ) -> str:
        bid = batch_id or str(uuid.uuid4())
        batch = CommandBatch(
            batch_id=bid,
            home_id=home_id,
            commands=commands,
            created_at=utcnow(),
        )
        self._pending[bid] = batch
        logger.info(
            "command_batch_enqueued", batch_id=bid, home_id=str(home_id), count=len(commands)
        )
        return bid

    def get(self, batch_id: str) -> CommandBatch | None:
        return self._pending.get(batch_id)

    def mark_attempted(self, batch_id: str) -> None:
        batch = self._pending.get(batch_id)
        if batch:
            batch.attempts += 1
            batch.last_attempt_at = utcnow()

    def complete(self, batch_id: str) -> None:
        batch = self._pending.pop(batch_id, None)
        if batch:
            batch.status = "complete"
            logger.info("command_batch_complete", batch_id=batch_id, attempts=batch.attempts)

    def fail(self, batch_id: str) -> None:
        batch = self._pending.get(batch_id)
        if batch:
            if batch.attempts >= batch.max_attempts:
                self._pending.pop(batch_id, None)
                logger.error("command_batch_failed", batch_id=batch_id, attempts=batch.attempts)
            else:
                batch.status = "retry"
                logger.warning("command_batch_retry", batch_id=batch_id, attempt=batch.attempts)

    def get_pending_for_home(self, home_id: uuid.UUID) -> list[CommandBatch]:
        return [b for b in self._pending.values() if b.home_id == home_id]

    def clear_home(self, home_id: uuid.UUID) -> int:
        """Clear all pending batches for a home. Returns count cleared."""
        to_remove = [bid for bid, b in self._pending.items() if b.home_id == home_id]
        for bid in to_remove:
            self._pending.pop(bid, None)
        return len(to_remove)

    def stats(self) -> dict[str, Any]:
        by_home: dict[str, int] = {}
        for b in self._pending.values():
            hid = str(b.home_id)
            by_home[hid] = by_home.get(hid, 0) + 1
        return {
            "pending_count": len(self._pending),
            "by_home": by_home,
        }


_command_queue: CommandQueue | None = None


def get_command_queue() -> CommandQueue:
    global _command_queue
    if _command_queue is None:
        _command_queue = CommandQueue()
    return _command_queue


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
