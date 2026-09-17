"""
app.py — Flask + Flask-SocketIO glue for Discord Clone.

All actual business rules (membership, roles, message persistence) live in
core.py and are called from here. This file only translates HTTP/Socket.IO
requests into core.py calls and JSON/event responses, and enforces auth
(role checks) by simply propagating the exceptions core.py raises — it does
not duplicate or re-implement any permission logic itself.
"""

import os

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, join_room, leave_room

import core

DB_PATH = os.environ.get("DISCORD_CLONE_DB", "discord_clone.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")

# Threading mode keeps this demo dependency-light and portable across Python
# versions (no eventlet/gevent monkey-patching required). Fine for a couple
# of browser tabs; swap in eventlet/gevent for real concurrent load.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


def get_db():
    """One connection per process is fine for this small demo app; SQLite
    handles the light concurrency of a couple of browser tabs without issue."""
    if not hasattr(get_db, "_conn"):
        conn = core.get_connection(DB_PATH)
        core.init_db(conn)
        get_db._conn = conn
    return get_db._conn


def channel_room(channel_id) -> str:
    return f"channel_{channel_id}"


def error_response(exc: Exception, status: int):
    return jsonify({"error": str(exc)}), status


def handle_core_error(exc: Exception):
    if isinstance(exc, core.NotFoundError):
        return error_response(exc, 404)
    if isinstance(exc, core.NotMemberError):
        return error_response(exc, 403)
    if isinstance(exc, core.InsufficientRoleError):
        return error_response(exc, 403)
    if isinstance(exc, (core.DuplicateUsernameError, ValueError)):
        return error_response(exc, 400)
    return error_response(exc, 500)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@app.route("/api/users", methods=["POST"])
def api_create_user():
    data = request.get_json(force=True) or {}
    try:
        user_id = core.create_user(get_db(), data.get("username", ""))
        return jsonify({"user_id": user_id, "username": data["username"].strip()})
    except core.CoreError as exc:
        return handle_core_error(exc)
    except ValueError as exc:
        return handle_core_error(exc)


@app.route("/api/servers", methods=["POST"])
def api_create_server():
    data = request.get_json(force=True) or {}
    try:
        result = core.create_server(get_db(), data.get("name", ""), int(data["user_id"]))
        return jsonify(result)
    except core.CoreError as exc:
        return handle_core_error(exc)
    except (ValueError, KeyError) as exc:
        return handle_core_error(ValueError(str(exc)))


@app.route("/api/servers/join", methods=["POST"])
def api_join_server():
    data = request.get_json(force=True) or {}
    try:
        result = core.join_server(get_db(), data.get("invite_code", ""), int(data["user_id"]))
        return jsonify(result)
    except core.CoreError as exc:
        return handle_core_error(exc)
    except (ValueError, KeyError) as exc:
        return handle_core_error(ValueError(str(exc)))


@app.route("/api/servers", methods=["GET"])
def api_list_servers():
    try:
        user_id = int(request.args["user_id"])
    except (KeyError, ValueError):
        return error_response(ValueError("user_id query param required"), 400)
    return jsonify(core.list_servers_for_user(get_db(), user_id))


@app.route("/api/servers/<int:server_id>/channels", methods=["POST"])
def api_create_channel(server_id):
    data = request.get_json(force=True) or {}
    try:
        channel_id = core.create_channel(
            get_db(), server_id, int(data["user_id"]), data.get("name", ""),
            int(data.get("position", 0)),
        )
        return jsonify({"channel_id": channel_id})
    except core.CoreError as exc:
        return handle_core_error(exc)
    except (ValueError, KeyError) as exc:
        return handle_core_error(ValueError(str(exc)))


@app.route("/api/servers/<int:server_id>/channels", methods=["GET"])
def api_list_channels(server_id):
    try:
        return jsonify(core.list_channels(get_db(), server_id))
    except core.CoreError as exc:
        return handle_core_error(exc)


@app.route("/api/channels/<int:channel_id>/messages", methods=["GET"])
def api_channel_messages(channel_id):
    try:
        return jsonify(core.get_channel_messages(get_db(), channel_id))
    except core.CoreError as exc:
        return handle_core_error(exc)


@app.route("/api/messages/<int:message_id>", methods=["DELETE"])
def api_delete_message(message_id):
    data = request.get_json(force=True) or {}
    try:
        core.delete_message(get_db(), message_id, int(data["user_id"]))
        return jsonify({"ok": True})
    except core.CoreError as exc:
        return handle_core_error(exc)
    except (ValueError, KeyError) as exc:
        return handle_core_error(ValueError(str(exc)))


# ---------------------------------------------------------------------------
# Socket.IO — real-time messaging, one room per channel
# ---------------------------------------------------------------------------

@socketio.on("join_channel")
def on_join_channel(data):
    channel_id = data.get("channel_id")
    user_id = data.get("user_id")
    try:
        channel = core.get_channel(get_db(), channel_id)
        role = core.get_membership(get_db(), channel["server_id"], user_id)
        if role is None:
            raise core.NotMemberError("only members may join this channel")
    except core.CoreError as exc:
        return {"ok": False, "error": str(exc)}

    join_room(channel_room(channel_id))
    return {"ok": True}


@socketio.on("leave_channel")
def on_leave_channel(data):
    channel_id = data.get("channel_id")
    leave_room(channel_room(channel_id))
    return {"ok": True}


@socketio.on("send_message")
def on_send_message(data):
    channel_id = data.get("channel_id")
    user_id = data.get("user_id")
    content = data.get("content", "")
    try:
        message = core.post_message(get_db(), channel_id, user_id, content)
        user = core.get_user(get_db(), user_id)
        message["username"] = user["username"]
    except core.CoreError as exc:
        return {"ok": False, "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    socketio.emit("new_message", message, room=channel_room(channel_id))
    return {"ok": True, "message": message}


@socketio.on("delete_message")
def on_delete_message(data):
    message_id = data.get("message_id")
    user_id = data.get("user_id")
    try:
        message = core.get_message(get_db(), message_id)
        channel_id = message["channel_id"]
        core.delete_message(get_db(), message_id, user_id)
    except core.CoreError as exc:
        return {"ok": False, "error": str(exc)}

    socketio.emit(
        "message_deleted", {"message_id": message_id}, room=channel_room(channel_id)
    )
    return {"ok": True}


if __name__ == "__main__":
    # allow_unsafe_werkzeug: this is a small local/demo app, not a production
    # deployment — the bundled dev server is fine here.
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        allow_unsafe_werkzeug=True,
    )
