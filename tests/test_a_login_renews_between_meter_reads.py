"""A login a machine holds a copy of is renewed before it lapses, whatever the meters' cadence.

Claude's usage endpoint is asked once in fifteen minutes and its login renews only in its last
five, so inside the cadence a read that asks no meter still renews a login near its end, for a
harness whose turns read a renewed login, whichever harness owns the meters, and a turn on a machine
makes those reads itself, from its lend on, ticks being too far apart and its machine's prepare
long. The real `adapters/claude.sh`, a fake `claude` that renews the login it runs on, and a
temporary HOME: no real login, and nothing that reaches a network.
"""

from contextlib import ExitStack
from types import SimpleNamespace
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
from agentkit import config, helper, machine_turn, usage  # noqa: E402

CONFIG = """turns_on_machines = true
[defaults]
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
# ... whose meters another harness's adapter reads: the first of the provider's models
ROUTED_FIRST = CONFIG.replace("[models.opus]", """[models.routed]
harness = "opencode"
model = "anthropic/claude-opus-5-5"
effort = "high"
provider = "anthropic"

[models.opus]""")
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

    def test_a_login_is_renewed_whichever_harness_owns_the_meters(self):
        (config.HOME / "config.toml").write_text(ROUTED_FIRST)
        self.cfg = config.load()
        self.assertEqual(config.provider_harness(self.cfg, "anthropic")[0], "opencode")
        self.assertTrue(self.read_with_left(200))
        # ... and past the cadence too, when that other adapter is asked and renews nothing
        usage._lock("anthropic", "acme-second").unlink()
        reading = {"provider": "anthropic", "meters": [], "error": None}
        with patch.object(usage, "_probe", side_effect=None, return_value=reading):
            self.assertTrue(self.read_with_left(200))

    def test_a_turn_has_its_login_renewed_from_its_lend_through_a_long_prepare(self):
        self.left(30)
        away = SimpleNamespace(alias="acme", key="turn", image="fixture", memory_mb=256,
                               repo="acme", branch="main", default="main")
        out = self.root / "out"
        out.mkdir()

        def prepare(*_args, **_kw):    # the copy is in the parcel: the renewal comes after it
            deadline = time.monotonic() + 60
            while (not (self.root / "turns").exists() and time.monotonic() < deadline):
                time.sleep(0.01)
            return away, ""

        def watch(_argv, stdin, **_kw):
            self.assertTrue(select.select([stdin], [], [], 60)[0], "no renewal reached the turn")
            self.assertIn(b"renewed", base64.b64decode(os.read(stdin, 65536).split(b" ", 1)[0]))
            return 0, "", False

        with ExitStack() as stack:
            stack.enter_context(patch.object(machine_turn, "KEEP_EVERY", 3600))    # the first ask
            stack.enter_context(patch.object(machine_turn, "_program", return_value=("c/1/c", {})))
            stack.enter_context(patch.object(machine_turn, "_stopped", return_value=False))
            stack.enter_context(patch.object(machine_turn, "_home", return_value=(0, "")))
            stack.enter_context(patch.object(helper, "start", side_effect=prepare))
            stack.enter_context(patch.object(helper, "_remote", return_value=["fixture-ssh"]))
            stack.enter_context(patch.object(helper, "finish"))
            answer = machine_turn.call(
                {"harness": "claude", "provider": "anthropic"}, [str(REPO / "adapters/claude.sh")],
                self.root, out, {**os.environ, "AGENTKIT_ACCOUNT": "acme-second"}, (), None, watch)
        self.assertEqual(answer, (0, False, ""))
        # its end ends them, before this sandbox does: a read then would be of the real HOME
        for thread in threading.enumerate():
            if thread is not threading.current_thread():
                thread.join(60)
                self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
