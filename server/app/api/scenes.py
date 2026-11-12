from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

from app.models import Room, ScenePreset
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import coordinator as coord
from app.services import quiet_hours as qh
from app.services import webhooks as wh
from app.services.mqtt import get_mqtt
from app.ws.app_gateway import app_hub
from app.ws.device_gateway import push_command_batch

router = APIRouter(prefix="/scenes", tags=["scenes"])
logger = structlog.get_logger(__name__)


class SceneCreate(BaseModel):
    name: str
    room_id: uuid.UUID
    content_ref: str | None = None
    standby_others: bool = True


class SceneUpdate(BaseModel):
    name: str | None = None
    room_id: uuid.UUID | None = None
    content_ref: str | None = None
    standby_others: bool | None = None


class SceneRead(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    name: str
    room_id: uuid.UUID
    content_ref: str | None = None
    standby_others: bool
    created_at: str

    @classmethod
    def from_model(cls, s: ScenePreset) -> SceneRead:
        return cls(
            id=s.id,
            home_id=s.home_id,
            name=s.name,
            room_id=s.room_id,
            content_ref=s.content_ref,
            standby_others=s.standby_others,
            created_at=s.created_at.isoformat(),
        )


class SceneApplyResult(BaseModel):
    ok: bool
    batch_id: str | None = None
    commands: list[dict] = []
    suppressed: bool = False
    reason: str | None = None
    minutes_remaining: int | None = None


def _get_owned_scene(auth: AuthenticatedHome, scene_id: uuid.UUID) -> ScenePreset:
    s = auth.session.get(ScenePreset, scene_id)
    if s is None or s.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="scene not found")
    return s


def _ensure_room(auth: AuthenticatedHome, room_id: uuid.UUID) -> None:
    r = auth.session.get(Room, room_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="room not in home")


@router.post("", response_model=SceneRead)
@limiter.limit("20/minute")
def create_scene(
    request: Request,
    body: SceneCreate,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> SceneRead:
    _ensure_room(auth, body.room_id)
    s = ScenePreset(
        home_id=auth.home.id,
        name=body.name,
        room_id=body.room_id,
        content_ref=body.content_ref,
        standby_others=body.standby_others,
    )
    auth.session.add(s)
    auth.session.commit()
    auth.session.refresh(s)
    return SceneRead.from_model(s)


@router.get("", response_model=list[SceneRead])
def list_scenes(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[SceneRead]:
    rows = list(
        auth.session.exec(select(ScenePreset).where(ScenePreset.home_id == auth.home.id)).all()
    )
    return [SceneRead.from_model(s) for s in rows]


@router.get("/{scene_id}", response_model=SceneRead)
def get_scene(
    scene_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> SceneRead:
    return SceneRead.from_model(_get_owned_scene(auth, scene_id))


@router.patch("/{scene_id}", response_model=SceneRead)
def update_scene(
    scene_id: uuid.UUID,
    body: SceneUpdate,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> SceneRead:
    s = _get_owned_scene(auth, scene_id)
    if body.name is not None:
        s.name = body.name
    if body.room_id is not None:
        _ensure_room(auth, body.room_id)
        s.room_id = body.room_id
    if body.content_ref is not None:
        s.content_ref = body.content_ref
    if body.standby_others is not None:
        s.standby_others = body.standby_others
    auth.session.add(s)
    auth.session.commit()
    auth.session.refresh(s)
    return SceneRead.from_model(s)


@router.delete("/{scene_id}", status_code=204)
def delete_scene(
    scene_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> None:
    s = _get_owned_scene(auth, scene_id)
    auth.session.delete(s)
    auth.session.commit()


@router.post("/{scene_id}/apply", response_model=SceneApplyResult)
@limiter.limit("10/minute")
async def apply_scene(
    request: Request,
    scene_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
    override_quiet_hours: bool = False,
) -> SceneApplyResult:
    s = _get_owned_scene(auth, scene_id)
    if not coord.ensure_room_in_home(auth.session, auth.home.id, s.room_id):
        raise HTTPException(status_code=404, detail="room not in home")

    if not override_quiet_hours:
        quiet = qh.evaluate(auth.session, auth.home.id)
        if quiet.suppressed:
            qh.log_suppressed(auth.session, auth.home.id, s.room_id, quiet, source="scene")
            wh.emit(
                auth.session,
                auth.home.id,
                "handoff_suppressed",
                {
                    "room_id": str(s.room_id),
                    "reason": quiet.reason,
                    "minutes_remaining": quiet.minutes_remaining,
                    "source": "scene",
                    "scene_id": str(s.id),
                },
            )
            return SceneApplyResult(
                ok=False,
                suppressed=True,
                reason=quiet.reason,
                minutes_remaining=quiet.minutes_remaining,
            )

    logger.info("scene_apply", home_id=str(auth.home.id), scene_id=str(scene_id))
    batch_id, cmds = coord.apply_handoff(
        auth.session,
        auth.home.id,
        s.room_id,
        content_ref=s.content_ref,
        source="scene",
        standby_others=s.standby_others,
    )
    await push_command_batch(auth.home.id, cmds, batch_id=batch_id)

    get_mqtt().publish(
        "handoff",
        {
            "room_id": str(s.room_id),
            "batch_id": batch_id,
            "source": "scene",
            "content_ref": s.content_ref,
            "standby_others": s.standby_others,
            "scene_id": str(s.id),
        },
        home_id=auth.home.id,
    )
    await app_hub.broadcast_json(
        auth.home.id,
        {
            "v": 1,
            "type": "handoff",
            "room_id": str(s.room_id),
            "batch_id": batch_id,
            "source": "scene",
            "scene_id": str(s.id),
        },
    )
    wh.emit(
        auth.session,
        auth.home.id,
        "handoff",
        {
            "batch_id": batch_id,
            "room_id": str(s.room_id),
            "content_ref": s.content_ref,
            "source": "scene",
            "scene_id": str(s.id),
        },
    )

    logger.info("scene_apply_completed", batch_id=batch_id, command_count=len(cmds))
    return SceneApplyResult(ok=True, batch_id=batch_id, commands=cmds)
