"""WebSocket endpoint for real-time collaboration."""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class ConnectionManager:
    """Tracks active WebSocket connections per deal for real-time updates."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, deal_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if deal_id not in self._connections:
            self._connections[deal_id] = []
        self._connections[deal_id].append(websocket)

    def disconnect(self, deal_id: str, websocket: WebSocket) -> None:
        if deal_id in self._connections:
            self._connections[deal_id] = [
                ws for ws in self._connections[deal_id] if ws is not websocket
            ]
            if not self._connections[deal_id]:
                del self._connections[deal_id]

    async def broadcast(self, deal_id: str, event: dict) -> None:
        """Send event to all connected clients for a deal."""
        connections = self._connections.get(deal_id, [])
        dead = []
        for ws in connections:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(deal_id, ws)

    @property
    def active_connections_count(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


# Singleton manager — shared across the app
ws_manager = ConnectionManager()


@router.websocket("/ws/{deal_id}")
async def websocket_endpoint(websocket: WebSocket, deal_id: str):
    """Connect to receive real-time updates for a deal.

    Events sent:
    - review_started: new review kicked off
    - verdict_submitted: human submitted a verdict
    - review_completed: all clauses reviewed
    - advisory_generated: advisory document created
    """
    await ws_manager.connect(deal_id, websocket)
    try:
        while True:
            # Keep connection alive; clients can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(deal_id, websocket)
