# FILE: backend/websocket/handlers.py
# on_connect, on_event, on_disconnect
# C1: Room names use 'session:{uuid}' prefix (not bare UUID) to:
#     - Prevent future collision if other room types are added (e.g. 'proctor:{id}')
#     - Make server-side grep/debug output immediately readable

import socketio
from websocket.manager import manager
from auth.jwt_validator import validate_token
from db import queries
import logging

log = logging.getLogger(__name__)

# C1: Room name helper — always use this to construct room strings
def _session_room(session_id: str) -> str:
    return f"session:{session_id}"


def register_socketio_events(sio: socketio.AsyncServer) -> None:
    """Register all Socket.IO event handlers."""

    @sio.event
    async def connect(sid, environ, auth):
        """Handle new Socket.IO connection."""
        # Auth is optional at connect time — validated on join_proctor_room
        log.info("[Socket.IO] Client connected: %s", sid)

    @sio.event
    async def join_proctor_room(sid, data):
        """
        Proctor subscribes to a session's events.
        Only proctors connect to Socket.IO.

        C1: Room name is 'session:{session_id}' — namespaced to avoid collisions.
        On reconnect, sends missed HIGH/CRITICAL events from the last 30 minutes.
        """
        session_id = data.get("sessionId")
        token = data.get("token")

        if not session_id or not token:
            await sio.emit("error", {"message": "Missing sessionId or token"}, room=sid)
            return

        # Validate JWT and check role
        try:
            payload = validate_token(token)
            if payload.role != "proctor":
                await sio.emit("error", {"message": "Proctor access required"}, room=sid)
                return
        except Exception as e:
            await sio.emit("error", {"message": f"Auth failed: {str(e)}"}, room=sid)
            return

        # C1: Join namespaced room
        room = _session_room(session_id)
        await sio.enter_room(sid, room)
        manager.join_room(room, sid)

        await sio.emit(
            "joined",
            {"sessionId": session_id, "room": room, "message": "Subscribed to session events"},
            room=sid,
        )
        log.info("[Socket.IO] Proctor %s joined room %s", payload.user_id, room)

        # C1: Send missed HIGH/CRITICAL events from the last 30 minutes on reconnect.
        # This ensures a proctor who refreshes their browser doesn't miss critical alerts.
        try:
            missed = await queries.get_recent_high_events(
                session_id=session_id,
                minutes=30,
            )
            if missed:
                await sio.emit(
                    "missed_events",
                    {"events": [dict(e) for e in missed], "count": len(missed)},
                    room=sid,
                )
                log.info(
                    "[Socket.IO] Sent %d missed events to proctor %s",
                    len(missed), payload.user_id,
                )
        except Exception as e:
            # Non-fatal — proctor can still see live events going forward
            log.warning("[Socket.IO] Failed to fetch missed events: %s", e)

    @sio.event
    async def disconnect(sid):
        """Handle Socket.IO disconnection."""
        manager.leave_all_rooms(sid)
        log.info("[Socket.IO] Client disconnected: %s", sid)

    @sio.event
    async def send_warning(sid, data):
        """
        Proctor sends a live pop-up warning to a specific candidate's screen.
        The warning is pushed to the session room and filtered client-side.
        """
        session_id = data.get("sessionId")
        candidate_id = data.get("candidateId")
        message = data.get("message", "")

        if not session_id or not candidate_id or not message:
            await sio.emit("error", {"message": "Missing required fields"}, room=sid)
            return

        # C1: Use namespaced room name
        room = _session_room(session_id)
        await sio.emit(
            "proctor_warning",
            {
                "candidateId": candidate_id,
                "message": message,
                "timestamp": None,  # Client will use local time
            },
            room=room,
        )
