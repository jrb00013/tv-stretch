from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models import WebhookEndpoint, utcnow

logger = structlog.get_logger(__name__)

SIGNATURE_HEADER = "X-TV-Stretch-Signature"
TIMESTAMP_HEADER = "X-TV-Stretch-Timestamp"
EVENT_HEADER = "X-TV-Stretch-Event"
DELIVERY_HEADER = "X-TV-Stretch-Delivery"

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5
DEFAULT_TIMEOUT_SECONDS = 5.0

#: Events a subscription can listen for. ``*`` (empty ``events``) means all of them.
KNOWN_EVENTS = (
    "handoff",
    "power",
    "cec_key",
    "input_select",
    "standby_all",
    "handoff_suppressed",
    "command_batch_failed",
)


def parse_events(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def subscribes_to(endpoint: WebhookEndpoint, event: str) -> bool:
    """An endpoint with no event list receives everything."""
    events = parse_events(endpoint.events)
    return not events or event in events


def sign(secret: str, timestamp: str, body: str) -> str:
    """HMAC-SHA256 over ``timestamp.body``, as ``sha256=<hex>``."""
    digest = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify(secret: str, headers: dict[str, str], body: str) -> bool:
    """Receiver-side check: signature present, matching, and not stale.

    Bind the timestamp into the signed payload so a captured request cannot be replayed
    verbatim; the tolerance is deliberately short because these are live TV events.
    """
    signature = headers.get(SIGNATURE_HEADER) or headers.get(SIGNATURE_HEADER.lower())
    timestamp = headers.get(TIMESTAMP_HEADER) or headers.get(TIMESTAMP_HEADER.lower())
    if not signature or not timestamp:
        return False
    try:
        sent_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (TypeError, ValueError):
        return False
    if abs((utcnow() - sent_at).total_seconds()) > 300:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


def build_headers(secret: str, event: str, delivery_id: str, body: str) -> dict[str, str]:
    timestamp = str(int(utcnow().timestamp()))
    return {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign(secret, timestamp, body),
        TIMESTAMP_HEADER: timestamp,
        EVENT_HEADER: event,
        DELIVERY_HEADER: delivery_id,
    }


async def post_json(url: str, headers: dict[str, str], body: str, timeout: float) -> int:
    """POST with the stdlib so delivery needs no new runtime dependency."""
    request = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
    loop = asyncio.get_running_loop()

    def _do() -> int:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status)
        except urllib.error.HTTPError as e:
            return int(e.code)

    return await loop.run_in_executor(None, _do)


Sender = Callable[[str, dict[str, str], str, float], Awaitable[int]]


@dataclass
class DeliveryResult:
    ok: bool
    status: int | None = None
    error: str | None = None
    attempts: int = 0
    delivery_id: str = ""


@dataclass
class DispatcherState:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None


class WebhookDispatcher:
    """Background delivery with bounded retries.

    Deliveries are queued, never awaited by the request that triggered them: a slow or
    dead receiver must not add latency to a TV handoff.
    """

    def __init__(
        self,
        *,
        send: Sender | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._send: Sender = send or post_json
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def enqueue(self, home_id: uuid.UUID, event: str, payload: dict[str, Any]) -> None:
        self._queue.put_nowait((home_id, event, payload))

    async def deliver(
        self,
        session: Session,
        endpoint: WebhookEndpoint,
        event: str,
        payload: dict[str, Any],
    ) -> DeliveryResult:
        """Deliver one event, retrying transport errors and 5xx responses."""
        body = json.dumps(
            {
                "event": event,
                "home_id": str(endpoint.home_id),
                "sent_at": utcnow().isoformat(),
                "data": payload,
            },
            default=str,
        )
        delivery_id = str(uuid.uuid4())
        last_error: str | None = None
        status: int | None = None

        for attempt in range(1, self.max_attempts + 1):
            headers = build_headers(endpoint.secret, event, delivery_id, body)
            try:
                status = await self._send(endpoint.url, headers, body, self.timeout_seconds)
            except Exception as e:  # network failure: retry
                last_error = f"{type(e).__name__}: {e}"
            else:
                if 200 <= status < 300:
                    _record(session, endpoint, status, None, ok=True)
                    return DeliveryResult(
                        ok=True, status=status, attempts=attempt, delivery_id=delivery_id
                    )
                last_error = f"http_{status}"
                if status < 500:
                    # 4xx is the receiver's fault; retrying will not fix it.
                    break
            if attempt < self.max_attempts:
                await asyncio.sleep(self.backoff_seconds * (2 ** (attempt - 1)))

        _record(session, endpoint, status, last_error, ok=False)
        return DeliveryResult(
            ok=False,
            status=status,
            error=last_error,
            attempts=self.max_attempts,
            delivery_id=delivery_id,
        )

    async def dispatch(
        self, session: Session, home_id: uuid.UUID, event: str, payload: dict[str, Any]
    ) -> list[DeliveryResult]:
        """Deliver to every matching endpoint now, awaiting each delivery."""
        endpoints = [
            e
            for e in session.exec(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.home_id == home_id,
                    WebhookEndpoint.enabled == True,  # noqa: E712
                )
            ).all()
            if subscribes_to(e, event)
        ]
        return [await self.deliver(session, endpoint, event, payload) for endpoint in endpoints]

    async def run_once(self) -> bool:
        """Process one queued event. Returns False when the queue was empty."""
        try:
            home_id, event, payload = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return False
        try:
            import app.db as db_module

            with Session(db_module.engine) as session:
                await self.dispatch(session, home_id, event, payload)
        except Exception:
            logger.exception("webhook_delivery_failed", event_name=event)
        finally:
            self._queue.task_done()
        return True


async def webhook_worker(poll_seconds: float = 0.05) -> None:
    """Drain webhook deliveries until cancelled.

    Resolves the dispatcher on every pass so an injected dispatcher (tests) is picked
    up without restarting the app.
    """
    logger.info("webhook_worker_started")
    try:
        while True:
            dispatcher = get_dispatcher()
            if not await dispatcher.run_once():
                await asyncio.sleep(poll_seconds)
    except asyncio.CancelledError:
        logger.info("webhook_worker_stopped")
        raise


def _record(
    session: Session,
    endpoint: WebhookEndpoint,
    status: int | None,
    error: str | None,
    *,
    ok: bool,
) -> None:
    endpoint.last_delivery_at = utcnow()
    endpoint.last_status = status
    endpoint.last_error = error[:256] if error else None
    if ok:
        endpoint.success_count += 1
        endpoint.failure_count = 0
    else:
        endpoint.failure_count += 1
    session.add(endpoint)
    session.commit()


def emit(session: Session, home_id: uuid.UUID, event: str, payload: dict[str, Any]) -> int:
    """Queue an event for every subscriber. Returns how many endpoints were queued."""
    matching = [
        e
        for e in session.exec(
            select(WebhookEndpoint).where(
                WebhookEndpoint.home_id == home_id,
                WebhookEndpoint.enabled == True,  # noqa: E712
            )
        ).all()
        if subscribes_to(e, event)
    ]
    if not matching:
        return 0
    get_dispatcher().enqueue(home_id, event, payload)
    logger.info(
        "webhook_event_queued", event_name=event, home_id=str(home_id), endpoints=len(matching)
    )
    return len(matching)


_dispatcher: WebhookDispatcher | None = None


def get_dispatcher() -> WebhookDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = WebhookDispatcher()
    return _dispatcher


def set_dispatcher(dispatcher: WebhookDispatcher | None) -> None:
    """Install a dispatcher (tests inject one with a fake sender)."""
    global _dispatcher
    _dispatcher = dispatcher
