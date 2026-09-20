# Contributing to Discord Clone

Thanks for taking a look at this project. It's a small, self-contained
Discord-style chat app (Flask + Flask-SocketIO + SQLite), and it's meant to
stay small — most contributions should touch `core.py` (business logic),
`app.py` (HTTP/Socket.IO glue), or `tests/test_core.py`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

## Running the dev server locally

```bash
python app.py
```

This starts the app on <http://localhost:5000> against a local SQLite file
(`discord_clone.db`, created automatically and ignored by git). Open two
browser tabs (or one regular + one incognito) with different usernames to
try real-time messaging across a server/channel — see the README's "How to
try it with two browser tabs" section for the full walkthrough.

Useful environment variables:

- `PORT` — port to listen on (default `5000`)
- `DISCORD_CLONE_DB` — path to the SQLite file (default `discord_clone.db`;
  use `:memory:` for a throwaway in-memory DB)
- `FLASK_DEBUG=1` — enable Flask's debug/auto-reload mode
- `SECRET_KEY` — Flask session secret (fine to leave as the dev default
  locally; set a real value if you ever deploy this)

If you start the dev server to test something manually, stop it
(`Ctrl+C`) before you're done — don't leave it running in the background.

## Running the tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

All meaningful logic lives in `core.py`, which has zero Flask/Socket.IO
imports, so the test suite exercises it directly against an in-memory
SQLite database — no running server or websocket needed. Please add or
update tests in `tests/test_core.py` for any behavior change in `core.py`,
and make sure the full suite passes before opening a PR. CI
(`.github/workflows/tests.yml`) runs the same command across the supported
Python versions on every push/PR.

## Code style

- Keep `core.py` free of Flask/Socket.IO imports. If a change needs
  request/session/socket data, pass it in as a plain argument from
  `app.py` rather than importing Flask into `core.py`.
- Business rules (membership, roles, validation) belong in `core.py`,
  never only in `app.py` or the frontend — the README's design principle is
  that a raw API/socket call must be rejected server-side, not just hidden
  behind a disabled button in the UI.
- Raise the existing `core.CoreError` subclasses (`NotFoundError`,
  `NotMemberError`, `InsufficientRoleError`, `DuplicateUsernameError`) for
  domain errors, and `ValueError` for plain input-validation failures.
  `app.py`'s `handle_core_error()` already maps these to the right HTTP
  status codes — don't add new ad hoc error shapes without wiring them
  in there too.
- Match the existing style: 4-space indentation, docstrings on public
  functions in `core.py` explaining *why* (not just what), and small,
  focused functions over large ones.
- No new dependencies for something `core.py`/`app.py`/the standard
  library can already do — this project intentionally stays
  dependency-light (see `requirements.txt`).

## Submitting changes

1. Make your change on a branch, with tests covering any new behavior.
2. Run the test suite locally and make sure it's green.
3. Keep commits focused — one logical change per commit, with a clear
   commit message describing *why*, not just *what*.
4. Open a pull request describing the change and, for anything
   user-visible, how you tried it (e.g. "two tabs, alice/bob, joined via
   invite code, ...").
