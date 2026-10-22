"""`ak run merge <id>` refuses a run that has nothing waiting to merge, and merges nothing.

Only a finished PASS whose delivery stopped short may be merged by hand: a run tried with
--no-merge has no PR, a failed run or one still going has no finished PASS, an id names one
run.  Each refusal exits 2 with a line saying why, calls no `gh pr merge` and leaves the run
as it was, and a run still going goes on to deliver itself.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, against the bare origin of gitrig.py
and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class RunMergeRefusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = Rig(home, "widgets")
        GitHub(home).grant(cls.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(home, claude="work", codex="pass")
        tried = taskfile.write(home, cls.rig.path, "Add retry file")
        cls.tried = cls.launch(str(tried), "--no-merge")
        cls.fakes["codex"].behave("fail")
        failing = taskfile.write(home, cls.rig.path, "Add fail file", front={"rounds": 1})
        cls.failing = cls.launch(str(failing))

    @classmethod
    def launch(cls, *args):
        before = taskfile.runs(cls.home)
        done = cls.home.ak("run", *args, timeout=300)
        new = [path for path in taskfile.runs(cls.home) if path not in before]
        assert len(new) == 1, (done, new)
        return new[0]

    def state(self, run_dir):
        return json.loads((run_dir / "run.json").read_text())

    def refused(self, *args):
        """What `ak run merge` says on stderr, having exited 2 and merged nothing."""
        before = len(self.home.calls("gh"))
        done = self.home.ak("run", "merge", *args)
        self.assertEqual((done.code, done.out), (2, ""), done.err)
        self.assertFalse([call for call in self.home.calls("gh")[before:]
                          if call[:2] == ["pr", "merge"]])
        return done.err

    def test_a_pass_tried_with_no_merge_has_no_delivery_pr_to_merge(self):
        self.assertEqual({key: self.state(self.tried).get(key) for key in (
            "state", "verdict", "no_merge", "pr")}, {
            "state": "pass", "verdict": "PASS", "no_merge": True, "pr": None})
        run_id = self.tried.name
        self.assertEqual(self.refused(run_id), f"ak run: {run_id}: no delivery PR to merge\n")

    def test_a_failed_run_and_an_unknown_id_need_a_finished_pass(self):
        self.assertEqual(self.state(self.failing)["verdict"], "FAIL")
        for run_id in (self.failing.name, "20261020-0000-no-such-run"):
            with self.subTest(run_id):
                self.assertEqual(self.refused(run_id),
                                 f"ak run: {run_id}: merge requires a finished PASS\n")

    def test_anything_but_one_run_id_is_told_the_usage(self):
        name = self.tried.name
        for args in ((), (name, name), (f"../runs/{name}",), (".",), ("..",)):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*args), "ak run: usage: ak run merge <runid>\n")

    def test_a_refusal_leaves_the_run_as_it_was(self):
        for run_dir in (self.tried, self.failing):
            with self.subTest(run_dir.name):
                kept = {name: (run_dir / name).read_bytes() for name in ("run.json", "result.md")}
                self.refused(run_dir.name)
                self.assertEqual({name: (run_dir / name).read_bytes() for name in kept}, kept)

    def test_a_run_still_going_is_refused_and_then_delivers_itself(self):
        release = self.fakes["claude"].dir / "release"
        self.fakes["claude"].behave(
            {"sh": f"while [ ! -e '{release}' ]; do sleep 0.1; done", **fakeadapter.WORK})
        self.fakes["codex"].behave("pass")
        turns = self.fakes["claude"].n
        task = taskfile.write(self.home, self.rig.path, "Add slow file")
        before = taskfile.runs(self.home)
        proc = self.home.spawn("run", str(task))
        try:
            deadline = time.monotonic() + 120
            while self.fakes["claude"].n == turns and proc.poll() is None:
                self.assertLess(time.monotonic(), deadline, "the executor's turn never began")
                time.sleep(0.1)
            [going] = [path for path in taskfile.runs(self.home) if path not in before]
            self.assertEqual(self.state(going)["state"], "running")
            self.assertEqual(self.refused(going.name),
                             f"ak run: {going.name}: merge requires a finished PASS\n")
        finally:
            release.write_text("")
        self.assertEqual(proc.wait(timeout=300), 0, self.home.log("spawn-1.err").read_text())
        self.assertEqual({key: self.state(going).get(key) for key in ("state", "merged")},
                         {"state": "pass", "merged": True})


if __name__ == "__main__":
    unittest.main()
