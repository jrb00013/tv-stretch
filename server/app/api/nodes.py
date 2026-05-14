from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

from app.models import Node, Room
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter

router = APIRouter(prefix="/nodes", tags=["nodes"])


class NodeRegister(BaseModel):
    room_id: uuid.UUID
    name: str = "node"


class NodeRegistered(BaseModel):
    node_id: uuid.UUID
    api_key: str


class NodeRead(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    room_id: uuid.UUID
    name: str
    last_seen_at: str | None = None
    firmware_version: str | None = None
    cec_enabled: bool = True
    physical_address: int = 0x2000
    config_json: dict | None = None


class NodeUpdate(BaseModel):
    name: str | None = None
    cec_enabled: bool | None = None
    physical_address: int | None = None
    config_json: dict | None = None


def _node_to_read(n: Node) -> NodeRead:
    import json
    cfg = None
    if n.config_json:
        try:
            cfg = json.loads(n.config_json)
        except json.JSONDecodeError:
            pass
    return NodeRead(
        id=n.id,
        home_id=n.home_id,
        room_id=n.room_id,
        name=n.name,
        last_seen_at=n.last_seen_at.isoformat() if n.last_seen_at else None,
        firmware_version=n.firmware_version,
        cec_enabled=n.cec_enabled,
        physical_address=n.physical_address,
        config_json=cfg,
    )


@router.post("/register", response_model=NodeRegistered)
@limiter.limit("10/minute")
def register_node(
    request: Request,
    body: NodeRegister,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> NodeRegistered:
    r = auth.session.get(Room, body.room_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="room not found")

    existing = auth.session.exec(
        select(Node).where(Node.home_id == auth.home.id, Node.room_id == body.room_id)
    ).first()
    if existing:
        raise HTTPException(
            status_code=409, detail="node already exists for this room; delete first"
        )

    api_key = secrets.token_urlsafe(32)
    n = Node(home_id=auth.home.id, room_id=body.room_id, name=body.name, api_key=api_key)
    auth.session.add(n)
    auth.session.commit()
    auth.session.refresh(n)
    return NodeRegistered(node_id=n.id, api_key=api_key)


@router.get("", response_model=list[NodeRead])
def list_nodes(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[NodeRead]:
    nodes = auth.session.exec(select(Node).where(Node.home_id == auth.home.id)).all()
    return [_node_to_read(n) for n in nodes]


@router.get("/{node_id}", response_model=NodeRead)
def get_node(
    node_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> NodeRead:
    n = auth.session.get(Node, node_id)
    if n is None or n.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="node not found")
    return _node_to_read(n)


@router.patch("/{node_id}", response_model=NodeRead)
def patch_node(
    node_id: uuid.UUID,
    body: NodeUpdate,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> NodeRead:
    import json
    n = auth.session.get(Node, node_id)
    if n is None or n.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="node not found")
    if body.name is not None:
        n.name = body.name
    if body.cec_enabled is not None:
        n.cec_enabled = body.cec_enabled
    if body.physical_address is not None:
        n.physical_address = body.physical_address
    if body.config_json is not None:
        n.config_json = json.dumps(body.config_json)
    auth.session.add(n)
    auth.session.commit()
    auth.session.refresh(n)
    return _node_to_read(n)


@router.delete("/{node_id}", status_code=204)
def delete_node(
    node_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> None:
    n = auth.session.get(Node, node_id)
    if n is None or n.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="node not found")
    auth.session.delete(n)
    auth.session.commit()


class NodeBatchDelete(BaseModel):
    node_ids: list[uuid.UUID]


class NodeBatchDeleteResult(BaseModel):
    deleted: int
    failed: list[str]


@router.post("/bulk-delete", response_model=NodeBatchDeleteResult)
@limiter.limit("10/minute")
def bulk_delete_nodes(
    request: Request,
    body: NodeBatchDelete,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> NodeBatchDeleteResult:
    """
    Delete multiple nodes at once.

    Returns the count of successfully deleted nodes and list of failures.
    """
    deleted = 0
    failed = []
    for node_id in body.node_ids:
        n = auth.session.get(Node, node_id)
        if n is None or n.home_id != auth.home.id:
            failed.append(f"{node_id}: not found")
            continue
        auth.session.delete(n)
        deleted += 1
    auth.session.commit()
    return NodeBatchDeleteResult(deleted=deleted, failed=failed)
