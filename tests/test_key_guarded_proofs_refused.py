"""A `--run` proof holding an exit-0 guard is refused at hand-in, naming the guard.

A guard is a path that ends in success whatever the code does: `true` or `:` run right after
`||`, `exit 0` or `set +e`.  Its replay could call a defect fixed, or win a dispute, without
testing anything, so `ak hand-in` refuses it; quoted text holds no guard.  Black-box: the
program `AK_BIN` names runs `ak run --no-merge` from outside through tests/fixtures/akbin.py,
on a project from gitrig.py with scripted harnesses from fakeadapter.py.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

GUARDED = {"python3 t.py || true": "|| true", "false || LC_ALL=C :": "|| :",
           "set +e; false": "set +e"}
TAKEN = "grep -q 'exit 0' t.sh"
REVIEWER = {"final": "Found one.", "hand_in": [
    *(["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--run", run]
      for run in [*GUARDED, TAKEN]), ["done"]]}
FIXER = {"final": "Disputed.", "hand_in": [
    ["dispute", "retry.txt:1", "it is right", "--run", "false; exit 0"],
    ["dispute", "retry.txt:1", "it is right", "--run", "true"], ["done"]]}


class GuardedProofsRefused(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(home, claude=["work", FIXER], codex=[REVIEWER, "concede"])
        task = taskfile.write(home, rig.path, "Add retry file", front={"rounds": 2})
        cls.done = home.ak("run", str(task), "--no-merge", timeout=300)

    def hand_ins(self, harness, call):
        runs = self.fakes[harness].runs()
        self.assertGreaterEqual(len(runs), call, self.done.out + self.done.err)
        return runs[call - 1]["hand_ins"]

    def test_a_finding_s_guarded_proof_is_refused_naming_its_guard(self):
        *guarded, taken, done = self.hand_ins("codex", 1)
        for row, guard in zip(guarded, GUARDED.values(), strict=True):
            self.assertNotEqual(row["code"], 0, row)
            self.assertIn(f"`{guard}`", row["err"])
        self.assertEqual((taken["argv"][-1], taken["code"]), (TAKEN, 0), taken)

    def test_a_dispute_s_guarded_proof_is_refused_naming_its_guard(self):
        guarded, taken, done = self.hand_ins("claude", 2)
        self.assertNotEqual(guarded["code"], 0, guarded)
        self.assertIn("`exit 0`", guarded["err"])
        self.assertEqual(taken["code"], 0, taken)


if __name__ == "__main__":
    unittest.main()
