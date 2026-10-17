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
        # where the test that opened a real seat on 17 Oct was started from: a login of its own
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "HOME": "/home/acme",
            **{name: f"/home/acme/{name.lower()}" for name in config.state_env_names()}}))
        self.ran = []
        table = watch.local_passes

        def every_pass(*args):
            return (*((what, lambda what=what: self.ran.append(what), dry)
                      for what, _step, dry in table(*args)),
                    # where it ran, and which of the caller's logins it could have found
                    ("the named pass did not run", lambda: self.ran.append(
                        (os.environ["HOME"], config.state_env_names() & set(os.environ))), False),
                    ("a pass added later did not run", lambda: self.ran.append("later"), False))

        self.every_pass = every_pass
        self.stack.enter_context(patch.object(watch, "local_passes", every_pass))

    def test_only_the_named_pass_runs_at_the_temporary_home_with_no_login_of_the_callers(self):
        with only_passes(self.root, "the named pass did not run") as reached, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(watch.main([]), 0)
        # nothing else ran: none of ak's own passes, and not the one the test never heard of
        self.assertEqual(self.ran, [(str(self.root), set())])
        # every pass was still reached, in the table's order: stilled, never dropped
        self.assertEqual(reached, [what for what, _, _ in self.every_pass({}, False, print)])
        # and the caller's environment is theirs again once the tick is over
        self.assertEqual(os.environ["HOME"], "/home/acme")
        self.assertEqual(os.environ["CLAUDE_CONFIG_DIR"], "/home/acme/claude_config_dir")


if __name__ == "__main__":
    unittest.main(verbosity=2)
