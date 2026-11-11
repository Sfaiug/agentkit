"""A follow-up handed in again in a later round is one follow-up, as the last round put it.

A follow-up names its defect by its file and what is wrong there.  A reviewer meeting it again
on the next round's head hands it in in other words: another line, another why, another failing
command.  The run keeps it once, as that last round proved it on the head nearest to what
merges, so the merge writes one line in the seat's plan, checked by the last round's command,
and starts one fix run, with that command as its done-when.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, from a seat of akseat.py, against the
origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PLAN_LINE, Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_followup_plan_line import LINE, alive, held, wait_for

FIRST, LAST = "test -f sturdy.txt", "test -s sturdy.txt"
ITEM = "caller.txt:2 - flimsy widget - it breaks under load"
# Round 1 fails the work on a finding and hands in the follow-up; round 2 passes the fix and
# hands the same file and words for what is wrong in again, at another line, why and command.
REVIEWS = [{"final": "One finding, one more defect.", "hand_in": [
               ["finding", "retry.txt:1", "retry setting is wrong", "breaks callers",
                "--run", "grep -qx ready retry.txt"],
               ["follow-up", "caller.txt:1", "flimsy widget", "it breaks later", "--run", FIRST],
               ["done"]]},
           {"final": "That defect again.", "hand_in": [
               ["follow-up", "caller.txt:2", "flimsy widget", "it breaks under load", "--run", LAST],
               ["done"]]}]
WORK = {"write": {"retry.txt": "wrong\n", "feature.txt": "added\n"}, "commit": "Add feature",
        "final": "## Summary\nAdded feature.", "hand_in": [["done"]]}
FIX = {"write": {"retry.txt": "ready\n"}, "commit": "Restore retry setting",
       "final": "## Summary\nRestored retry setting.", "hand_in": [["done"]]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AFollowUpHandedInAgainIsOne(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets", files={"retry.txt": "ready\n",
                                              "caller.txt": "uses retry.txt\nretries twice\n"})
        GitHub(cls.home).grant(rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        Seat(cls.home, "acme", cwd=rig.path, record={"reviewers": ["astra"]}, planned=True)
        cls.release = cls.home.root / "adapters" / "release"
        # The fix run's turn waits for the test, so what the merge started is still there to read.
        fakeadapter.install(cls.home, claude=[WORK, FIX, held(cls.release, fakeadapter.PASS)],
                            codex=[*REVIEWS, "pass"])
        task = taskfile.write(cls.home, rig.path, "Add feature", done_when=("test -f feature.txt",))
        cls.done = cls.home.ak("run", str(task), env={"AGENTKIT_SESSION": "acme"}, timeout=300)
        plan = cls.home.path / ".agentkit/state/plan-acme.md"
        cls.plan = plan.read_text().replace(PLAN_LINE + "\n", "", 1) if plan.exists() else ""
        cls.parent_dir, *cls.fixes = taskfile.runs(cls.home)
        cls.parent = json.loads((cls.parent_dir / "run.json").read_text())
        cls.addClassCleanup(cls.settle)

    @classmethod
    def settle(cls):
        # A fix run still going would outlive this Home, so each ends before the Home goes.
        cls.release.write_text("")
        for directory in cls.fixes:
            if not wait_for(lambda: not alive(json.loads((directory / "run.json").read_text()).get("pid")), 60):
                cls.home.ak("run", "stop", directory.name)

    def test_the_run_fails_a_round_then_merges_keeping_the_last_round_s_follow_up(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.parent["state"], self.parent["merged"]), ("pass", True))
        self.assertEqual([row["verdict"] for row in self.parent["round_summaries"]], ["FAIL", "PASS"])
        [item] = self.parent["followups"]
        self.assertEqual(item.splitlines()[:2], [ITEM, f"$ {LAST}"])

    def test_the_seat_s_plan_has_one_line_for_it_checked_by_the_last_round_s_command(self):
        lines = [line for line in self.plan.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, self.plan)
        found = LINE.fullmatch(lines[0])
        self.assertIsNotNone(found, lines[0])
        self.assertEqual((found["what"], found["check"]), (f"Fix {ITEM}", LAST))
        # the commit that command was proven failing on: the last one reviewed
        self.assertEqual(found["base"], self.parent["review"]["head_sha"][:12])

    def test_one_fix_run_starts_with_the_last_round_s_command_as_its_done_when(self):
        self.assertEqual(len(self.fixes), 1, [path.name for path in self.fixes])
        self.assertEqual(self.parent.get("followup_runs"), [self.fixes[0].name])
        task = (self.fixes[0] / "task.md").read_text()
        self.assertIn(f"## Done when\n```bash\n{LAST}\n```", task)


if __name__ == "__main__":
    unittest.main()
