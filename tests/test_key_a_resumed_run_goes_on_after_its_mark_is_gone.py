"""A resumed run goes on with the marks it was launched with, though the config dropped one.

A mark is a name in config.toml's `[models.*]`; a run is bound to its marks at launch, and the
config may change while it lives.  A launch records each mark's entry, and the run reads a mark
the config no longer defines from there: resumed, the same model builds and reviews.  A mark the
config still defines runs as the config defines it now, and one whose provider is gone too stays
gone.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
on a project from gitrig.py, a config from akconfig.py and scripted harnesses from
fakeadapter.py.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

ALPHA = {"harness": "claude", "model": "alpha-1"}
BETA = {"harness": "codex", "model": "beta-1"}
# The build, then the lock a crashed git leaves: the run ends in error with its review owed.
LOCKED = {"sh": "echo hello > retry.txt && git add -A && git commit -qm 'add retry.txt' && "
                'touch "$(git rev-parse --git-path index.lock)"',
          "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
# A spent window that is back a second later: the run waits `exhausted` with its build owed.
SPENT = {"final": "You have hit your usage limit. Try again at {in 1}.", "exit": 1}


def record(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def launched(case, turns):
    """A run of alpha building and beta reviewing, its harnesses scripted with `turns`; beta's
    entry holds a date, a value TOML has and JSON has not."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    case.rig = Rig(home, "widgets")
    path = akconfig.write(home, {"alpha": ALPHA, "beta": BETA}, workers=["alpha"],
                          reviewers=["beta"])
    path.write_text(path.read_text().replace('model = "beta-1"\n',
                                             'model = "beta-1"\nadded_on = 2026-10-01\n'))
    case.fakes = fakeadapter.install(home, **turns)
    case.ran = home.ak("run", str(taskfile.write(home, case.rig.path)), "--no-merge")
    case.run_dir = taskfile.only_run(home)
    case.stopped = record(case.run_dir)
    case.reviews = case.fakes["codex"].runs()


def resumed(case):
    case.resume = case.home.ak("run", "resume", case.run_dir.name, timeout=300)
    case.state = record(case.run_dir)


class RenamedReviewer(unittest.TestCase):
    """beta, owed the review, is renamed gamma in the config."""

    @classmethod
    def setUpClass(cls):
        launched(cls, {"claude": LOCKED, "codex": "pass"})
        lock = cls.home.run("git", "-C", cls.stopped["worktree"], "rev-parse",
                            "--path-format=absolute", "--git-path", "index.lock").out.strip()
        Path(lock).unlink()
        akconfig.write(cls.home, {"alpha": ALPHA, "gamma": BETA}, workers=["alpha"],
                       reviewers=["gamma"])
        resumed(cls)

    def test_the_run_stopped_with_its_review_owed(self):
        self.assertEqual(self.stopped["state"], "error", self.ran.out + self.ran.err)
        self.assertEqual(self.reviews, [])

    def test_resumed_it_ends_pass_reviewed_by_the_model_it_recorded(self):
        self.assertEqual(self.resume.code, 0, self.resume.out + self.resume.err)
        self.assertEqual((self.state["state"], self.state["reviewer"]), ("pass", "beta"))
        self.assertEqual([run["argv"][0] for run in self.fakes["codex"].runs()], ["beta-1"])


class RemovedExecutor(unittest.TestCase):
    """alpha, owed the build, is removed from the config, and beta now runs another model."""

    @classmethod
    def setUpClass(cls):
        launched(cls, {"claude": [SPENT, "work"], "codex": "pass"})
        time.sleep(2)       # past the moment the refusal named
        beta = {"beta": {**BETA, "model": "beta-2"}}
        akconfig.write(cls.home, beta, workers=["beta"])
        cls.unprovided = cls.home.ak("run", "resume", cls.run_dir.name)
        akconfig.write(cls.home, beta, workers=["beta"], providers={"anthropic": None})
        resumed(cls)

    def test_with_its_provider_gone_too_the_mark_stays_gone(self):
        self.assertEqual(self.unprovided.code, 2, self.unprovided.out)
        self.assertIn("unknown model 'alpha'", self.unprovided.err)

    def test_the_run_stopped_with_its_build_owed(self):
        self.assertEqual(self.stopped["state"], "exhausted", self.ran.out + self.ran.err)
        self.assertEqual(self.stopped["executor"], "alpha")

    def test_resumed_it_is_built_by_the_model_it_recorded(self):
        self.assertEqual(self.resume.code, 0, self.resume.out + self.resume.err)
        self.assertEqual((self.state["state"], self.state["executor"]), ("pass", "alpha"))
        self.assertEqual([run["argv"][0] for run in self.fakes["claude"].runs()],
                         ["alpha-1", "alpha-1"])

    def test_a_mark_the_config_still_defines_runs_as_it_defines_it_now(self):
        self.assertEqual([run["argv"][0] for run in self.fakes["codex"].runs()], ["beta-2"])


if __name__ == "__main__":
    unittest.main()
