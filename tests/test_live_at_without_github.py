"""A merged change goes live on its `health:` whether or not GitHub answers the tick.

Offline: a temporary ~/.agentkit, gh faked as the tick tests fake it, and a probe that is `true`.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, record, watch  # noqa: E402
from fixtures.tick import only_passes  # noqa: E402

AFTER_MERGE = "merged runs were not followed"


class LiveAtWithoutGitHub(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-live-at-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        env = {key: value for key, value in os.environ.items()
               if key not in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG")}
        env.update(AGENTKIT_TMUX_SOCKET="agentkit-test", AK_RUN_DEPTH="0", AK_MAX_RUNS="0")
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.object(watch, "LOG_OWNED", set()))
        config.ensure_dirs()
        self.github = stack.enter_context(patch.object(watch, "gh_json"))
        self.reached = []
        for name in ("incoming", "outgoing"):
            stack.enter_context(patch.object(
                watch, name, side_effect=lambda *_a, name=name: self.reached.append(name)))

    def tick(self):
        with only_passes(self.root, AFTER_MERGE) as reached, redirect_stdout(io.StringIO()):
            self.reached = reached
            self.assertEqual(watch.main([]), 0)

    def test_a_merged_run_whose_health_passes_goes_live_while_gh_api_user_fails(self):
        self.github.return_value = (None, "error connecting to api.github.com")
        (self.root / "widget").mkdir()
        directory = config.RUNS / "run-a"
        directory.mkdir()
        record.save_state(directory, {
            "run_id": "run-a", "state": "pass", "verdict": "PASS", "merged": True,
            "pr": "https://github.com/acme/widget/pull/7", "merge_sha": "abc123",
            "launched_session": "fix-api", "repo": str(self.root / "widget"),
            "health": {"command": "true"}, "finished_at": time.time() - 600,
            "handed_back": time.time() - 600, "reported": True})
        self.tick()
        self.assertIn(("api", "user"), [call.args[1:] for call in self.github.call_args_list])
        self.assertTrue(record.read_state(directory).get("live_at"))
        self.assertNotIn("incoming", self.reached)

    def test_with_gh_api_user_passing_only_this_pass_moved_first(self):
        self.github.return_value = ({"login": "me"}, "")
        with patch.object(watch, "after_merge_checks") as follow:
            self.tick()
        follow.assert_called_once()
        self.assertEqual(self.reached[-4:], ["the harness upgrade pass did not run", AFTER_MERGE,
                                             "incoming", "outgoing"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
