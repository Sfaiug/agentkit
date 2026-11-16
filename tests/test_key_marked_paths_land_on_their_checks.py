"""A change touching only paths its target marks `ak-checks-only` lands on its checks, unreviewed.

Black-box against AK_BIN, fakeadapter's passing reviewer and a bare GitHub origin whose main
marks `shadow/**`: the mark is read on the target, so a change marking its own paths, or one
from a branch marking them for main, is reviewed.
"""

import contextlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class MarkedPaths(unittest.TestCase):
    def launch(self, change, *, from_dev=False):
        home = Home()
        self.addCleanup(home.close)
        home.env.update(AK_NOTIFY_SINK=None,
                        AK_HOST_READINGS=json.dumps({"cpus": 4, "load": 0, "free_mb": 16000}))
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        mark = {".gitattributes": "shadow/** ak-checks-only\n"}
        rig = Rig(home, "widgets", files={**({} if from_dev else mark), "api.py": "x = 1\n",
                                          "shadow/old.py": "x = 1\n"})
        if from_dev:
            rig.branch("dev", mark)
        gh = GitHub(home)
        gh.grant(rig.slug, "WRITE")
        work = {**change, "commit": "the change", "final": "## Summary\nchanged it", "hand_in": [["done"]]}
        fakes = fakeadapter.install(home, claude=work, codex="pass")
        front = {"base": "dev", "target": "main"} if from_dev else None
        done = home.ak("run", str(taskfile.write(home, rig.path, done_when=("true",), front=front)),
                       timeout=300)
        directory = taskfile.only_run(home)
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((directory / "run.json").read_text())
        self.assertTrue(state["merged"])
        with contextlib.closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
            no_review, = db.execute("SELECT no_review FROM runs WHERE run_id=?", (directory.name,)).fetchone()
        return fakes["codex"].n, no_review, (directory / "result.md").read_text().splitlines(), gh.pr(1)["body"]

    def test_only_marked_paths_merge_with_no_reviewer_turn(self):
        reviews, no_review, result, body = self.launch({"write": {"shadow/port.py": "x = 2\n"},
                                                        "sh": "git rm -q shadow/old.py"})
        self.assertEqual((reviews, no_review), (0, 1))
        self.assertIn("no review", result)
        self.assertIn("- no review", body.splitlines())

    def test_a_path_unmarked_on_the_target_gets_its_review(self):
        for change, from_dev in (({"write": {"shadow/port.py": "x = 2\n", "api.py": "x = 2\n"}}, False),
                                 ({"sh": "git mv api.py shadow/api.py"}, False),
                                 ({"write": {" shadow/port.py": "x = 2\n"}}, False),
                                 ({"write": {".gitattributes": "* ak-checks-only\n", "notes.txt": "x\n"}}, False),
                                 ({"write": {"shadow/port.py": "x = 2\n"}}, True)):
            with self.subTest(change=change, from_dev=from_dev):
                reviews, no_review, result, body = self.launch(change, from_dev=from_dev)
                self.assertEqual((reviews, no_review), (1, 0))
                self.assertIn("rounds: 1 of 3", result)
                self.assertNotIn("- no review", body.splitlines())


if __name__ == "__main__":
    unittest.main()
