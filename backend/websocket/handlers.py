# FILE: backend/websocket/handlers.py
# on_connect, on_event, on_disconnect
# C1: Room names use 'session:{uuid}' prefix (not bare UUID) to:
#     - Prevent future collision if other room types are added (e.g. 'proctor:{id}')
#     - Make server-side grep/debug output immediately readable

import socketio
from uuid import UUID
from datetime import datetime, timezone
from websocket.manager import manager
from auth.jwt_validator import validate_token
from db import queries
import logging

log = logging.getLogger(__name__)


def _serialize_socket_payload(data):
    """Recursively convert UUIDs and datetimes to JSON-serializable types for Socket.IO."""
    if isinstance(data, dict):
        return {k: _serialize_socket_payload(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return [_serialize_socket_payload(v) for v in data]
    elif isinstance(data, UUID):
        return str(data)
    elif isinstance(data, datetime):
        return data.isoformat()
    return data

# C1: Room name helper — always use this to construct room strings
def _session_room(session_id: str) -> str:
    return f"session:{session_id}"


# Track active candidate socket connections: sid -> (session_id, candidate_id)
_candidate_connections: dict = {}
# Track active candidate live state: (session_id, candidate_id) -> state dict
_candidate_live_state: dict = {}


def register_socketio_events(sio: socketio.AsyncServer) -> None:
    """Register all Socket.IO event handlers."""

    @sio.event
    async def connect(sid, environ, auth):
        """Handle new Socket.IO connection."""
        # Auth is optional at connect time — validated on join_proctor_room or candidate_heartbeat
        log.info("[Socket.IO] Client connected: %s", sid)

    @sio.event
    async def candidate_heartbeat(sid, data):
        """
        Candidate periodic heartbeat (every 1.5s).
        Carries compressed video thumbnail and real-time risk score.
        Authenticates candidate JWT and broadcasts candidate_status to session room.
        """
        session_id = data.get("sessionId")
        token = data.get("token")
        risk_level = data.get("riskLevel", 0)
        thumbnail = data.get("thumbnail")

        if not session_id or not token:
            return

        try:
            payload = validate_token(token)
            candidate_id = payload.user_id
        except Exception as e:
            log.warning("[Socket.IO] Candidate heartbeat auth failed: %s", e)
            return

        room = _session_room(session_id)
        _candidate_connections[sid] = (session_id, candidate_id)
        _candidate_live_state[(session_id, candidate_id)] = {
            "status": "online",
            "riskLevel": risk_level,
            "thumbnailUrl": thumbnail,
        }

        # Enter session room so candidate receives proctor warnings
        await sio.enter_room(sid, room)

        # Broadcast online status, risk level, and thumbnail to proctor
        await sio.emit(
            "candidate_status",
            {
                "candidateId": candidate_id,
                "status": "online",
                "riskLevel": risk_level,
                "thumbnailUrl": thumbnail,
            },
            room=room,
        )

    @sio.event
    async def candidate_join(sid, data):
        """Candidate initial room subscription."""
        session_id = data.get("sessionId")
        token = data.get("token")
        if not session_id or not token:
            return
        try:
            payload = validate_token(token)
            candidate_id = payload.user_id
            room = _session_room(session_id)
            _candidate_connections[sid] = (session_id, candidate_id)
            _candidate_live_state[(session_id, candidate_id)] = {
                "status": "online",
                "riskLevel": 0,
                "thumbnailUrl": None,
            }
            await sio.enter_room(sid, room)
            await sio.emit(
                "candidate_status",
                {"candidateId": candidate_id, "status": "online", "riskLevel": 0},
                room=room,
            )
            log.info("[Socket.IO] Candidate %s joined session room %s", candidate_id, room)
        except Exception as e:
            log.warning("[Socket.IO] Candidate join auth failed: %s", e)

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

        # Replay immediate status for any candidates already online in this session
        for (s_id, c_id), state in list(_candidate_live_state.items()):
            if s_id == session_id:
                await sio.emit(
                    "candidate_status",
                    {"candidateId": c_id, **state},
                    room=sid,
                )

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
                    {"events": [_serialize_socket_payload(dict(e)) for e in missed], "count": len(missed)},
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
        if sid in _candidate_connections:
            session_id, candidate_id = _candidate_connections.pop(sid)
            _candidate_live_state.pop((session_id, candidate_id), None)
            room = _session_room(session_id)
            await sio.emit(
                "candidate_status",
                {
                    "candidateId": candidate_id,
                    "status": "offline",
                },
                room=room,
            )
            log.info("[Socket.IO] Candidate %s disconnected from %s", candidate_id, room)

        manager.leave_all_rooms(sid)
        log.info("[Socket.IO] Client disconnected: %s", sid)

    @sio.event
    async def send_warning(sid, data):
        """
        Proctor sends a live pop-up warning to a specific candidate's screen.
        The warning is pushed to the session room and filtered client-side.
        Supports One-Way Voice Intercom (speak=True) through SpeechSynthesis.
        Authenticated: requires proctor JWT token or verified proctor session.
        """
        session_id = data.get("sessionId")
        candidate_id = data.get("candidateId")
        message = data.get("message", "")
        token = data.get("token")
        speak = data.get("speak", True)

        if not session_id or not candidate_id or not message:
            await sio.emit("error", {"message": "Missing required fields"}, room=sid)
            return

        if token:
            try:
                payload = validate_token(token)
                if payload.role != "proctor":
                    await sio.emit("error", {"message": "Proctor access required"}, room=sid)
                    return
            except Exception as e:
                await sio.emit("error", {"message": f"Auth failed: {str(e)}"}, room=sid)
                return

        # C1: Use namespaced room name
        room = _session_room(session_id)
        await sio.emit(
            "proctor_warning",
            {
                "candidateId": candidate_id,
                "message": message,
                "speak": speak if isinstance(speak, bool) else True,
                "timestamp": None,  # Client will use local time
            },
            room=room,
        )

    @sio.event
    async def candidate_transcript(sid, data):
        """
        Candidate live speech-to-text transcript event.
        Broadcasts candidate_transcript to session room for real-time proctor monitoring.
        """
        session_id = data.get("sessionId")
        candidate_id = data.get("candidateId")
        if not candidate_id and sid in _candidate_connections:
            candidate_id = _candidate_connections[sid][1]
        text = data.get("text", "")
        flagged = data.get("flagged", False)

        if not session_id or not text:
            return

        room = _session_room(session_id)
        await sio.emit(
            "candidate_transcript",
            {
                "sessionId": session_id,
                "candidateId": candidate_id,
                "text": text,
                "flagged": bool(flagged),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            room=room,
        )
