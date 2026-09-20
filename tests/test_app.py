"""
Tests for app.py's plain HTTP surface (no live Socket.IO connection
needed for these — Flask's test client is enough).

Uses an in-memory SQLite DB (DISCORD_CLONE_DB=":memory:") set before
importing app.py, so running this test never touches the real
discord_clone.db file a developer might have locally.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DISCORD_CLONE_DB", ":memory:")

import app as app_module


class HealthzTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_healthz_returns_ok_status(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
