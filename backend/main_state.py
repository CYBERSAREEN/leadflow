import json
import logging
from typing import Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)

active_connections: Set[WebSocket] = set()


async def broadcast_message(data: dict):
    if not active_connections:
        return
    dead = set()
    for ws in list(active_connections):
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            dead.add(ws)
    for ws in dead:
        active_connections.discard(ws)
