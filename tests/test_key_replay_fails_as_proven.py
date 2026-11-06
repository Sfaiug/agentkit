"""A replayed proof blocks only by failing with the exit code its finding was proven with.

Each later round, ak replays every earlier blocking finding's `--run` proof on the reviewed
commit.  One that fails otherwise, as a proof its own `timeout` ends with 124 on a loaded host
where it first exited 1, is kept as a note naming both codes, and the run can pass; one failing
as proven blocks, a hang proven with 124 as much as an exit 1.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, a config
from akconfig.py, a task from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# Exits 1 (test's own failure) until slow.txt is committed, then hits its own timeout: 124.
# It holds no `exit 1` of its own, so a record naming that code names the proven one.
PROOF = "test -f slow.txt && timeout 1 sleep 9"
FINDING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--run", PROOF],
    ["done"]]}
SLOW = {"write": {"retry.txt": "hello\n", "slow.txt": "\n"}, "commit": "add retry.txt",
        "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}


def fix(path):
    return {"write": {path: "\n"}, "commit": f"add {path}", "final": f"## Summary\nadded {path}",
            "hand_in": [["done"]]}


class Run:
    """One `ak run task.md --no-merge` of two rounds in a Home of the class's own, the
    harnesses scripted as `steps` gives them."""

    steps = {}

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, **cls.steps)
        cls.task = taskfile.write(cls.home, cls.rig.path, "Add retry file", front={"rounds": 2})
        cls.done = cls.home.ak("run", str(cls.task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.result = (cls.run_dir / "result.md").read_text()

    def verdicts(self):
        return [summary["verdict"] for summary in self.state["round_summaries"]]

    def items(self, section):
        """Each `- ` item of the result's `section`, its indented lines with it."""
        part = self.result.split(f"\n## {section}\n", 1)[1:]
        return re.findall(r"(?m)^- .*(?:\n {2}.*)*", re.split(r"\n## ", part[0])[0] if part else "")


class Blocks(Run):
    """The replay fails as its finding was proven: round two fails on it, though its reviewer
    hands in nothing, and so does the run, its two rounds spent."""

    def test_the_replay_blocks_round_two(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.verdicts()), ("fail", ["FAIL", "FAIL"]))
        self.assertEqual(self.fakes["codex"].runs()[1]["hand_ins"][0]["argv"], ["done"])
        self.assertTrue([item for item in self.items("Findings")
                         if item.startswith("- retry.txt:1 ")], self.result)


class ATimeoutWhereTheProofExitedOneIsANote(Run, unittest.TestCase):
    """Proven with exit 1; the fix commits slow.txt, and the replay times out with 124."""

    steps = {"claude": ["work", fix("slow.txt")], "codex": [FINDING, "pass"]}

    def test_the_run_passes_in_round_two(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.verdicts()), ("pass", ["FAIL", "PASS"]))
        self.assertEqual(self.items("Findings"), [])

    def test_its_note_names_both_exit_codes(self):
        [note] = [item for item in self.items("Notes") if item.startswith("- retry.txt:1 ")]
        self.assertLessEqual({"1", "124"}, set(re.findall(r"\bexit (\d+)\b", note)), note)


class AProofStillExitingOneBlocks(Blocks, unittest.TestCase):
    """Proven with exit 1; the fix leaves slow.txt out, and the replay exits 1."""

    steps = {"claude": ["work", fix("other.txt")], "codex": [FINDING, "pass"]}


class AHangProvenWithTimeoutsCodeBlocksWhileItHangs(Blocks, unittest.TestCase):
    """slow.txt stands from the first commit on: proven with 124, and the replay exits 124."""

    steps = {"claude": [SLOW, fix("other.txt")], "codex": [FINDING, "pass"]}


if __name__ == "__main__":
    unittest.main()
