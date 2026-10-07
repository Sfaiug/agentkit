"""A harness and its ak commands keep the launching home's notification boundary.

A fake tmux starts the real launch script with a stale server environment, applying only
tmux's explicit per-pane overrides. No harness, webhook or real tmux server is reached.
"""

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, orch, statusbar


HARNESS = '''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from agentkit import config, notify
notify.record(os.environ[config.SESSION_ENV], "done", "Probe complete")
print(json.dumps({"home": str(config.HOME), "destination": notify.webhook(),
                  "sink_log": os.environ.get(notify.SINK_LOG_ENV, ""),
                  "session": config.current_session(),
                  "socket": os.environ.get("AGENTKIT_TMUX_SOCKET")}))
'''


class SeatEnvironment(Sandbox):
    def setUp(self):
        super().setUp()
        home = self.root / ".agentkit"
        for key in ("HOME", "STATE", "SECRETS", "TMP", "RUNS", "WT", "WORK", "ENV"):
            self.stack.enter_context(patch.object(
                config, key, home if key == "HOME" else home / key.lower()))
        config.ensure_dirs()
        (config.SECRETS / "discord_webhook").write_text("http://acme.invalid/hook")
        self.server_home = self.root / "old-server-home"
        self.server_home.mkdir()
        self.command = [sys.executable, "-c", HARNESS, str(REPO)]
        self.launched = []
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(statusbar, "dress"))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))

    def tmux(self, *args, **_kw):
        if args[0] == "show-options":
            return 0, "%1"
        if args[0] == "display-message":
            return 0, "acme"
        if "new-session" not in args and "respawn-pane" not in args:
            return 0, ""
        env = {**os.environ, "HOME": str(self.server_home),
               config.SESSION_ENV: "old-seat", orch.SOCKET_ENV: "old-server",
               notify.SINK_ENV: self.server_sink, notify.SINK_LOG_ENV: "old-sink-log",
               "AGENTKIT_DISCORD_WEBHOOK": "http://stale.invalid/hook",
               "AGENTKIT_DISCORD_USER_ID": "old-owner"}
        for index, arg in enumerate(args[:-1]):
            if arg == "-e":
                key, value = args[index + 1].split("=", 1)
                env[key] = value
        child = subprocess.run(["sh", "-c", args[-1]], env=env, capture_output=True,
                               text=True, timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.launched.append(json.loads(child.stdout))
        return 0, ""

    def launch_both(self):
        orch.start("acme", self.root, self.command, "any-model")
        orch._start_harness("acme", "any-model", self.root, self.command,
                            {"name": "acme", "exited": True})

    def test_probe_state_and_notices_stay_in_the_callers_home(self):
        for sink, destination in (("dry-run", "off"), ("http://sink.invalid/hook",
                                                       "http://sink.invalid/hook")):
            with self.subTest(sink=sink), patch.dict(os.environ, {
                    notify.SINK_ENV: sink, notify.SINK_LOG_ENV: str(self.root / "sink-log"),
                    "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": ""}):
                self.server_sink = ""
                self.launched.clear()
                self.launch_both()
                self.assertEqual(self.launched, [{
                    "home": str(self.root / ".agentkit"), "destination": destination,
                    "sink_log": str(self.root / "sink-log"), "session": "acme",
                    "socket": "agentkit-test"}] * 2)
                self.assertTrue(config.notify_path("acme").exists())
                self.assertFalse((self.server_home / ".agentkit").exists())

    def test_a_real_seat_drops_the_servers_old_sink_and_webhook(self):
        with patch.dict(os.environ):
            for key in (notify.SINK_ENV, notify.SINK_LOG_ENV, "AGENTKIT_DISCORD_WEBHOOK",
                        "AGENTKIT_DISCORD_USER_ID"):
                os.environ.pop(key, None)
            self.server_sink = "http://old-sink.invalid/hook"
            self.launch_both()
        self.assertEqual(self.launched, [{
            "home": str(self.root / ".agentkit"), "destination": "http://acme.invalid/hook",
            "sink_log": "", "session": "acme", "socket": "agentkit-test"}] * 2)

    def test_a_requested_webhook_follows_the_caller_on_start_and_resume(self):
        self.server_sink = "off"
        with patch.dict(os.environ, {notify.SINK_ENV: "", notify.SINK_LOG_ENV: "",
                "AGENTKIT_DISCORD_WEBHOOK": "http://requested.invalid/hook"}):
            self.launch_both()
        self.assertEqual([child["destination"] for child in self.launched],
                         ["http://requested.invalid/hook"] * 2)


if __name__ == "__main__":
    unittest.main()
