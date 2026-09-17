"""
core.py — plain-Python data model and business logic for Discord Clone.

Deliberately kept free of any Flask / Socket.IO imports so the whole
membership / role / message pipeline can be unit tested without a live
web server or websocket connection.

Data model
----------
users               id, username (unique)
servers             id, name, owner_id, invite_code (unique)
server_memberships  id, user_id, server_id, role ('owner'|'admin'|'member')
channels            id, server_id, name, position
messages            id, channel_id, user_id, content, created_at

Design notes
------------
* Roles: 'owner' (creator, exactly one per server), 'admin', 'member'.
  Only 'owner' and 'admin' may create channels or delete messages.
* Joining a server is done via an invite code generated when the server
  is created (short random hex string, unique per server).
* Joining a server you are already a member of is IDEMPOTENT: it simply
  returns your existing membership rather than raising an error or
  creating a duplicate row. This keeps the client logic simple (a client
  can always "join" the last server it saw an invite for without first
  checking membership). See test_join_server_idempotent.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
MANAGE_ROLES = (ROLE_OWNER, ROLE_ADMIN)


class CoreError(Exception):
    """Base class for all core logic errors."""


class NotFoundError(CoreError):
    """Raised when a referenced entity (user/server/channel/message) does not exist."""


class NotMemberError(CoreError):
    """Raised when a user who is not a member of a server tries to act within it."""


class InsufficientRoleError(CoreError):
    """Raised when a member's role does not permit the requested action."""


class DuplicateUsernameError(CoreError):
    """Raised when creating a user whose username is already taken."""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    invite_code TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS server_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    server_id INTEGER NOT NULL REFERENCES servers(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    UNIQUE (user_id, server_id)
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL REFERENCES servers(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def get_connection(db_path: str = ":memory:") -> sqlite3.Connection:
    """Open a sqlite3 connection with row access by column name and FKs on."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables (idempotent)."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_invite_code() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(conn: sqlite3.Connection, username: str) -> int:
    """Create a user and return their id. Raises DuplicateUsernameError if taken."""
    username = username.strip()
    if not username:
        raise ValueError("username must not be empty")
    try:
        cur = conn.execute("INSERT INTO users (username) VALUES (?)", (username,))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise DuplicateUsernameError(f"username {username!r} already taken") from exc


def get_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no user with id {user_id}")
    return row


# ---------------------------------------------------------------------------
# Servers & membership
# ---------------------------------------------------------------------------

def create_server(conn: sqlite3.Connection, name: str, owner_id: int) -> dict:
    """Create a server. The creator becomes its 'owner' member. Returns dict
    with server id and invite_code."""
    get_user(conn, owner_id)  # raises NotFoundError if missing
    name = name.strip()
    if not name:
        raise ValueError("server name must not be empty")

    invite_code = _new_invite_code()
    cur = conn.execute(
        "INSERT INTO servers (name, owner_id, invite_code) VALUES (?, ?, ?)",
        (name, owner_id, invite_code),
    )
    server_id = cur.lastrowid
    conn.execute(
        "INSERT INTO server_memberships (user_id, server_id, role) VALUES (?, ?, ?)",
        (owner_id, server_id, ROLE_OWNER),
    )
    conn.commit()
    return {"server_id": server_id, "invite_code": invite_code}


def get_server_by_invite_code(conn: sqlite3.Connection, invite_code: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM servers WHERE invite_code = ?", (invite_code,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"no server with invite code {invite_code!r}")
    return row


def get_membership(
    conn: sqlite3.Connection, server_id: int, user_id: int
) -> Optional[str]:
    """Return the caller's role in a server, or None if not a member."""
    row = conn.execute(
        "SELECT role FROM server_memberships WHERE server_id = ? AND user_id = ?",
        (server_id, user_id),
    ).fetchone()
    return row["role"] if row else None


def join_server(conn: sqlite3.Connection, invite_code: str, user_id: int) -> dict:
    """Join a server via its invite code.

    Idempotent: if the user is already a member, their existing membership
    is returned unchanged (no duplicate row, no error, no role change).
    """
    get_user(conn, user_id)
    server = get_server_by_invite_code(conn, invite_code)
    server_id = server["id"]

    existing_role = get_membership(conn, server_id, user_id)
    if existing_role is not None:
        return {"server_id": server_id, "role": existing_role, "created": False}

    conn.execute(
        "INSERT INTO server_memberships (user_id, server_id, role) VALUES (?, ?, ?)",
        (user_id, server_id, ROLE_MEMBER),
    )
    conn.commit()
    return {"server_id": server_id, "role": ROLE_MEMBER, "created": True}


def list_servers_for_user(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.id, s.name, s.owner_id, s.invite_code, m.role
        FROM servers s
        JOIN server_memberships m ON m.server_id = s.id
        WHERE m.user_id = ?
        ORDER BY s.id
        """,
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _require_server(conn: sqlite3.Connection, server_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no server with id {server_id}")
    return row


def _require_role(role: Optional[str], allowed: tuple[str, ...]) -> None:
    if role is None:
        raise NotMemberError("user is not a member of this server")
    if role not in allowed:
        raise InsufficientRoleError(
            f"role {role!r} is not permitted to perform this action"
        )


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

def create_channel(
    conn: sqlite3.Connection,
    server_id: int,
    user_id: int,
    name: str,
    position: int = 0,
) -> int:
    """Create a channel in a server. Only owner/admin members may do this."""
    _require_server(conn, server_id)
    role = get_membership(conn, server_id, user_id)
    _require_role(role, MANAGE_ROLES)

    name = name.strip()
    if not name:
        raise ValueError("channel name must not be empty")

    cur = conn.execute(
        "INSERT INTO channels (server_id, name, position) VALUES (?, ?, ?)",
        (server_id, name, position),
    )
    conn.commit()
    return cur.lastrowid


def list_channels(conn: sqlite3.Connection, server_id: int) -> list[dict]:
    _require_server(conn, server_id)
    rows = conn.execute(
        "SELECT * FROM channels WHERE server_id = ? ORDER BY position, id",
        (server_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_channel(conn: sqlite3.Connection, channel_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no channel with id {channel_id}")
    return row


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def post_message(
    conn: sqlite3.Connection,
    channel_id: int,
    user_id: int,
    content: str,
    created_at: Optional[str] = None,
) -> dict:
    """Post a message to a channel. Requires the caller to be a member of the
    server that owns the channel (any role)."""
    channel = get_channel(conn, channel_id)
    role = get_membership(conn, channel["server_id"], user_id)
    if role is None:
        raise NotMemberError("only members of the server may post in this channel")

    content = content.strip()
    if not content:
        raise ValueError("message content must not be empty")

    ts = created_at or _now()
    cur = conn.execute(
        "INSERT INTO messages (channel_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
        (channel_id, user_id, content, ts),
    )
    conn.commit()
    return {
        "message_id": cur.lastrowid,
        "channel_id": channel_id,
        "user_id": user_id,
        "content": content,
        "created_at": ts,
    }


def get_message(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no message with id {message_id}")
    return row


def delete_message(conn: sqlite3.Connection, message_id: int, user_id: int) -> None:
    """Delete a message. Only an owner/admin of the server that owns the
    message's channel may do this (not just the author, and not plain
    members)."""
    message = get_message(conn, message_id)
    channel = get_channel(conn, message["channel_id"])
    role = get_membership(conn, channel["server_id"], user_id)
    _require_role(role, MANAGE_ROLES)

    conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    conn.commit()


def get_channel_messages(conn: sqlite3.Connection, channel_id: int) -> list[dict]:
    """Return the full message history for a channel in chronological order."""
    get_channel(conn, channel_id)
    rows = conn.execute(
        """
        SELECT m.id, m.channel_id, m.user_id, u.username, m.content, m.created_at
        FROM messages m
        JOIN users u ON u.id = m.user_id
        WHERE m.channel_id = ?
        ORDER BY m.created_at ASC, m.id ASC
        """,
        (channel_id,),
    ).fetchall()
    return [dict(r) for r in rows]
