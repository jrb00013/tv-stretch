from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import desc
from sqlmodel import Session, select

from app.models import EventLog, Node, SessionState, utcnow
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import content as content_service
from app.services import coordinator as coord
from app.services import idempotency as idem
from app.services import quiet_hours as qh
from app.services import webhooks as wh
from app.services.command_queue import (
    check_node_health,
    get_command_queue,
    get_home_node_health,
)
from app.services.coordinator import build_cec_key_command, build_input_select, build_power_command
from app.services.mqtt import get_mqtt
from app.ws.app_gateway import app_hub
from app.ws.device_gateway import push_command_batch

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = structlog.get_logger(__name__)


def _as_utc(value: datetime | None) -> datetime | None:
    """Read naive timestamps as UTC so filters compare against aware columns."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _claim_idempotency(
    request: Request, auth: AuthenticatedHome, endpoint: str, body: BaseModel
) -> tuple[str | None, idem.IdempotencyDecision]:
    """Validate and claim the ``Idempotency-Key`` for a mutating endpoint."""
    try:
        key = idem.read_key(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        decision = idem.begin(
            auth.session, auth.home.id, endpoint, key, body.model_dump(mode="json")
        )
    except idem.IdempotencyConflict as e:
        raise HTTPException(status_code=409, detail=e.detail) from e
    return key, decision


def _finish_idempotency(
    session: Session, home_id: uuid.UUID, key: str | None, result: BaseModel
) -> None:
    idem.complete(session, home_id, key, result.model_dump(mode="json"))


class HandoffBody(BaseModel):
    active_room_id: uuid.UUID
    content_ref: str | None = None
    standby_others: bool = True
    #: A person explicitly asking for a TV may bypass quiet hours; sensor-driven
    #: presence reporting may not.
    override_quiet_hours: bool = False


class HandoffResult(BaseModel):
    ok: bool
    batch_id: str | None = None
    commands: list[dict] = []
    #: True when the handoff was deliberately not performed (e.g. quiet hours).
    suppressed: bool = False
    reason: str | None = None
    minutes_remaining: int | None = None


class SessionStateDetail(BaseModel):
    home_id: uuid.UUID
    active_room_id: uuid.UUID | None = None
    content_ref: str | None = None
    updated_at: str

    @classmethod
    def from_model(cls, st: SessionState) -> SessionStateDetail:
        return cls(
            home_id=st.home_id,
            active_room_id=st.active_room_id,
            content_ref=st.content_ref,
            updated_at=st.updated_at.isoformat(),
        )


class HomeHealth(BaseModel):
    home_id: uuid.UUID
    nodes: list[dict]
    summary: dict


class BatchList(BaseModel):
    batches: list[dict]
    summary: dict


@router.post("/handoff", response_model=HandoffResult)
@limiter.limit("10/minute")
async def handoff(
    request: Request,
    response: Response,
    body: HandoffBody,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HandoffResult:
    key, decision = _claim_idempotency(request, auth, "handoff", body)
    if decision.action == "replay":
        response.headers[idem.REPLAY_HEADER] = "true"
        return HandoffResult(**decision.response)

    logger.info("handoff_request", home_id=str(auth.home.id), room_id=str(body.active_room_id))
    if not coord.ensure_room_in_home(auth.session, auth.home.id, body.active_room_id):
        logger.warning("handoff_room_not_found", room_id=str(body.active_room_id))
        raise HTTPException(status_code=404, detail="room not in home")

    if not body.override_quiet_hours:
        quiet = qh.evaluate(auth.session, auth.home.id)
        if quiet.suppressed:
            qh.log_suppressed(auth.session, auth.home.id, body.active_room_id, quiet, source="api")
            result = HandoffResult(
                ok=False,
                suppressed=True,
                reason=quiet.reason,
                minutes_remaining=quiet.minutes_remaining,
            )
            wh.emit(
                auth.session,
                auth.home.id,
                "handoff_suppressed",
                {
                    "room_id": str(body.active_room_id),
                    "reason": quiet.reason,
                    "minutes_remaining": quiet.minutes_remaining,
                    "source": "api",
                },
            )
            _finish_idempotency(auth.session, auth.home.id, key, result)
            return result

    batch_id, cmds = coord.apply_handoff(
        auth.session,
        auth.home.id,
        body.active_room_id,
        content_ref=body.content_ref,
        source="api",
        standby_others=body.standby_others,
    )
    await push_command_batch(auth.home.id, cmds, batch_id=batch_id)

    get_mqtt().publish(
        "handoff",
        {
            "room_id": str(body.active_room_id),
            "batch_id": batch_id,
            "source": "api",
            "content_ref": body.content_ref,
            "standby_others": body.standby_others,
        },
        home_id=auth.home.id,
    )
    await app_hub.broadcast_json(
        auth.home.id,
        {
            "v": 1,
            "type": "handoff",
            "room_id": str(body.active_room_id),
            "batch_id": batch_id,
            "source": "api",
        },
    )

    wh.emit(
        auth.session,
        auth.home.id,
        "handoff",
        {
            "batch_id": batch_id,
            "room_id": str(body.active_room_id),
            "content_ref": body.content_ref,
            "source": "api",
        },
    )
    logger.info("handoff_completed", batch_id=batch_id, command_count=len(cmds))
    result = HandoffResult(ok=True, batch_id=batch_id, commands=cmds)
    _finish_idempotency(auth.session, auth.home.id, key, result)
    return result


@router.get("", response_model=SessionStateDetail | None)
def read_session_state(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> SessionStateDetail | None:
    """Get current session state for the home (active room and content ref)."""
    st = auth.session.get(SessionState, auth.home.id)
    if st:
        return SessionStateDetail.from_model(st)
    return None


@router.get("/by-room/{room_id}", response_model=SessionStateDetail | None)
def get_session_by_room(
    room_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> SessionStateDetail | None:
    """Get session state if the given room is the active room."""
    st = auth.session.get(SessionState, auth.home.id)
    if st and st.active_room_id == room_id:
        return SessionStateDetail.from_model(st)
    return None


@router.get("/events", response_model=list[dict])
def list_events(
    request: Request,
    response: Response,
    limit: int = Query(50, ge=1, le=500),
    kind: str | None = Query(None, description="Filter by event kind"),
    since: datetime | None = Query(None, description="Only events at or after this ISO-8601 time"),
    until: datetime | None = Query(None, description="Only events before this ISO-8601 time"),
    cursor: datetime | None = Query(
        None, description="Keyset cursor: continue strictly before this event time"
    ),
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[dict]:
    """Recent events, newest first.

    Pagination is keyset-based to stay stable while new events arrive: pass the
    ``X-Next-Cursor`` header back as ``cursor`` to walk further back. Times without a
    timezone are read as UTC.
    """
    stmt = select(EventLog).where(EventLog.home_id == auth.home.id)
    if kind:
        stmt = stmt.where(EventLog.kind == kind)
    since_utc = _as_utc(since)
    until_utc = _as_utc(until)
    cursor_utc = _as_utc(cursor)
    if since_utc and until_utc and since_utc > until_utc:
        raise HTTPException(status_code=422, detail="since must not be after until")
    if since_utc:
        stmt = stmt.where(EventLog.created_at >= since_utc)
    if until_utc:
        stmt = stmt.where(EventLog.created_at < until_utc)
    if cursor_utc:
        stmt = stmt.where(EventLog.created_at < cursor_utc)

    stmt = stmt.order_by(desc(EventLog.created_at)).limit(limit)
    rows = list(auth.session.exec(stmt).all())
    if rows and len(rows) == limit:
        # "Z" instead of "+00:00": a raw "+" decodes to a space in a query string, which
        # would make the cursor unusable when copied straight from the header.
        response.headers["X-Next-Cursor"] = _as_utc(rows[-1].created_at).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
    return [
        {
            "id": str(r.id),
            "kind": r.kind,
            "payload": r.payload_json,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/events/kinds", response_model=list[str])
def list_event_kinds(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[str]:
    stmt = select(EventLog.kind).where(EventLog.home_id == auth.home.id).distinct()
    rows = list(auth.session.exec(stmt).all())
    return sorted(set(rows))


@router.delete("/events", status_code=204)
@limiter.limit("10/minute")
def clear_events(
    request: Request,
    response: Response,
    older_than_seconds: int | None = Query(
        None, ge=1, description="Delete only events older than this many seconds"
    ),
    before: datetime | None = Query(
        None, description="Delete only events before this ISO-8601 time"
    ),
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> None:
    """Delete events.

    With no arguments this clears the whole log (previous behaviour). Pass
    ``older_than_seconds`` or ``before`` to prune instead; the number of deleted
    rows comes back in the ``X-Deleted-Count`` header.
    """
    stmt = select(EventLog).where(EventLog.home_id == auth.home.id)
    cutoff = _as_utc(before)
    if older_than_seconds is not None:
        age_cutoff = utcnow() - timedelta(seconds=older_than_seconds)
        cutoff = age_cutoff if cutoff is None else min(cutoff, age_cutoff)
    if cutoff is not None:
        stmt = stmt.where(EventLog.created_at < cutoff)
    else:
        logger.info("event_log_cleared", home_id=str(auth.home.id))

    rows = list(auth.session.exec(stmt).all())
    for r in rows:
        auth.session.delete(r)
    auth.session.commit()
    response.headers["X-Deleted-Count"] = str(len(rows))
    logger.info(
        "event_log_pruned",
        home_id=str(auth.home.id),
        deleted=len(rows),
        cutoff=cutoff.isoformat() if cutoff else None,
    )


@router.get("/health", response_model=HomeHealth)
def home_health(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HomeHealth:
    health = get_home_node_health(auth.session, auth.home.id)
    return HomeHealth(
        home_id=auth.home.id,
        nodes=health["nodes"],
        summary=health["summary"],
    )


@router.get("/nodes/{node_id}/health", response_model=dict)
def node_health(
    node_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> dict:
    node = auth.session.get(Node, node_id)
    if not node or node.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="node not found")
    return check_node_health(auth.session, node_id)


class NowPlaying(BaseModel):
    """What the house is currently pointed at, resolved against the catalogue."""

    home_id: uuid.UUID
    active_room_id: uuid.UUID | None = None
    content_ref: str | None = None
    content: dict | None = None
    playing_since: str | None = None


@router.get("/now-playing", response_model=NowPlaying)
def now_playing(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> NowPlaying:
    """Current session plus the catalogue entry for its ``content_ref`` (if known)."""
    st = auth.session.get(SessionState, auth.home.id)
    if st is None or st.active_room_id is None:
        return NowPlaying(home_id=auth.home.id)
    item = (
        content_service.find_by_ref(auth.session, auth.home.id, st.content_ref)
        if st.content_ref
        else None
    )
    return NowPlaying(
        home_id=auth.home.id,
        active_room_id=st.active_room_id,
        content_ref=st.content_ref,
        content=(
            {
                "id": str(item.id),
                "ref": item.ref,
                "title": item.title,
                "source": item.source,
                "kind": item.kind,
                "duration_seconds": item.duration_seconds,
            }
            if item
            else None
        ),
        playing_since=st.updated_at.isoformat(),
    )


@router.get("/batches", response_model=BatchList)
def list_command_batches(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> BatchList:
    """In-flight and dead-lettered ``command_batch`` deliveries for this home."""
    queue = get_command_queue()
    batches = sorted(
        queue.get_pending_for_home(auth.home.id)
        + queue.get_dead_letters_for_home(auth.home.id)
        + queue.get_completed_for_home(auth.home.id),
        key=lambda b: b.created_at,
        reverse=True,
    )
    return BatchList(batches=[b.to_dict() for b in batches], summary=queue.stats())


@router.get("/batches/{batch_id}", response_model=dict)
def get_command_batch(
    batch_id: str,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> dict:
    batch = get_command_queue().get(batch_id)
    if batch is None or batch.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="batch not found")
    return batch.to_dict()


class PowerControl(BaseModel):
    room_id: uuid.UUID
    power: bool


class CecKeyControl(BaseModel):
    room_id: uuid.UUID
    key: str


class InputSelect(BaseModel):
    room_id: uuid.UUID
    source: str


@router.post("/power", response_model=HandoffResult)
@limiter.limit("10/minute")
async def power_control(
    request: Request,
    response: Response,
    body: PowerControl,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HandoffResult:
    key, decision = _claim_idempotency(request, auth, "power", body)
    if decision.action == "replay":
        response.headers[idem.REPLAY_HEADER] = "true"
        return HandoffResult(**decision.response)

    if not coord.ensure_room_in_home(auth.session, auth.home.id, body.room_id):
        raise HTTPException(status_code=404, detail="room not in home")
    cmd = build_power_command(body.power, body.room_id)
    batch_id = str(uuid.uuid4())
    await push_command_batch(auth.home.id, [cmd], batch_id=batch_id)
    auth.session.add(
        EventLog(
            home_id=auth.home.id,
            kind="power_control",
            payload_json=json.dumps(
                {"room_id": str(body.room_id), "power": body.power, "batch_id": batch_id}
            ),
        )
    )
    auth.session.commit()

    get_mqtt().publish(
        "power",
        {"room_id": str(body.room_id), "power": body.power, "batch_id": batch_id},
        home_id=auth.home.id,
    )
    await app_hub.broadcast_json(
        auth.home.id,
        {
            "v": 1,
            "type": "power_control",
            "room_id": str(body.room_id),
            "power": body.power,
            "batch_id": batch_id,
        },
    )

    result = HandoffResult(ok=True, batch_id=batch_id, commands=[cmd])
    wh.emit(
        auth.session,
        auth.home.id,
        "power",
        {"batch_id": batch_id, "room_id": str(body.room_id), "power": body.power},
    )
    _finish_idempotency(auth.session, auth.home.id, key, result)
    return result


@router.post("/cec-key", response_model=HandoffResult)
@limiter.limit("20/minute")
async def cec_key_control(
    request: Request,
    response: Response,
    body: CecKeyControl,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HandoffResult:
    key, decision = _claim_idempotency(request, auth, "cec-key", body)
    if decision.action == "replay":
        response.headers[idem.REPLAY_HEADER] = "true"
        return HandoffResult(**decision.response)

    if not coord.ensure_room_in_home(auth.session, auth.home.id, body.room_id):
        raise HTTPException(status_code=404, detail="room not in home")
    cmd = build_cec_key_command(body.key, body.room_id)
    batch_id = str(uuid.uuid4())
    await push_command_batch(auth.home.id, [cmd], batch_id=batch_id)
    auth.session.add(
        EventLog(
            home_id=auth.home.id,
            kind="cec_key",
            payload_json=json.dumps(
                {"room_id": str(body.room_id), "key": body.key, "batch_id": batch_id}
            ),
        )
    )
    auth.session.commit()

    get_mqtt().publish(
        "cec_key",
        {"room_id": str(body.room_id), "key": body.key, "batch_id": batch_id},
        home_id=auth.home.id,
    )
    await app_hub.broadcast_json(
        auth.home.id,
        {
            "v": 1,
            "type": "cec_key",
            "room_id": str(body.room_id),
            "key": body.key,
            "batch_id": batch_id,
        },
    )

    result = HandoffResult(ok=True, batch_id=batch_id, commands=[cmd])
    wh.emit(
        auth.session,
        auth.home.id,
        "cec_key",
        {"batch_id": batch_id, "room_id": str(body.room_id), "key": body.key},
    )
    _finish_idempotency(auth.session, auth.home.id, key, result)
    return result


@router.post("/input-select", response_model=HandoffResult)
@limiter.limit("10/minute")
async def input_select_control(
    request: Request,
    response: Response,
    body: InputSelect,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HandoffResult:
    key, decision = _claim_idempotency(request, auth, "input-select", body)
    if decision.action == "replay":
        response.headers[idem.REPLAY_HEADER] = "true"
        return HandoffResult(**decision.response)

    if not coord.ensure_room_in_home(auth.session, auth.home.id, body.room_id):
        raise HTTPException(status_code=404, detail="room not in home")
    cmd = build_input_select(body.source, body.room_id)
    batch_id = str(uuid.uuid4())
    await push_command_batch(auth.home.id, [cmd], batch_id=batch_id)
    auth.session.add(
        EventLog(
            home_id=auth.home.id,
            kind="input_select",
            payload_json=json.dumps(
                {"room_id": str(body.room_id), "source": body.source, "batch_id": batch_id}
            ),
        )
    )
    auth.session.commit()

    get_mqtt().publish(
        "input_select",
        {"room_id": str(body.room_id), "source": body.source, "batch_id": batch_id},
        home_id=auth.home.id,
    )
    await app_hub.broadcast_json(
        auth.home.id,
        {
            "v": 1,
            "type": "input_select",
            "room_id": str(body.room_id),
            "source": body.source,
            "batch_id": batch_id,
        },
    )

    result = HandoffResult(ok=True, batch_id=batch_id, commands=[cmd])
    wh.emit(
        auth.session,
        auth.home.id,
        "input_select",
        {"batch_id": batch_id, "room_id": str(body.room_id), "source": body.source},
    )
    _finish_idempotency(auth.session, auth.home.id, key, result)
    return result
