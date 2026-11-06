"""A seat a run reopens runs the live ak, never the version that run is pinned to.

On 5 Nov 2026 a run pinned to its checkout under ~/.agentkit/versions reopened its gone seat,
which ran that checkout's wrapper with its `bin` first on PATH: every `ak` the seat typed after
ran the run's code.  Offline: a temporary HOME whose ~/agentkit and pinned version are both this
checkout, the process as `versions.enter` leaves a run's, the real claude adapter's command line,
and a fake tmux first on PATH that logs each call and the environment it was given; the pane is
then started from that as tmux 3.5a starts one, on a server a pinned run started earlier.
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
from unittest.mock import patch

from fixtures import pane
from fixtures.sandbox import REPO, Sandbox
from agentkit import config, guard, orch, versions

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

    def harness_env(self):
        """What the harness starts with: the server's environment, one a pinned run started and
        still holding its checkout, under the spawn's `-e` values and its client's PATH, through
        the launch file up to the harness."""
        spawn = next(c for c in guard.commands(self.spawn["argv"]) if "new-session" in c)
        env = {**self.spawn["env"], versions.CODE_ENV: str(self.pinned)}
        env.update(word.split("=", 1) for before, word in zip(spawn, spawn[1:]) if before == "-e")
        env["PATH"] = self.spawn["env"]["PATH"]
        head = Path(shlex.split(spawn[-1])[1]).read_text().split("\nexec ", 1)[0]
        probe = shlex.join([sys.executable, "-c",
                            "import json, os; print(json.dumps(dict(os.environ)))"])
        done = subprocess.run(["sh", "-c", f"{head}\nexec {probe}", str(self.root / "launch")],
                              env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_seat_runs_the_live_checkouts_wrapper(self):
        self.assertIn(str(self.live / "tools" / "idle-compact.py"), self.words)
        pinned = str(config.HOME / versions.VERSIONS)
        self.assertEqual([word for word in self.words if pinned in word], [])

    def test_its_path_holds_no_version_and_its_environment_no_run_code(self):
        env = self.harness_env()
        self.assertEqual([entry for entry in env["PATH"].split(os.pathsep)
                          if Path(entry).is_relative_to(config.HOME / versions.VERSIONS)], [])
        self.assertNotIn(versions.CODE_ENV, env)

    def test_a_starter_in_any_other_checkout_names_the_live_one_too(self):
        with patch.object(config, "REPO", self.root / "fix-api"):     # a worktree's, say
            words = orch.command(self.cfg, "opus", rulebook=self.root / "rules.md")
        self.assertIn(str(self.live / "tools" / "idle-compact.py"), words)

    def test_its_shims_and_its_servers_hooks_are_the_live_checkouts(self):
        shim = Path(os.readlink(config.HOME / "bin" / "tmux"))
        self.assertEqual(shim, self.live / "tools" / "tmux-shim")
        hooks = (config.STATE / "tmux.conf").read_text()
        self.assertIn(str(self.live / "bin" / "ak"), hooks)
        self.assertNotIn(str(config.HOME / versions.VERSIONS), hooks)


if __name__ == "__main__":
    unittest.main()
