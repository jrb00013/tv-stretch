from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

import app.db as db_module
from app.models import Home, Node, Room, SessionState
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
            msg_type = msg.get("type")
            if msg_type == "presence":
                rid_raw = msg.get("active_room_id")
                if not rid_raw:
                    continue
                try:
                    room_id = uuid.UUID(str(rid_raw))
                except ValueError:
                    continue
                cref = msg.get("content_ref")
                cref_s = str(cref) if cref is not None else None
                standby = msg.get("standby_others")
                standby_b = True if standby is None else bool(standby)
                with Session(db_module.engine) as session:
                    if not coord.ensure_room_in_home(session, home_id, room_id):
                        continue
                    batch_id, cmds = coord.apply_handoff(
                        session,
                        home_id,
                        room_id,
                        content_ref=cref_s,
                        source="app_ws",
                        standby_others=standby_b,
                    )
                await push_command_batch(home_id, cmds, batch_id=batch_id)
                await websocket.send_text(
                    json.dumps({"v": 1, "type": "handoff_applied", "batch_id": batch_id})
                )
            elif msg_type == "get_session":
                with Session(db_module.engine) as session:
                    st = session.get(SessionState, home_id)
                    out: dict = {"v": 1, "type": "session_state", "home_id": str(home_id)}
                    if st:
                        out["active_room_id"] = (
                            str(st.active_room_id) if st.active_room_id else None
                        )
                        out["content_ref"] = st.content_ref
                        out["updated_at"] = st.updated_at.isoformat()
                    else:
                        out["active_room_id"] = None
                        out["content_ref"] = None
                        out["updated_at"] = None
                await websocket.send_text(json.dumps(out))
            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"v": 1, "type": "pong"}))
            elif msg_type == "list_rooms":
                with Session(db_module.engine) as session:
                    rooms = session.exec(
                        select(Room).where(Room.home_id == home_id)
                    ).all()
                    await websocket.send_text(
                        json.dumps({
                            "v": 1,
                            "type": "room_list",
                            "rooms": [{"id": str(r.id), "name": r.name} for r in rooms],
                        })
                    )
            elif msg_type == "list_nodes":
                with Session(db_module.engine) as session:
                    nodes = session.exec(
                        select(Node).where(Node.home_id == home_id)
                    ).all()
                    await websocket.send_text(
                        json.dumps({
                            "v": 1,
                            "type": "node_list",
                            "nodes": [
                                {
                                    "id": str(n.id),
                                    "room_id": str(n.room_id),
                                    "name": n.name,
                                    "last_seen": n.last_seen_at.isoformat() if n.last_seen_at else None,
                                }
                                for n in nodes
                            ],
                        })
                    )
            elif msg_type == "subscribe_events":
                await websocket.send_text(
                    json.dumps({"v": 1, "type": "events_subscribed", "home_id": str(home_id)})
                )
    except WebSocketDisconnect:
        pass
