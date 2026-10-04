from __future__ import annotations

import asyncio
import json
import uuid

import structlog
from sqlmodel import Session

import app.db as db_module
from app.models import EventLog, utcnow
from app.services.command_queue import CommandBatch, CommandQueue, get_command_queue
from app.ws.device_gateway import redeliver_command_batch

logger = structlog.get_logger(__name__)

#: How often the worker looks for batches whose retry window has elapsed.
RETRY_TICK_SECONDS = 1.0


def log_batch_event(home_id: uuid.UUID, batch_id: str, kind: str, **payload: object) -> None:
    """Persist a batch lifecycle transition to the home event log.

    The live queue is in-memory and does not survive a restart; the event log
    keeps the retry / dead-letter trail.
    """
    with Session(db_module.engine) as session:
        session.add(
            EventLog(
                home_id=home_id,
                kind=kind,
                payload_json=json.dumps({"batch_id": batch_id, **payload}),
            )
        )
        session.commit()
    logger.info("command_batch_event", kind=kind, batch_id=batch_id, **payload)


async def retry_due_batches(queue: CommandQueue | None = None) -> int:
    """Run one redelivery pass. Returns how many batches were re-sent."""
    queue = queue or get_command_queue()
    redelivered = 0
    for batch in queue.due_retries(utcnow()):
        queue.mark_attempted(batch.batch_id)
        await redeliver_command_batch(batch)
        log_batch_event(
            batch.home_id,
            batch.batch_id,
            "command_batch_retry",
            attempt=batch.attempts,
        )
        redelivered += 1
    return redelivered


async def retry_loop(tick_seconds: float = RETRY_TICK_SECONDS) -> None:
    """Redeliver command batches whose retry window elapsed, until cancelled."""
    logger.info("command_retry_worker_started", tick_seconds=tick_seconds)
    try:
        while True:
            await asyncio.sleep(tick_seconds)
            await retry_due_batches()
    except asyncio.CancelledError:
        logger.info("command_retry_worker_stopped")
        raise


__all__ = [
    "RETRY_TICK_SECONDS",
    "CommandBatch",
    "log_batch_event",
    "retry_due_batches",
    "retry_loop",
]
