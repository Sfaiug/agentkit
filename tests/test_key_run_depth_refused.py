"""A worker's worker may not start a run, a malformed depth is refused, and runs can still be read.

Every process a run starts carries AK_RUN_DEPTH, one more than the run's own.  The orchestrator's
runs are depth 0; their workers are depth 1 and may start a run for their tests; that run's
workers are depth 2, and a run they started would be machinery started by machinery, which
nobody asked for and nobody watches.  So `ak run` refuses it with exit 2 before it makes a run
directory, a branch or a session, while `ak run status` still answers.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py,
a config from akconfig.py, tasks from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, Home
from fixtures.gitrig import Rig

REFUSED = ("a worker's worker may not start runs (depth {}); only the orchestrator, and a worker "
           "for its tests, may\n")
MALFORMED = "ak run: AK_RUN_DEPTH must be a non-negative integer\n"


def project(home):
    """A project, two scripted models and a task each would otherwise run to PASS."""
    rig = Rig(home, "widgets")
    akconfig.write(home, ["opus", "astra"])
    fakes = fakeadapter.install(home, claude="work", codex="pass")
    return rig, fakes, taskfile.write(home, rig.path, "Add retry file")


class RefusedAtDepth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig, cls.fakes, cls.task = project(cls.home)
        cls.other = taskfile.write(cls.home, cls.rig.path, "Add other file")

    def assertNothingStarted(self):
        self.assertEqual(taskfile.runs(self.home), [])
        self.assertEqual(self.rig.branches(remote=False), ["main"])
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertNotEqual(self.home.tmux("list-sessions").code, 0)   # no server, no session
        self.assertEqual(self.home.calls("gh"), [])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))

    def test_every_way_of_starting_a_run_is_refused_at_depth_two_or_more(self):
        starts = ([str(self.task)], [str(self.task), "--no-merge"], [str(self.task), "--bg"],
                  [str(self.task), str(self.other)],
                  ["--review-pr", "https://github.com/acme/widgets/pull/7"],
                  ["resume", "20261020-0900-add-retry-file"])
        for depth in ("2", "3", "10"):
            for args in starts:
                with self.subTest(depth=depth, args=args):
                    done = self.home.ak("run", *args, env={"AK_RUN_DEPTH": depth})
                    self.assertEqual((done.code, done.out, done.err),
                                     (2, "", REFUSED.format(depth)))
        self.assertNothingStarted()

    def test_a_depth_that_is_not_a_whole_number_is_refused(self):
        for depth in ("x", "-1", "1.5", "", "٣"):    # the last is a digit, but not 0-9
            with self.subTest(depth=depth):
                done = self.home.ak("run", str(self.task), env={"AK_RUN_DEPTH": depth})
                self.assertEqual((done.code, done.out, done.err), (2, "", MALFORMED))
        self.assertNothingStarted()

    def test_a_worker_s_worker_may_still_read_the_runs(self):
        for depth in ("2", "3"):
            with self.subTest(depth=depth):
                listed = self.home.ak("run", "status", "--json", env={"AK_RUN_DEPTH": depth})
                self.assertEqual(listed.code, 0, listed.err)
                self.assertEqual(json.loads(listed.out), [])
                shown = self.home.ak("run", "status", env={"AK_RUN_DEPTH": depth})
                self.assertEqual(shown.code, 0, shown.err)
        self.assertNothingStarted()


class StartedInsideAWorker(unittest.TestCase):
    """A worker started for its tests (depth 1) runs a task whose executor tries `ak run`."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig, cls.fakes, task = project(cls.home)
        inner = taskfile.write(cls.home, cls.rig.path, "Add other file")
        # The adapters' directory is the one place beside the workspace a turn may write.
        cls.nested = cls.fakes["claude"].dir / "nested"
        attempt = (f"{shlex.quote(AK)} run {shlex.quote(str(inner))} --no-merge "
                   f">{cls.nested}.out 2>{cls.nested}.err; echo $? >{cls.nested}.code")
        cls.fakes["claude"].behave({**fakeadapter.WORK, "sh": attempt})
        cls.done = cls.home.ak("run", str(task), "--no-merge", env={"AK_RUN_DEPTH": "1"},
                               timeout=300)

    def said(self, kind):
        return Path(f"{self.nested}.{kind}").read_text()

    def test_a_worker_may_start_a_run_for_its_tests(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual(state["verdict"], "PASS")

    def test_that_run_s_workers_carry_depth_two(self):
        turns = self.fakes["claude"].runs() + self.fakes["codex"].runs()
        self.assertEqual([turn["env"].get("AK_RUN_DEPTH") for turn in turns], ["2", "2"])

    def test_a_run_its_executor_starts_is_refused_and_makes_nothing(self):
        self.assertEqual((self.said("code"), self.said("out"), self.said("err")),
                         ("2\n", "", REFUSED.format(2)))
        run = taskfile.only_run(self.home)
        self.assertTrue(run.name.endswith("-add-retry-file"), run.name)
        self.assertEqual(self.rig.branches(remote=False), ["ak/add-retry-file", "main"])


if __name__ == "__main__":
    unittest.main()
