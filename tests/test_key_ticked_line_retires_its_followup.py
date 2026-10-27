"""A plan line ticking ends the queued runs that only repeat its check (`plan.retire`): one
in its repository that never held a slot and whose follow-up check is the line's ends
`stopped`, naming the line and the commit, so its seat reads done; another check, or a run
that started, is left alone.  Offline: a real repository and plan, a throwaway HOME.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, handback, orch, plan, stop, transitions
from agentkit import record as run_record

SEAT = "fix-api"
CHECK = "test -f feature.txt"


class Ticked(Sandbox):

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: SEAT, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        self.stack.enter_context(patch.object(plan.os, "killpg"))
        # a stop touches no real unit, process or seat
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(stop, "marker_pids", return_value=[]))
        self.stack.enter_context(patch.object(handback, "redress_seat"))
        self.repo = config.CODE / "acme"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Plan test")
        self.git("config", "user.email", "plan@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        origin = self.root / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(origin)],
                       check=True, capture_output=True)
        self.git("remote", "add", "origin", str(origin))
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        config.save_session(self.cfg, SEAT, "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def run_record(self, run_id, check, **state):
        directory = config.RUNS / run_id
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(json.dumps({
            "run_id": run_id, "launched_session": SEAT, "repo": str(self.repo.resolve()),
            "followup": {"run": "source", "text": "api.py:1 - mode is wrong", "place": "api.py:1",
                         "check": check}, **state}))
        return directory

    def test_the_line_ticking_ends_only_the_queued_run_repeating_its_check(self):
        plan.add(SEAT, "Fix the mode", CHECK, self.repo, proven=self.base, deferred=False)
        queued = {"state": "queued", "slot_waiting": True, "pid": None}
        repeat = self.run_record("repeat", CHECK + " ", **queued)       # trimmed, it is the check
        # another seat's, so what is left open is no work of this seat's
        other = self.run_record("other", "test -f other.txt", **queued, launched_session="acme-ui")
        started = self.run_record("started", CHECK, state="running", slot_waiting=False, pid=None,
                                  launched_session="acme-ui")
        (self.repo / "feature.txt").write_text("fixed\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Fix the mode")
        self.git("push", "-q", "origin", "main")
        commit = self.git("rev-parse", "--short=12", "HEAD")

        self.assertEqual(plan.verify(SEAT), [])

        ended = run_record.read_state(repeat)
        self.assertEqual(ended["state"], "stopped")
        self.assertIn("Fix the mode", ended["error"])
        self.assertIn(commit, ended["error"])
        self.assertEqual(run_record.read_state(other)["state"], "queued")
        self.assertEqual(run_record.read_state(started)["state"], "running")
        self.assertEqual(plan.finished(SEAT), "Fix the mode")
        self.assertEqual(transitions.seat_runs(SEAT), [])


if __name__ == "__main__":
    unittest.main()
