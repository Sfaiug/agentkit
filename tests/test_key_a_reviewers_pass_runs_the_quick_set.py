"""A reviewer's PASS runs the project's tests a round chose, before that verdict is recorded, and no
round runs them before its review.  Red, the verdict is FAIL, the override saying the first line
that failed, and its next executor turn is handed that reason; nothing lands meanwhile.  A review
that fails runs none.

Owner, 20 Nov 2026, asked whether the set should run once per change after its review has passed:
"Once, after review passes".

Black-box, on the fixtures of tests/test_key_a_round_runs_the_tests_that_fail_most_at_landing.py:
the program `AK_BIN` names runs three tasks in turn, each editing tests/often.sh, which the
project's time record times, so each round chooses it.  The suite notes each start and the tests
it was handed, the reviewer each review, and the whole suite runs at landing alone.  The first's
first review fails and its second passes.  The second's change breaks often.sh, its reviewer
passing it, in its one round; resumed with a second, its next turn mends it.  The third's every
review fails.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.notes import Notes
from test_key_a_round_runs_its_changes_tests import SUITE
from test_key_a_round_runs_the_tests_that_fail_most_at_landing import SAID

OFTEN = "grep -qx v1 widget.txt\n"
CHOSEN = "suite ./tests/often.sh"
TASKS = ("fixed", "broken", "refused")
WORK = [
    {"write": {"fixed.txt": "bad\n", "tests/often.sh": f"# fixed\n{OFTEN}"}, "commit": "fixed",
     "final": "## Summary\nfixed", "hand_in": [["done"]]},
    {"write": {"fixed.txt": "good\n"}, "commit": "fixed good", "final": "## Summary\ngood",
     "hand_in": [["done"]]},
    {"write": {"broken.txt": "2\n", "widget.txt": "v2\n", "tests/often.sh": f"# broken\n{OFTEN}"},
     "commit": "broken", "final": "## Summary\nbroken", "hand_in": [["done"]]},
    {"write": {"widget.txt": "v1\n"}, "commit": "widget v1", "final": "## Summary\nwidget v1",
     "hand_in": [["done"]]},
    {"write": {"refused.txt": "bad\n", "tests/often.sh": f"# refused\n{OFTEN}"},
     "commit": "refused", "final": "## Summary\nrefused", "hand_in": [["done"]]},
    {"write": {"refused.txt": "bad again\n"}, "commit": "refused again",
     "final": "## Summary\nagain", "hand_in": [["done"]]},
]


def review(said, found=None):
    """A review noted on `said`: a finding that `found` holds no `bad`, else a pass."""
    note = ("import socket; socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)"
            f".sendto(b'review', {said.address!r})")
    finding = [["finding", f"{found}:1", "it says bad", "the task wants it good", "--run",
                f"! grep -q bad {found}"]] if found else []
    return {"sh": f"python3 -c {shlex.quote(note)}", "final": "Handed in.",
            "hand_in": [*finding, ["done"]]}


class ThreeRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        said = Notes()
        cls.addClassCleanup(said.close)
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: python3 suite.py\n---\n# widgets\n",
            "suite.py": SUITE.format(said=said.address), "widget.txt": "v1\n",
            "tests/often.sh": OFTEN, "tests/other.sh": "true\n"})
        cls.rig.git("config", "ak.repository", "0123456789ab")
        cls.home.write(".agentkit/state/test-times-0123456789ab.json",
                       {"./tests/often.sh": 1, "./tests/other.sh": 1})
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=WORK, codex=[
            review(said, "fixed.txt"), review(said), review(said), review(said),
            review(said, "refused.txt")])
        cls.done, cls.notes, cls.states = {}, {}, {}
        for name in TASKS:
            tip = cls.rig.origin("rev-parse", "main")
            task = taskfile.write(cls.home, cls.rig.path, f"Add {name}",
                                  front={"rounds": 1 if name == "broken" else 2},
                                  done_when=(f"test -f {name}.txt",))
            cls.done[name] = cls.home.ak("run", str(task), timeout=300)
            run_dir = next(path for path in taskfile.runs(cls.home)
                           if path.name.endswith(f"-add-{name}"))
            if name == "broken":
                # where its failed round left the run and the target, then on with a round more
                cls.ended = (cls.done[name], json.loads((run_dir / "run.json").read_text()), tip,
                             cls.rig.origin("rev-parse", "main"))
                cls.done[name] = cls.home.ak("run", "resume", run_dir.name, "--rounds", "2",
                                             timeout=300)
            cls.notes[name] = said.since()
            cls.states[name] = (run_dir, json.loads((run_dir / "run.json").read_text()))

    def verdicts(self, name):
        return [summary["verdict"] for summary in self.states[name][1]["round_summaries"]]

    def test_a_failed_review_runs_none_and_the_pass_after_it_runs_them_once(self):
        done, (_, state) = self.done["fixed"], self.states["fixed"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        self.assertEqual(self.verdicts("fixed"), ["FAIL", "PASS"])
        self.assertEqual(self.notes["fixed"], ["review", "review", CHOSEN, "suite whole"])

    def test_a_pass_its_tests_fail_is_a_fail_whose_next_turn_is_told_the_line_that_failed(self):
        # red, then red on its re-run: the round ends the run FAIL, the target where it was
        ended, failed, before, after = self.ended
        self.assertEqual(ended.code, 1, ended.out + ended.err)
        self.assertEqual((failed["state"], failed["merged"]), ("fail", False))
        self.assertEqual([summary["verdict"] for summary in failed["round_summaries"]], ["FAIL"])
        self.assertEqual(after, before)
        # resumed, the next turn's commit passes them and lands
        done, (run_dir, state) = self.done["broken"], self.states["broken"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        self.assertEqual(self.verdicts("broken"), ["FAIL", "PASS"])
        self.assertEqual(self.notes["broken"],
                         ["review", CHOSEN, CHOSEN, "review", CHOSEN, "suite whole"])
        self.assertIn(SAID, (run_dir / "round-2/executor/prompt.md").read_text())
        self.assertEqual(self.rig.origin("show", "main:widget.txt"), "v1")

    def test_a_run_whose_every_review_fails_runs_none(self):
        _, state = self.states["refused"]
        self.assertEqual(state["state"], "fail")
        self.assertEqual(self.verdicts("refused"), ["FAIL", "FAIL"])
        self.assertEqual(self.notes["refused"], ["review", "review"])


if __name__ == "__main__":
    unittest.main()
