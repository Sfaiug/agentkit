"""A login a machine holds a copy of is renewed before it lapses, whatever the meters' cadence.

Claude's usage endpoint is asked once in fifteen minutes and its login renews only in its last
five, so inside the cadence a read that asks no meter still renews a login near its end, for a
harness whose turns read a renewed login, and a turn on a machine makes those reads itself, ticks
being too far apart. The real `adapters/claude.sh`, a fake `claude` that renews the login it runs
on, and a temporary HOME: no real login, and nothing that reaches a network.
"""

from contextlib import ExitStack
import base64
import json
import os
from pathlib import Path
import select
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, machine_turn, usage  # noqa: E402

CONFIG = """[defaults]
orchestrator = "opus"
workers = ["opus"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "high"
provider = "anthropic"

[providers.anthropic]
accounts = ["acme-second"]
"""
CLAUDE = """#!/bin/sh
echo turn >>"$HOME/turns"
printf '{"claudeAiOauth":{"accessToken":"renewed","refreshToken":"r","expiresAt":%s}}' \
  "$(( ($(date +%s) + 28800) * 1000 ))" >"$CLAUDE_CONFIG_DIR/.credentials.json"
"""


class Renewal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-login-renewal-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = self.root / ".agentkit"
        for key in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            stack.enter_context(patch.object(config, key, home / key.lower()))
        stack.enter_context(patch.object(config, "HOME", home))
        bin = self.root / "bin"
        bin.mkdir()
        # no Keychain on any host this runs on: the login is the file
        for name, text in (("claude", CLAUDE), ("security", "#!/bin/sh\nexit 1\n")):
            (bin / name).write_text(text)
            (bin / name).chmod(0o755)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("AK_", "AGENTKIT_", "CLAUDE_"))}
        env.update(HOME=str(self.root), PATH=f"{bin}{os.pathsep}{env['PATH']}")
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        (home / "config.toml").write_text(CONFIG)
        self.cfg = config.load()
        # Any meter asked is a failure: this is the cadence's quiet.
        stack.enter_context(patch.object(usage, "_probe",
                                         side_effect=AssertionError("asked a meter")))
        usage._lock("anthropic", "acme-second").write_text(repr(time.time()))
        self.login = self.root / ".claude-acme-second/.credentials.json"
        self.login.parent.mkdir()

    def left(self, seconds):
        self.login.write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "seat", "refreshToken": "r",
            "expiresAt": int((time.time() + seconds) * 1000)}}))

    def read_with_left(self, seconds):
        """The turns renewing a login with `seconds` left took, a meter read in the cadence on."""
        self.left(seconds)
        (self.root / "turns").unlink(missing_ok=True)
        usage._probe_gently(self.cfg, "anthropic", "acme-second")
        return (self.root / "turns").exists()

    def test_a_login_near_its_end_is_renewed_and_a_later_one_left_alone(self):
        self.assertTrue(self.read_with_left(200))
        self.assertEqual(json.loads(self.login.read_text())["claudeAiOauth"]["accessToken"], "renewed")
        self.assertFalse(self.read_with_left(600))

    def test_a_harness_whose_turns_read_no_renewal_is_not_asked(self):
        with patch.object(config, "manifest", return_value={}):
            self.assertFalse(self.read_with_left(200))

    def test_a_turn_on_a_machine_has_its_login_renewed_and_is_sent_the_renewal(self):
        self.left(200)
        env = {**os.environ, "AGENTKIT_ACCOUNT": "acme-second"}
        with patch.object(machine_turn, "KEEP_EVERY", 0.01), machine_turn._following(
                {"harness": "claude", "provider": "anthropic"}, str(REPO / "adapters/claude.sh"),
                env, [self.login], [machine_turn._stamp(self.login)], {}) as stdin:
            self.assertTrue(select.select([stdin], [], [], 60)[0], "no renewal reached the turn")
            line = os.read(stdin, 65536)
        # a read still under way ends before this sandbox does: it would read the real HOME
        for thread in threading.enumerate():
            if thread is not threading.current_thread():
                thread.join(60)
        self.assertIn(b"renewed", base64.b64decode(line.split(b" ", 1)[0]))


if __name__ == "__main__":
    unittest.main()
