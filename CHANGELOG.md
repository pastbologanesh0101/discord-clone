# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] - 2026-09-17

Initial release.

### Added

- **Core data model and business logic** (`core.py`): plain-Python,
  Flask-free module implementing users, servers ("guilds"), server
  memberships with roles (`owner`/`admin`/`member`), channels, and
  messages on top of SQLite. Includes invite-code-based server joining
  (idempotent — re-joining a server you're already in returns your
  existing membership instead of erroring or duplicating it),
  owner/admin-only channel creation and message deletion, and
  chronological message history.
- **Flask + Flask-SocketIO app** (`app.py`): a REST API (create user,
  create/list servers, join by invite code, create/list channels, fetch
  channel message history, delete a message) plus Socket.IO events
  (`join_channel`, `leave_channel`, `send_message`, `delete_message`)
  for real-time messaging, broadcasting to one room per channel. Runs on
  the built-in dev server in threading mode against a local SQLite file.
- **Single-page frontend** (`templates/index.html`): vanilla-JS UI for
  picking a username, creating/joining servers via invite code, managing
  channels, and sending/receiving messages live over Socket.IO.
- **Unit test suite** (`tests/test_core.py`): 14 tests covering
  `core.py` directly against an in-memory SQLite database — server
  creation/ownership, invite-code joins (including the idempotent
  re-join case), non-member post rejection, channel creation permissions
  (member vs. admin/owner), message deletion permissions, chronological
  message ordering, channel-to-server scoping, and duplicate usernames.
- **CI** (`.github/workflows/tests.yml`): runs the test suite on every
  push/PR across Python 3.11 and 3.12.
- MIT `LICENSE` and project `README.md` describing the data model, how
  to run the app and tests, and a walkthrough for trying real-time
  messaging across two browser tabs.

[0.1.0]: https://github.com/pastbologanesh0101/discord-clone/commit/a1fb34f
