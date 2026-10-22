"""A second run of the same change is refused while the first is going; `--anyway` starts it.

Two runs building the same change in one repository waste a round each and then collide at
landing, so `ak run` refuses a task that looks already under way there: one whose title shares
at least four significant words with a run still going, or whose checks name the same test
file.  The refusal exits 2, names the going run, whose it is, when it started and its title,
says what they share and what to do, and leaves no run behind.  Outside a seat `--anyway`
starts the second run regardless, and the run's log names the one it started beside.  Once
the first run has ended the same task starts again.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, with the first
run's executor held by fakeadapter.py until the test releases it.
"""

from datetime import datetime, timezone
import json
import re
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

TITLE = "Add retry file handling logic"     # four significant words: retry, file, handling, logic
CHECKS = ("test -f retry.txt", "test ! -e tests/test_parser.py")
REFUSAL = ("ak run: this looks already under way: {id} (nobody's, started HH:MM, \"{title}\") "
           "shares {detail}; wait for it, or add --anyway to start a second run")


class SecondRunRefused(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.release = cls.fakes["claude"].dir / "release"
        # Bounded, so a test that dies before releasing it leaves no turn waiting for ever.
        hold = {**fakeadapter.WORK, "sh": f"i=0; while [ ! -e {shlex.quote(str(cls.release))} ]"
                                          " && [ $i -lt 1500 ]; do sleep 0.2; i=$((i+1)); done"}
        cls.fakes["claude"].behave(hold, "work")
        cls.addClassCleanup(cls.settle)
        first = taskfile.write(cls.home, cls.rig.path, TITLE, done_when=CHECKS, name="first")
        before = time.time()
        launched = cls.home.ak("run", str(first), "--no-merge", "--bg")
        assert launched.code == 0, launched.out + launched.err
        cls.wait(lambda: cls.fakes["claude"].n >= 1, "the first run's executor turn")
        cls.minutes = {datetime.fromtimestamp(stamp, timezone.utc).strftime("%H:%M")
                       for stamp in range(int(before), int(time.time()) + 2)}
        cls.first = taskfile.only_run(cls.home)
        same = taskfile.write(cls.home, cls.rig.path, TITLE, name="same")
        cls.by_title = cls.launch(same)
        cls.by_file = cls.launch(taskfile.write(cls.home, cls.rig.path, "Tidy widget colours",
                                                done_when=CHECKS, name="colours"))
        cls.three_words = cls.launch(taskfile.write(cls.home, cls.rig.path,
                                                    "Add retry file handling", name="three"))
        cls.anyway = cls.launch(same, "--anyway")
        cls.settle()
        cls.after_end = cls.launch(same)

    @classmethod
    def launch(cls, task, *flags):
        """Run a task in the foreground; what it returned and the run directories it added."""
        before = set(taskfile.runs(cls.home))
        done = cls.home.ak("run", str(task), "--no-merge", *flags, timeout=300)
        return done, sorted(set(taskfile.runs(cls.home)) - before)

    @classmethod
    def wait(cls, ready, what, bound=120):
        deadline = time.monotonic() + bound
        while not ready():
            assert time.monotonic() < deadline, f"no {what} after {bound} s"
            time.sleep(0.2)

    @classmethod
    def settle(cls):
        """Let the held turn go and wait for every run to end."""
        cls.release.write_text("")
        for run_dir in taskfile.runs(cls.home):
            cls.wait(lambda: cls.state(run_dir).get("state") not in ("queued", "running"),
                     f"end of {run_dir.name}")

    @staticmethod
    def state(run_dir):
        try:
            return json.loads((run_dir / "run.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def refused(self, launched, detail):
        done, added = launched
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual(added, [], "a refused launch leaves no run")
        pattern = re.escape(REFUSAL.format(id=self.first.name, title=TITLE, detail=detail))
        pattern = pattern.replace("HH:MM", r"(\d\d:\d\d)")
        lines = [re.fullmatch(pattern, line) for line in done.err.splitlines()]
        found = [line for line in lines if line]
        self.assertEqual(len(found), 1, done.err)
        # The clock reading is the first run's start, in the host's zone (UTC in a Home).
        self.assertIn(found[0].group(1), self.minutes)

    def started(self, launched):
        done, added = launched
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(len(added), 1, added)
        self.assertEqual(self.state(added[0]).get("verdict"), "PASS")
        return (added[0] / "log.txt").read_text().splitlines()

    def test_a_task_sharing_four_title_words_with_a_going_run_is_refused_naming_it(self):
        self.refused(self.by_title, "4 title words")

    def test_a_task_whose_checks_name_the_same_test_file_is_refused_whatever_its_title(self):
        self.refused(self.by_file, "tests/test_parser.py")

    def test_three_shared_title_words_are_not_the_same_change(self):
        self.started(self.three_words)

    def test_anyway_starts_the_second_run_and_its_log_names_the_one_beside_it(self):
        expected = f"--- preflight: started alongside {self.first.name} (--anyway)"
        lines = self.started(self.anyway)
        self.assertTrue([line for line in lines if line.endswith(expected)], lines)

    def test_the_first_run_finishes_untouched_by_the_refusals_and_the_second_run(self):
        self.assertEqual(self.state(self.first).get("verdict"), "PASS")

    def test_once_the_first_run_has_ended_the_same_task_starts(self):
        lines = self.started(self.after_end)
        self.assertFalse([line for line in lines if "started alongside" in line], lines)


if __name__ == "__main__":
    unittest.main()
