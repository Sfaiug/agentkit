"""A seat a run reopens runs the live ak, never the version that run is pinned to.

On 5 Nov 2026 a run pinned to its checkout under ~/.agentkit/versions reopened its gone seat,
which ran that checkout's wrapper with its `bin` first on PATH: every `ak` the seat typed after
ran the run's code.  Offline: a temporary HOME whose ~/agentkit and pinned version are both this
checkout, the process as `versions.enter` leaves a run's, the real claude adapter's command line,
and a fake tmux first on PATH that logs each call and the environment it was given.
"""

import json
import os
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

from fixtures import pane
from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch, versions

TMUX = """#!{python}
import json, os, sys
with open({log!r}, "a") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "env": dict(os.environ)}}) + "\\n")
if sys.argv[1:] == ["-V"]:
    print("tmux 3.5a")
"""


class SeatRunsTheLiveAk(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        self.pinned = config.HOME / versions.VERSIONS / "3c263bd0a1b2c3d4e5f60718293a4b5c6d7e8f90"
        self.pinned.parent.mkdir(parents=True)
        self.pinned.symlink_to(REPO)
        self.live = self.root / "agentkit"
        self.live.symlink_to(REPO)
        fake, self.log = self.root / "fake-bin", self.root / "tmux.jsonl"
        fake.mkdir()
        (fake / "tmux").write_text(TMUX.format(python=sys.executable, log=str(self.log)))
        (fake / "tmux").chmod(0o755)
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(config, "REPO", self.pinned))
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{fake}:{os.environ['PATH']}"}))
        for _ in range(2):          # entered again, as each of the run's own commands is
            versions.enter(self.pinned)
        config.save_session(self.cfg, "acme", "opus", ["opus"], {
            "cwd": str(self.root), "conversation": "5b0c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f",
            "id_source": "launcher"})
        orch.ensure(self.cfg, "acme", lambda _: None, saved=True)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.spawn = next(call for call in calls if "new-session" in call["argv"])
        self.words = shlex.split(pane.resolved(self.spawn["argv"])[-1])

    def under_versions(self, path):
        return Path(path).is_relative_to(config.HOME / versions.VERSIONS)

    def test_the_seat_runs_the_live_checkouts_wrapper(self):
        self.assertIn(str(self.live / "tools" / "idle-compact.py"), self.words)
        self.assertEqual([word for word in self.words if str(config.HOME / versions.VERSIONS) in word],
                         [])

    def test_its_path_holds_no_version_and_its_environment_no_run_code(self):
        entries = self.spawn["env"]["PATH"].split(os.pathsep)
        self.assertEqual([entry for entry in entries if self.under_versions(entry)], [])
        self.assertNotIn("AK_RUN_CODE", self.spawn["env"])
        self.assertFalse(any(word.startswith("AK_RUN_CODE=") for word in self.spawn["argv"]))

    def test_its_shims_and_its_servers_hooks_are_the_live_checkouts(self):
        shim = Path(os.readlink(config.HOME / "bin" / "tmux"))
        self.assertEqual(shim, self.live / "tools" / "tmux-shim")
        hooks = (config.STATE / "tmux.conf").read_text()
        self.assertIn(str(self.live / "bin" / "ak"), hooks)
        self.assertNotIn(str(config.HOME / versions.VERSIONS), hooks)


if __name__ == "__main__":
    unittest.main()
