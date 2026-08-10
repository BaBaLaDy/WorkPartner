"""Session persistence manager.

Stores LangGraph checkpoints in history/checkpoints.db via SqliteSaver
and session metadata in history/sessions.json.
"""

import asyncio
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver


SESSIONS_FILE = "sessions.json"
CHECKPOINTS_DB = "checkpoints.db"


# ---------------------------------------------------------------------------
# Hybrid SqliteSaver — sync SQLite + async wrappers for LangGraph
# ---------------------------------------------------------------------------
# LangGraph's async runtime (astream_events) calls aget_tuple / aput / etc.
# SqliteSaver only has sync methods. AsyncSqliteSaver needs aiosqlite + an
# event loop at __init__ time. We subclass SqliteSaver and offload every
# sync call to a worker thread via asyncio.to_thread, so a slow/blocked
# sqlite write no longer stalls the event loop (and every other concurrent
# coroutine, e.g. parallel SubAgents, waiting on it). A threading.Lock
# serializes access to the underlying sqlite3 connection, since
# check_same_thread=False only disables the thread-affinity check — it does
# not make the connection safe for truly concurrent use from the executor's
# worker threads.

class _HybridSqliteSaver(SqliteSaver):
    """SqliteSaver with async wrappers that run off the event loop thread."""

    def __init__(self, conn):
        super().__init__(conn)
        self._io_lock = threading.Lock()

    def _locked(self, fn, *args, **kwargs):
        with self._io_lock:
            return fn(*args, **kwargs)

    async def aget_tuple(self, config):
        return await asyncio.to_thread(self._locked, self.get_tuple, config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(
            self._locked, self.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(self, config, writes, task_id, task_path):
        return await asyncio.to_thread(
            self._locked, self.put_writes, config, writes, task_id, task_path
        )

    async def aget(self, config):
        return await asyncio.to_thread(self._locked, self.get, config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        return await asyncio.to_thread(
            self._locked, self.list, config, filter=filter, before=before, limit=limit
        )

    async def adelete_thread(self, thread_id):
        return await asyncio.to_thread(self._locked, self.delete_thread, thread_id)

    async def adelete_for_runs(self, config):
        return await asyncio.to_thread(self._locked, self.delete_for_runs, config)

    async def acopy_thread(self, source_config, dest_config):
        return await asyncio.to_thread(
            self._locked, self.copy_thread, source_config, dest_config
        )

    async def aprune(self, *, max_age_seconds=None, max_checkpoints=None):
        return await asyncio.to_thread(
            self._locked, self.prune,
            max_age_seconds=max_age_seconds, max_checkpoints=max_checkpoints,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionManager:
    """Manages named sessions backed by a SqliteSaver.

    Each session is a LangGraph thread_id. Metadata is stored in a
    lightweight JSON index (sessions.json) so we can list/name/switch
    sessions without querying LangGraph internals.
    """

    def __init__(self, history_dir: str = "./history"):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)

        # -- checkpoint database --
        db_path = str(self.history_dir / CHECKPOINTS_DB)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL: readers don't block writers and vice versa; NORMAL sync trades a
        # sliver of durability (survives app crash, not OS crash) for far fewer
        # fsyncs — worthwhile for a checkpoint DB that's rewritten every turn.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._checkpointer = _HybridSqliteSaver(self._conn)

        # -- metadata index --
        self._index_path = self.history_dir / SESSIONS_FILE
        self._data = self._load_index()

        # Ensure there's always at least one session
        if not self._data["sessions"]:
            self.create_session("default")

        # Resolve active
        active = self._data.get("active")
        if active not in self._data["sessions"]:
            # Active session was deleted — pick the most recent
            sessions = self._data["sessions"]
            if sessions:
                latest = max(sessions.keys(), key=lambda k: sessions[k]["last_active"])
                self._data["active"] = latest
            self._save_index()

    # ------------------------------------------------------------------
    # Index I/O
    # ------------------------------------------------------------------
    def _load_index(self) -> dict:
        if self._index_path.exists():
            try:
                with open(self._index_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, KeyError):
                pass
        return {"sessions": {}, "active": None}

    def _save_index(self):
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def checkpointer(self) -> _HybridSqliteSaver:
        return self._checkpointer

    @property
    def active_id(self) -> str:
        return self._data["active"]

    @property
    def active_name(self) -> str:
        sid = self._data["active"]
        return self._data["sessions"].get(sid, {}).get("name", sid)

    def list_sessions(self, session_type: str | None = None) -> list[dict]:
        """Return sessions sorted by last_active (most recent first).

        Args:
            session_type: If given, only return sessions of this type.
        """
        sessions = []
        for tid, meta in self._data["sessions"].items():
            # Apply defaults for old entries (Phase 2 backward compat)
            stype = meta.get("session_type", "interactive")
            if session_type is not None and stype != session_type:
                continue
            sessions.append({
                "thread_id": tid,
                "name": meta.get("name", tid),
                "created_at": meta.get("created_at", ""),
                "last_active": meta.get("last_active", ""),
                "active": tid == self._data["active"],
                "session_type": stype,
                "owner": meta.get("owner", "cli"),
                "pin": meta.get("pin"),
            })
        sessions.sort(key=lambda s: s["last_active"], reverse=True)
        return sessions

    def get_session(self, thread_id: str) -> dict | None:
        """Get metadata for a specific session."""
        meta = self._data["sessions"].get(thread_id)
        if meta is None:
            return None
        return {
            "thread_id": thread_id,
            "name": meta.get("name", thread_id),
            "created_at": meta.get("created_at", ""),
            "last_active": meta.get("last_active", ""),
            "active": thread_id == self._data["active"],
            "session_type": meta.get("session_type", "interactive"),
            "owner": meta.get("owner", "cli"),
            "pin": meta.get("pin"),
        }

    def create_session(self, name: str, session_type: str = "interactive",
                       owner: str = "cli") -> str:
        """Create a new session. Returns its thread_id."""
        # Sanitize name → thread_id
        thread_id = _sanitize(name)
        base = thread_id
        i = 1
        while thread_id in self._data["sessions"]:
            thread_id = f"{base}-{i}"
            i += 1

        now = _now_iso()
        self._data["sessions"][thread_id] = {
            "name": name.strip(),
            "created_at": now,
            "last_active": now,
            "session_type": session_type,
            "owner": owner,
        }
        self._data["active"] = thread_id
        self._save_index()
        return thread_id

    def switch_session(self, thread_id: str):
        """Switch the active session."""
        if thread_id not in self._data["sessions"]:
            raise KeyError(f"Session '{thread_id}' not found")
        self._data["active"] = thread_id
        self._data["sessions"][thread_id]["last_active"] = _now_iso()
        self._save_index()

    def touch(self, thread_id: str | None = None):
        """Update last_active timestamp (call after each turn)."""
        tid = thread_id or self._data["active"]
        if tid and tid in self._data["sessions"]:
            self._data["sessions"][tid]["last_active"] = _now_iso()
            self._save_index()

    def delete_session(self, thread_id: str) -> bool:
        """Delete a session and its checkpoints. Returns False if it doesn't exist."""
        if thread_id not in self._data["sessions"]:
            return False

        # Prevent deleting the last session
        if len(self._data["sessions"]) <= 1:
            return False

        # Remove checkpoints from SqliteSaver
        self._checkpointer.delete_thread(thread_id)

        # Remove metadata
        del self._data["sessions"][thread_id]

        # If active session was deleted, switch to the most recent remaining
        if self._data["active"] == thread_id:
            remaining = self._data["sessions"]
            if remaining:
                latest = max(remaining.keys(), key=lambda k: remaining[k]["last_active"])
                self._data["active"] = latest

        self._save_index()
        return True

    def rename_session(self, thread_id: str, new_name: str) -> bool:
        """Rename a session."""
        if thread_id not in self._data["sessions"]:
            return False
        self._data["sessions"][thread_id]["name"] = new_name.strip()
        self._save_index()
        return True

    def update_title(self, thread_id: str, title: str) -> bool:
        """Auto-update session title (shorter alias for rename_session)."""
        return self.rename_session(thread_id, title)

    def auto_create(self, base_name: str = "") -> str:
        """Create a new session with an auto-generated id (timestamp-based).

        Format: 2026-05-04-001, 2026-05-04-002, ...
        If base_name is provided, it's stored as the session name;
        otherwise a placeholder name is used until auto-titled.
        """
        now = datetime.now(timezone.utc)
        date_prefix = now.strftime("%Y-%m-%d")

        # Find next counter for today
        existing = [tid for tid in self._data["sessions"] if tid.startswith(date_prefix)]
        counter = 1
        while f"{date_prefix}-{counter:03d}" in existing:
            counter += 1

        thread_id = f"{date_prefix}-{counter:03d}"
        name = base_name.strip() if base_name.strip() else f"Session {date_prefix} #{counter}"

        self._data["sessions"][thread_id] = {
            "name": name,
            "created_at": now.isoformat(),
            "last_active": now.isoformat(),
        }
        self._data["active"] = thread_id
        self._save_index()
        return thread_id

    def thread_config(self, thread_id: str | None = None) -> dict:
        """Return the LangGraph config dict for a given (or active) thread."""
        tid = thread_id or self._data["active"]
        return {"configurable": {"thread_id": tid}}


def _sanitize(name: str) -> str:
    """Turn a human-readable name into a safe thread_id."""
    # Keep only alphanumeric, dash, underscore, and Chinese chars
    safe = "".join(
        ch for ch in name.strip()
        if ch.isalnum() or ch in ("-", "_") or "一" <= ch <= "鿿"
    )
    if not safe:
        safe = "session-" + str(int(time.time()))
    return safe[:64]
