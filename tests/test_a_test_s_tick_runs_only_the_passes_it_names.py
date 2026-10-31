"""A test's tick runs only the passes it names, under no login of the caller's (`fixtures.tick`).

Offline: every pass of `watch.local_passes` only says it ran, two of this test's own follow
them, ak's directories are temporary ones and GitHub answers as unreachable, so the tick ends
after its local passes.  The caller's login is an invented one in a patched environment.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, watch
from fixtures.hand_in import stateful
from fixtures.tick import only_passes


class TickRunsOnlyTheNamedPasses(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-tick-named-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.object(watch, "LOG_OWNED", set()))
        self.stack.enter_context(patch.object(watch, "gh_json", return_value=(None, "offline")))
        # where the test that opened a real seat on 17 Oct was started from: a login of its own,
        # by ak's adapters' state roots, a harness's token and key, and the account ak names
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        os.environ.pop(config.ADAPTER_DIR_ENV, None)
        self.caller = {"CLAUDE_CODE_OAUTH_TOKEN": "acme-token", "OPENAI_API_KEY": "acme-key",
                       config.ACCOUNT_ENV: "acme", config.PROVIDER_ENV: "anthropic",
                       **{name: f"/home/acme/{name.lower()}" for name in config.state_env_names()}}
        os.environ.update(HOME="/home/acme", **self.caller)
        self.ran = []
        table = watch.local_passes

        def every_pass(*args):
            return (*((what, lambda what=what: self.ran.append(what), dry)
                      for what, _step, dry in table(*args)),
                    # where it ran, and which of the caller's logins it could have found
                    ("named pass", lambda: self.ran.append(
                        (os.environ["HOME"], sorted(set(self.caller) & set(os.environ)))), False),
                    ("later pass", lambda: self.ran.append("later"), False))

        self.every_pass = every_pass
        self.stack.enter_context(patch.object(watch, "local_passes", every_pass))

    def tick(self):
        with only_passes(self.root, "named pass") as reached, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(watch.main([]), 0)
        # nothing else ran: none of ak's own passes, and not the one the test never heard of
        self.assertEqual(self.ran, [(str(self.root), [])])
        # every pass was still reached, in the table's order: stilled, never dropped
        self.assertEqual(reached, [what for what, _, _ in self.every_pass({}, False, print)])
        # and the caller's environment is theirs again once the tick is over
        self.assertEqual(os.environ["HOME"], "/home/acme")
        self.assertEqual(os.environ["CLAUDE_CONFIG_DIR"], "/home/acme/claude_config_dir")

    def test_only_the_named_pass_runs_at_the_temporary_home_with_no_login_of_the_callers(self):
        self.tick()

    def test_fake_adapters_that_declare_other_state_leave_no_login_of_the_callers_either(self):
        adapters = self.root / "adapters"
        adapters.mkdir()
        stateful(adapters / "acme.sh", self.root, ("claude", "codex"))
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.assertFalse({"CLAUDE_CONFIG_DIR", "CODEX_HOME"} & config.state_env_names())
        self.tick()

    def test_a_checkout_of_the_tests_own_with_no_adapters_leaves_no_login_of_the_callers(self):
        # test_live_update's tick runs in a clone of its own that holds no adapters
        self.stack.enter_context(patch.object(config, "REPO", self.root / "checkout"))
        self.assertFalse(config.state_env_names())
        self.tick()

if __name__ == "__main__":
    unittest.main(verbosity=2)
