# FILE: backend/websocket/manager.py
# ConnectionManager: session_id → socket mapping

from typing import Dict, Set


class ConnectionManager:
    """Manages Socket.IO connections per session room."""

    def __init__(self):
        # Maps session_id → set of socket IDs
        self._rooms: Dict[str, Set[str]] = {}

    def join_room(self, session_id: str, sid: str) -> None:
        """Add a socket to a session room."""
        if session_id not in self._rooms:
            self._rooms[session_id] = set()
        self._rooms[session_id].add(sid)

    def leave_room(self, session_id: str, sid: str) -> None:
        """Remove a socket from a session room."""
        if session_id in self._rooms:
            self._rooms[session_id].discard(sid)
            if not self._rooms[session_id]:
                del self._rooms[session_id]

    def leave_all_rooms(self, sid: str) -> None:
        """Remove a socket from all rooms (on disconnect)."""
        for session_id in list(self._rooms.keys()):
            self._rooms[session_id].discard(sid)
            if not self._rooms[session_id]:
                del self._rooms[session_id]

    def get_room_members(self, session_id: str) -> Set[str]:
        """Get all socket IDs in a session room."""
        return self._rooms.get(session_id, set())

    def is_in_room(self, session_id: str, sid: str) -> bool:
        """Check if a socket is in a specific room."""
        return sid in self._rooms.get(session_id, set())


# Global connection manager instance
manager = ConnectionManager()
