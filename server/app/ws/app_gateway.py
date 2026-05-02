from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

import app.db as db_module
from app.models import Home
from app.services import coordinator as coord
from app.ws.device_gateway import push_command_batch

router = APIRouter()


def _parse_bearer(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


@router.websocket("/ws/app")
async def ws_app(websocket: WebSocket) -> None:
    token = _parse_bearer(websocket.headers.get("authorization")) or websocket.query_params.get(
        "token"
    )
    home_raw = (
        websocket.headers.get("x-tv-stretch-home")
        or websocket.query_params.get("home_id")
        or websocket.query_params.get("home")
    )
    if not token or not home_raw:
        await websocket.close(code=4401)
        return
    try:
        home_id = uuid.UUID(home_raw)
    except ValueError:
        await websocket.close(code=4400)
        return

    with Session(db_module.engine) as session:
        h = session.exec(
            select(Home).where(Home.id == home_id, Home.control_token == token)
        ).first()
        if h is None:
            await websocket.close(code=4401)
            return

    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("v") != 1:
                continue
            if msg.get("type") == "presence":
                rid_raw = msg.get("active_room_id")
                if not rid_raw:
                    continue
                try:
                    room_id = uuid.UUID(str(rid_raw))
                except ValueError:
                    continue
                cref = msg.get("content_ref")
                cref_s = str(cref) if cref is not None else None
                with Session(db_module.engine) as session:
                    if not coord.ensure_room_in_home(session, home_id, room_id):
                        continue
                    batch_id, cmds = coord.apply_handoff(
                        session,
                        home_id,
                        room_id,
                        content_ref=cref_s,
                        source="app_ws",
                    )
                await push_command_batch(home_id, cmds, batch_id=batch_id)
                await websocket.send_text(
                    json.dumps({"v": 1, "type": "handoff_applied", "batch_id": batch_id})
                )
            elif msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"v": 1, "type": "pong"}))
    except WebSocketDisconnect:
        pass
