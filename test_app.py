"""
Tests for the app: config storage, key handling and the local HTTP server.

The server is started on a random free port and driven over real HTTP, so the
token check, the routes and the JSON contract are all exercised for real.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
import urllib.error
import urllib.request
from typing import Any, Dict

from jimmy_agent import Jimmy, config
from jimmy_agent.app import serve


class ConfigTestCase(unittest.TestCase):
    """Each test gets its own JIMMY_HOME."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

        self._saved = {k: os.environ.get(k) for k in
                       ("JIMMY_HOME", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        os.environ["JIMMY_HOME"] = self.tmpdir.name
        for variable in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            os.environ.pop(variable, None)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class TestConfig(ConfigTestCase):
    def test_no_config_means_no_key(self) -> None:
        self.assertIsNone(config.api_key())
        self.assertEqual(config.load(), {})

    def test_saved_key_round_trips(self) -> None:
        config.set_api_key("sk-ant-example")
        self.assertEqual(config.api_key(), "sk-ant-example")

    def test_key_file_is_owner_only(self) -> None:
        path = config.set_api_key("sk-ant-example")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_environment_wins_over_the_file(self) -> None:
        config.set_api_key("sk-ant-from-file")
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-from-env"
        self.assertEqual(config.api_key(), "sk-ant-from-env")
        self.assertEqual(config.stored_api_key(), "sk-ant-from-file")

    def test_empty_key_clears_it(self) -> None:
        config.set_api_key("sk-ant-example")
        config.set_api_key("")
        self.assertIsNone(config.api_key())

    def test_whitespace_is_stripped(self) -> None:
        config.set_api_key("  sk-ant-padded  ")
        self.assertEqual(config.api_key(), "sk-ant-padded")

    def test_corrupt_config_does_not_crash(self) -> None:
        path = config.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(config.load(), {})
        self.assertIsNone(config.api_key())

    def test_masked_key_hides_the_middle(self) -> None:
        config.set_api_key("sk-ant-api03-abcdefghijklmnop-XYZW")
        masked = config.masked_key()
        self.assertIn("...", masked)
        self.assertNotIn("abcdefghijklmnop", masked)

    def test_key_source_is_reported(self) -> None:
        self.assertEqual(config.key_source(), "nowhere yet")
        config.set_api_key("sk-ant-example")
        self.assertIn("config.json", config.key_source())
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-env"
        self.assertIn("ANTHROPIC_API_KEY", config.key_source())

    def test_other_settings_survive_a_key_change(self) -> None:
        config.save({"theme": "dark"})
        config.set_api_key("sk-ant-example")
        self.assertEqual(config.load()["theme"], "dark")


class TestSetKeyCommand(ConfigTestCase):
    def test_rejects_something_that_is_not_a_key(self) -> None:
        from jimmy_agent.agent import _store_key

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(_store_key("hunter2"), 1)
        self.assertIsNone(config.api_key(), "a bad key must not be saved")

    def test_a_rejected_key_is_not_kept(self) -> None:
        """The CLI and the app must agree: a key the API refuses is removed again."""
        import jimmy_agent.agent as agent_module
        from jimmy_agent.agent import _store_key

        class RejectingBrain:
            def verify(self):
                return False, "the API rejected that key"

        real_brain = agent_module.Brain
        agent_module.Brain = RejectingBrain
        try:
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                self.assertEqual(_store_key("sk-ant-bogus-but-well-formed"), 1)
        finally:
            agent_module.Brain = real_brain

        self.assertIn("not kept", captured.getvalue())
        self.assertIsNone(config.api_key(), "the rejected key must not be left behind")

    def test_an_accepted_key_is_kept(self) -> None:
        import jimmy_agent.agent as agent_module
        from jimmy_agent.agent import _store_key

        class AcceptingBrain:
            def verify(self):
                return True, "connected to claude-opus-5"

        real_brain = agent_module.Brain
        agent_module.Brain = AcceptingBrain
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(_store_key("sk-ant-fine"), 0)
        finally:
            agent_module.Brain = real_brain

        self.assertEqual(config.api_key(), "sk-ant-fine")

    def test_an_unverifiable_key_is_kept_with_a_warning(self) -> None:
        """No network is not the same as a bad key - don't throw it away."""
        import jimmy_agent.agent as agent_module
        from jimmy_agent.agent import _store_key

        class OfflineBrain:
            def verify(self):
                return None, "couldn't reach the API to check - the key was saved anyway"

        real_brain = agent_module.Brain
        agent_module.Brain = OfflineBrain
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(_store_key("sk-ant-unverified"), 0)
        finally:
            agent_module.Brain = real_brain

        self.assertEqual(config.api_key(), "sk-ant-unverified")

    def test_clearing_always_succeeds(self) -> None:
        from jimmy_agent.agent import _store_key

        config.set_api_key("sk-ant-example")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(_store_key(""), 0)
        self.assertIsNone(config.api_key())


class ServerTestCase(ConfigTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.jimmy = Jimmy(offline=True, root=self.tmpdir.name)
        self.server = serve(self.jimmy, port=0, open_browser=False)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        self.url = self.server.jimmy_url
        self.base, self.token = self.url.split("/?t=")

    def post(self, path: str, body: Dict[str, Any], token: str = None) -> Dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base}{path}?t={token if token is not None else self.token}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())


class TestServerSecurity(ServerTestCase):
    def test_binds_to_loopback_only(self) -> None:
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_page_needs_the_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/", timeout=10)
        self.assertEqual(caught.exception.code, 403)

    def test_api_needs_the_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/chat", {"message": "hi"}, token="wrong-token")
        self.assertEqual(caught.exception.code, 403)

    def test_unknown_paths_are_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/secrets?t={self.token}", timeout=10)
        self.assertEqual(caught.exception.code, 404)

    def test_tokens_differ_between_runs(self) -> None:
        other = serve(Jimmy(offline=True, root=self.tmpdir.name), port=0, open_browser=False)
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        self.assertNotEqual(self.token, other.jimmy_url.split("/?t=")[1])


class TestServerRoutes(ServerTestCase):
    def test_page_renders_with_the_token(self) -> None:
        with urllib.request.urlopen(self.url, timeout=10) as response:
            html = response.read().decode()
        self.assertEqual(response.status, 200)
        self.assertIn("<title>Jimmy</title>", html)
        self.assertNotIn(self.token, html, "the page must not embed the token in its markup")

    def test_hello_reports_status(self) -> None:
        out = self.post("/api/hello", {})
        self.assertIn("Jimmy", out["greeting"])
        self.assertFalse(out["status"]["online"])
        self.assertIn("config.json", out["config_path"])

    def test_chat_round_trip_updates_memory(self) -> None:
        out = self.post("/api/chat", {"message": "teach the app lives in app.py"})
        self.assertIn("Learned", out["reply"])
        self.assertEqual(out["status"]["facts"], 1)

    def test_chat_learns_passively(self) -> None:
        self.post("/api/chat", {"message": "my name is Omer"})
        self.assertEqual(self.jimmy.engine.user_name, "Omer")

    def test_chat_reports_tool_calls(self) -> None:
        self.jimmy.chat = lambda message, on_text=None, on_tool=None: (
            on_tool("list_files(.)") or "I looked."
        )
        self.assertEqual(self.post("/api/chat", {"message": "look"})["tools"], ["list_files(.)"])

    def test_exit_is_flagged(self) -> None:
        self.assertTrue(self.post("/api/chat", {"message": "exit"})["exit"])
        self.assertFalse(self.post("/api/chat", {"message": "hello"})["exit"])

    def test_empty_message_is_harmless(self) -> None:
        self.assertEqual(self.post("/api/chat", {"message": "   "})["reply"], "")

    def test_malformed_body_is_a_400_not_a_crash(self) -> None:
        request = urllib.request.Request(
            f"{self.base}/api/chat?t={self.token}", data=b"{not json",
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 400)

        # ...and the server is still alive afterwards
        self.assertIn("Jimmy", self.post("/api/hello", {})["greeting"])


class TestKeyEndpoint(ServerTestCase):
    def test_a_non_key_is_refused_and_not_stored(self) -> None:
        out = self.post("/api/key", {"key": "hunter2"})
        self.assertIn("doesn't look like", out["message"])
        self.assertIsNone(config.api_key())

    def test_clearing_the_key_works(self) -> None:
        config.set_api_key("sk-ant-example")
        out = self.post("/api/key", {"key": ""})
        self.assertIn("removed", out["message"])
        self.assertIsNone(config.api_key())

    def test_a_key_the_api_rejects_is_not_kept(self) -> None:
        """A bad key is worse than none - it would fail on every single message."""

        class RejectingBrain:
            """The app rebuilds the brain with type(brain)(), so a stub class is enough."""

            online = False
            offline_reason = "the API rejected that key"
            model = "claude-opus-5"

            def verify(self):
                return False, "the API rejected that key"

            def status_line(self):
                return "offline"

        self.jimmy.brain = RejectingBrain()

        out = self.post("/api/key", {"key": "sk-ant-bogus-but-well-formed"})

        self.assertIn("not kept", out["message"])
        self.assertIsNone(config.api_key(), "a rejected key must be removed again")

    def test_a_key_the_api_accepts_is_kept(self) -> None:
        class AcceptingBrain:
            online = True
            offline_reason = None
            model = "claude-opus-5"

            def verify(self):
                return True, "connected to claude-opus-5"

            def status_line(self):
                return "online"

        self.jimmy.brain = AcceptingBrain()

        out = self.post("/api/key", {"key": "sk-ant-looks-fine"})

        self.assertIn("verified", out["message"])
        self.assertEqual(config.api_key(), "sk-ant-looks-fine")


if __name__ == "__main__":
    unittest.main(verbosity=2)
