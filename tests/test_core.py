"""
Unit tests for core.py — the pure membership/role/message logic module.

These tests run against an in-memory SQLite database and never touch
Flask or Socket.IO, so they exercise exactly the rules the app relies on
for authorization, independent of any web/websocket transport.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = core.get_connection(":memory:")
        core.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    # -- helpers ----------------------------------------------------------

    def make_user(self, name):
        return core.create_user(self.conn, name)

    # -- tests --------------------------------------------------------------

    def test_create_server_makes_creator_the_owner(self):
        alice = self.make_user("alice")
        result = core.create_server(self.conn, "Alice's Place", alice)
        role = core.get_membership(self.conn, result["server_id"], alice)
        self.assertEqual(role, core.ROLE_OWNER)

    def test_join_via_invite_code_adds_membership(self):
        alice = self.make_user("alice")
        bob = self.make_user("bob")
        server = core.create_server(self.conn, "Alice's Place", alice)

        core.join_server(self.conn, server["invite_code"], bob)

        role = core.get_membership(self.conn, server["server_id"], bob)
        self.assertEqual(role, core.ROLE_MEMBER)

    def test_join_with_bad_invite_code_raises_not_found(self):
        bob = self.make_user("bob")
        with self.assertRaises(core.NotFoundError):
            core.join_server(self.conn, "not-a-real-code", bob)

    def test_join_server_idempotent(self):
        """Joining a server you're already in returns the existing membership
        instead of raising or creating a duplicate row (documented design
        choice — see core.py docstring)."""
        alice = self.make_user("alice")
        bob = self.make_user("bob")
        server = core.create_server(self.conn, "Alice's Place", alice)

        first = core.join_server(self.conn, server["invite_code"], bob)
        second = core.join_server(self.conn, server["invite_code"], bob)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])

        count = self.conn.execute(
            "SELECT COUNT(*) c FROM server_memberships WHERE user_id = ? AND server_id = ?",
            (bob, server["server_id"]),
        ).fetchone()["c"]
        self.assertEqual(count, 1)

    def test_non_member_cannot_post_in_channel(self):
        alice = self.make_user("alice")
        mallory = self.make_user("mallory")
        server = core.create_server(self.conn, "Alice's Place", alice)
        channel_id = core.create_channel(self.conn, server["server_id"], alice, "general")

        with self.assertRaises(core.NotMemberError):
            core.post_message(self.conn, channel_id, mallory, "hi")

    def test_member_can_post_in_channel(self):
        alice = self.make_user("alice")
        bob = self.make_user("bob")
        server = core.create_server(self.conn, "Alice's Place", alice)
        core.join_server(self.conn, server["invite_code"], bob)
        channel_id = core.create_channel(self.conn, server["server_id"], alice, "general")

        msg = core.post_message(self.conn, channel_id, bob, "hello")
        self.assertEqual(msg["content"], "hello")

    def test_only_owner_or_admin_can_create_channels_member_rejected(self):
        alice = self.make_user("alice")
        bob = self.make_user("bob")
        server = core.create_server(self.conn, "Alice's Place", alice)
        core.join_server(self.conn, server["invite_code"], bob)  # bob is a plain member

        with self.assertRaises(core.InsufficientRoleError):
            core.create_channel(self.conn, server["server_id"], bob, "mods-only")

    def test_admin_can_create_channels(self):
        alice = self.make_user("alice")
        bob = self.make_user("bob")
        server = core.create_server(self.conn, "Alice's Place", alice)
        core.join_server(self.conn, server["invite_code"], bob)
        self.conn.execute(
            "UPDATE server_memberships SET role = 'admin' WHERE user_id = ? AND server_id = ?",
            (bob, server["server_id"]),
        )
        self.conn.commit()

        channel_id = core.create_channel(self.conn, server["server_id"], bob, "staff")
        self.assertIsNotNone(channel_id)

    def test_only_owner_or_admin_can_delete_message_member_rejected(self):
        alice = self.make_user("alice")
        bob = self.make_user("bob")
        server = core.create_server(self.conn, "Alice's Place", alice)
        core.join_server(self.conn, server["invite_code"], bob)
        channel_id = core.create_channel(self.conn, server["server_id"], alice, "general")
        msg = core.post_message(self.conn, channel_id, bob, "oops")

        with self.assertRaises(core.InsufficientRoleError):
            core.delete_message(self.conn, msg["message_id"], bob)

        # message must still exist
        still_there = core.get_message(self.conn, msg["message_id"])
        self.assertEqual(still_there["content"], "oops")

    def test_owner_can_delete_any_message(self):
        alice = self.make_user("alice")
        bob = self.make_user("bob")
        server = core.create_server(self.conn, "Alice's Place", alice)
        core.join_server(self.conn, server["invite_code"], bob)
        channel_id = core.create_channel(self.conn, server["server_id"], alice, "general")
        msg = core.post_message(self.conn, channel_id, bob, "delete me")

        core.delete_message(self.conn, msg["message_id"], alice)

        with self.assertRaises(core.NotFoundError):
            core.get_message(self.conn, msg["message_id"])

    def test_message_history_loads_in_chronological_order(self):
        alice = self.make_user("alice")
        server = core.create_server(self.conn, "Alice's Place", alice)
        channel_id = core.create_channel(self.conn, server["server_id"], alice, "general")

        core.post_message(self.conn, channel_id, alice, "first", created_at="2026-01-01T00:00:00+00:00")
        core.post_message(self.conn, channel_id, alice, "third", created_at="2026-01-01T00:00:02+00:00")
        core.post_message(self.conn, channel_id, alice, "second", created_at="2026-01-01T00:00:01+00:00")

        history = core.get_channel_messages(self.conn, channel_id)
        contents = [m["content"] for m in history]
        self.assertEqual(contents, ["first", "second", "third"])

    def test_channel_belongs_to_correct_server(self):
        alice = self.make_user("alice")
        server_a = core.create_server(self.conn, "Server A", alice)
        server_b = core.create_server(self.conn, "Server B", alice)

        channel_a = core.create_channel(self.conn, server_a["server_id"], alice, "general")
        channel_b = core.create_channel(self.conn, server_b["server_id"], alice, "general")

        self.assertEqual(core.get_channel(self.conn, channel_a)["server_id"], server_a["server_id"])
        self.assertEqual(core.get_channel(self.conn, channel_b)["server_id"], server_b["server_id"])

        channels_a = core.list_channels(self.conn, server_a["server_id"])
        self.assertEqual(len(channels_a), 1)
        self.assertEqual(channels_a[0]["id"], channel_a)

    def test_duplicate_username_rejected(self):
        self.make_user("alice")
        with self.assertRaises(core.DuplicateUsernameError):
            self.make_user("alice")

    def test_create_channel_requires_membership(self):
        alice = self.make_user("alice")
        mallory = self.make_user("mallory")
        server = core.create_server(self.conn, "Alice's Place", alice)

        with self.assertRaises(core.NotMemberError):
            core.create_channel(self.conn, server["server_id"], mallory, "hack-channel")

    def test_post_message_with_empty_content_raises_value_error(self):
        alice = self.make_user("alice")
        server = core.create_server(self.conn, "Alice's Place", alice)
        channel_id = core.create_channel(self.conn, server["server_id"], alice, "general")

        # whitespace-only content should be rejected the same way as "",
        # since post_message() strips before checking.
        with self.assertRaises(ValueError):
            core.post_message(self.conn, channel_id, alice, "   ")

        # and the message must not have been persisted
        history = core.get_channel_messages(self.conn, channel_id)
        self.assertEqual(history, [])

    def test_post_message_to_nonexistent_channel_raises_not_found(self):
        alice = self.make_user("alice")
        core.create_server(self.conn, "Alice's Place", alice)

        with self.assertRaises(core.NotFoundError):
            core.post_message(self.conn, 9999, alice, "hello?")


if __name__ == "__main__":
    unittest.main()
