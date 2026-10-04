from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

import app.db as db_module
from app.models import EventLog, Node, utcnow
from app.services.command_queue import CommandBatch, get_command_queue

router = APIRouter()


@dataclass
class DeviceConn:
    websocket: WebSocket
    node_id: uuid.UUID
    home_id: uuid.UUID


class DeviceHub:
    def __init__(self) -> None:
        self._by_home: dict[uuid.UUID, list[DeviceConn]] = {}

    async def connect(self, home_id: uuid.UUID, node_id: uuid.UUID, ws: WebSocket) -> DeviceConn:
        await ws.accept()
        dc = DeviceConn(websocket=ws, node_id=node_id, home_id=home_id)
        self._by_home.setdefault(home_id, []).append(dc)
        return dc

    def disconnect(self, dc: DeviceConn) -> None:
        lst = self._by_home.get(dc.home_id, [])
        if dc in lst:
            lst.remove(dc)

    def connected_node_ids(self, home_id: uuid.UUID) -> list[str]:
        """Node ids currently connected for a home (the delivery target set)."""
        return [str(c.node_id) for c in self._by_home.get(home_id, [])]

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {"homes": {}}
        for hid, conns in self._by_home.items():
            out["homes"][str(hid)] = {
                "device_connections": len(conns),
                "nodes": [str(c.node_id) for c in conns],
            }
        return out

    async def broadcast_json(self, home_id: uuid.UUID, payload: dict[str, Any]) -> None:
        dead: list[DeviceConn] = []
        text = json.dumps(payload)
        for dc in self._by_home.get(home_id, []):
            try:
                await dc.websocket.send_text(text)
            except Exception:
                dead.append(dc)
        for dc in dead:
            self.disconnect(dc)


hub = DeviceHub()


def _parse_bearer(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


@router.websocket("/ws/device")
async def ws_device(websocket: WebSocket) -> None:
    token = _parse_bearer(websocket.headers.get("authorization")) or (
        websocket.query_params.get("token") or websocket.query_params.get("api_key")
    )
    home_hdr = websocket.headers.get("x-tv-stretch-home") or websocket.query_params.get("home_id")
    if not token or not home_hdr:
        await websocket.close(code=4401)
        return
    try:
        home_id = uuid.UUID(home_hdr)
    except ValueError:
        await websocket.close(code=4400)
        return

    with Session(db_module.engine) as session:
        node = session.exec(select(Node).where(Node.api_key == token)).first()
        if node is None or node.home_id != home_id:
            await websocket.close(code=4401)
            return
        node_id = node.id

    dc = await hub.connect(home_id, node_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "hello":
                with Session(db_module.engine) as s:
                    n = s.get(Node, node_id)
                    if n:
                        n.last_seen_at = utcnow()
                        fv = (
                            msg.get("node", {}).get("fw")
                            if isinstance(msg.get("node"), dict)
                            else None
                        )
                        if isinstance(fv, str):
                            n.firmware_version = fv
                        s.add(n)
                        s.commit()
            elif mtype == "heartbeat":
                with Session(db_module.engine) as s:
                    n = s.get(Node, node_id)
                    if n:
                        n.last_seen_at = utcnow()
                        s.add(n)
                        s.commit()
            elif mtype == "event":
                payload_raw = msg.get("payload")
                if isinstance(payload_raw, dict | list):
                    pl = json.dumps(payload_raw)
                elif isinstance(payload_raw, str):
                    pl = json.dumps({"text": payload_raw})
                else:
                    pl = json.dumps(msg)
                with Session(db_module.engine) as s:
                    s.add(
                        EventLog(
                            home_id=home_id,
                            kind="device_event",
                            payload_json=pl,
                        )
                    )
                    s.commit()
            elif mtype == "ack":
                bid = msg.get("batch_id")
                ack_ok = msg.get("ok")
                if isinstance(bid, str) and bid:
                    get_command_queue().record_ack(
                        bid,
                        str(node_id),
                        ok=bool(ack_ok),
                        error=str(msg.get("error")) if msg.get("error") else None,
                    )
                with Session(db_module.engine) as s:
                    s.add(
                        EventLog(
                            home_id=home_id,
                            kind="device_ack",
                            payload_json=json.dumps(
                                {
                                    "node_id": str(node_id),
                                    "batch_id": bid,
                                    "ok": ack_ok,
                                }
                            ),
                        )
                    )
                    s.commit()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(dc)


async def push_command_batch(
    home_id: uuid.UUID,
    commands: list[dict[str, Any]],
    *,
    batch_id: str | None = None,
    track: bool = True,
) -> str:
    """Broadcast a ``command_batch`` and, by default, track it for ack/retry."""
    bid = batch_id or str(uuid.uuid4())
    if track:
        queue = get_command_queue()
        queue.enqueue(
            home_id,
            commands,
            batch_id=bid,
            expected_nodes=hub.connected_node_ids(home_id),
        )
        queue.mark_attempted(bid)
    await hub.broadcast_json(
        home_id,
        {"v": 1, "type": "command_batch", "batch_id": bid, "commands": commands},
    )
    return bid


async def redeliver_command_batch(batch: CommandBatch) -> str:
    """Re-send an already tracked batch without re-enqueueing it."""
    return await push_command_batch(
        batch.home_id,
        batch.commands,
        batch_id=batch.batch_id,
        track=False,
    )
