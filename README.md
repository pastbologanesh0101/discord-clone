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

14 unit tests cover the core module directly (no Flask app, no websocket):
server creation/ownership, invite-code joins (including idempotent
re-joins), posting messages as a non-member (rejected), channel creation
by member vs. admin/owner, message deletion by member vs. owner
(rejected/allowed), chronological message ordering, channel-to-server
scoping, and duplicate usernames.

CI (`.github/workflows/tests.yml`) runs the same suite on Python 3.11 and
3.12 on every push/PR. It only exercises `core.py` — the live Socket.IO
server is not started in CI.

## Project layout

```
core.py                 # pure logic: models, membership, roles, messages
app.py                   # Flask routes + Socket.IO events (glue only)
templates/index.html     # single-page vanilla-JS frontend
tests/test_core.py       # unit tests for core.py
.github/workflows/tests.yml
```
