# Discord Clone

A small, self-contained Discord-style chat platform: **servers (guilds)**
containing **channels**, with **membership and roles** — not just flat
real-time chat. Built with Flask, Flask-SocketIO, and SQLite.

## Data model

| Table                | Columns |
|-----------------------|---------|
| `users`               | `id`, `username` (unique) |
| `servers`              | `id`, `name`, `owner_id`, `invite_code` (unique) |
| `server_memberships`  | `id`, `user_id`, `server_id`, `role` (`owner` \| `admin` \| `member`) |
| `channels`             | `id`, `server_id`, `name`, `position` |
| `messages`             | `id`, `channel_id`, `user_id`, `content`, `created_at` |

A server has exactly one `owner` (its creator). Anyone else joins as a
`member` via the server's invite code and can be promoted to `admin`
directly in the `server_memberships` table (there's no promote-UI in this
scoped-down build). Only `owner`/`admin` members may **create channels** or
**delete messages** — this is enforced in `core.py`, not just hidden in the
UI, so a client can't bypass it by calling the API/socket directly.

All of that logic lives in **`core.py`**, a plain-Python module with zero
Flask/Socket.IO imports, so it's fully unit-testable without a live
websocket connection. `app.py` is just the HTTP/Socket.IO glue that calls
into `core.py` and translates exceptions into error responses.

### Design choice: joining a server twice

`core.join_server()` is **idempotent** — if you're already a member, it
returns your existing membership (role unchanged) instead of raising an
error or inserting a duplicate row. This keeps the client simple: it can
always "join" a server it has an invite code for without first checking
membership. See `test_join_server_idempotent` in `tests/test_core.py`.

## How to run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The server starts on <http://localhost:5000>, using a local SQLite file
`discord_clone.db` (created automatically, ignored by git).

## How to try it with two browser tabs

1. Open <http://localhost:5000> in **Tab A**, pick a username (e.g. `alice`),
   click **+ Server**, name it anything. You're now the owner.
2. Click the new server's icon in the left rail — the sidebar shows an
   **Invite code** near the bottom. Copy it.
3. Click **+ Channel** and create e.g. `general`.
4. Open <http://localhost:5000> in **Tab B** (or an incognito window), pick a
   different username (e.g. `bob`), click **Join**, and paste the invite
   code.
5. In both tabs, click the server icon, then the `general` channel. Send a
   message from Tab B and watch it appear instantly in Tab A (and vice
   versa) — that's Socket.IO broadcasting to everyone in that channel's
   room. Reloading either tab reloads the full message history from SQLite.
6. As `bob` (a plain member), try clicking `+ Channel` — the button is
   hidden because `bob` isn't owner/admin, and even a raw API/socket call
   to create a channel as `bob` is rejected server-side with a 403 /
   `InsufficientRoleError`.

## Running the tests

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
```

17 unit tests cover the core module directly (no Flask app, no websocket):
server creation/ownership, invite-code joins (including idempotent
re-joins), posting messages as a non-member (rejected), empty/over-length
message content (rejected), posting to a nonexistent channel, channel
creation by member vs. admin/owner, message deletion by member vs. owner
(rejected/allowed), chronological message ordering, channel-to-server
scoping, and duplicate usernames. A separate `tests/test_app.py` adds one
more test against Flask's test client for the `/healthz` endpoint.

CI (`.github/workflows/tests.yml`) runs the same suite on Python 3.11,
3.12, and 3.13 on every push/PR. It only exercises `core.py` — the live
Socket.IO server is not started in CI.

## Troubleshooting / FAQ

**"Join" says `no server with invite code '...'` even though I copied it
correctly.** Invite codes are matched with an exact string comparison
against the `servers.invite_code` column, so trailing whitespace (easy to
pick up when copying from a chat message) or a code from a previous run
against a different `discord_clone.db` file will both fail to match.
Re-copy the code from the sidebar of the tab that owns the server, and
make sure both tabs are pointed at the same server process/DB file.

**Messages don't show up in the other tab, but reloading fetches them.**
That means the REST fetch of history (`GET /api/channels/<id>/messages`)
works but the Socket.IO broadcast doesn't — almost always because that
browser tab never emitted `join_channel` for the channel it's viewing
(so it isn't in that channel's Socket.IO room), or the websocket
connection dropped silently. Check the browser console for Socket.IO
connection errors, and confirm both tabs called `join_channel` with the
same `channel_id` after selecting the channel.

**`sqlite3.OperationalError: database is locked` under load.** This app
uses one shared SQLite connection per process (see `get_db()` in
`app.py`) with the Socket.IO server in `threading` mode, which is fine
for a couple of browser tabs but not for real concurrent write load —
SQLite serializes writers. If you're stress-testing this, that's
expected; it's not meant to be a production chat backend.

**I get a 403 with `InsufficientRoleError` when creating a channel or
deleting a message, but I'm sure I'm in the server.** Only `owner` and
`admin` members may create channels or delete messages — plain `member`s
can post but not manage the server. This is enforced in `core.py`
regardless of what the UI shows, so a raw API/socket call as a plain
member is rejected the same way. Check your role with
`GET /api/servers?user_id=<id>` (it's in the `role` field for each
server).

**Port 5000 is already in use.** Set `PORT=5001 python app.py` (or any
free port) — see the environment variables listed in `CONTRIBUTING.md`.

## Project layout

```
core.py                 # pure logic: models, membership, roles, messages
app.py                   # Flask routes + Socket.IO events (glue only)
templates/index.html     # single-page vanilla-JS frontend
tests/test_core.py       # unit tests for core.py
tests/test_app.py        # Flask test-client tests for app.py's HTTP routes
.github/workflows/tests.yml
```

## Health check

`GET /healthz` returns `{"status": "ok"}` (200) if the process is up and
its SQLite connection is working, or `{"status": "error", ...}` (503)
otherwise — useful for a process manager or uptime check, separate from
just "Flask is responding."
