"""A run's row in `ak run status` shows the round under way past its budget: `round 4/3`.

A task's run whose third review left one blocking finding goes on to a fourth round
(`extra_rounds`).  While that round is under way its row says so, whatever the run's state:
its fourth review parked on a reviewer that never answered, or its fourth fixer waiting for its
retry after its provider's error; and its result counts the round its row does, `(4 of 3)`.
A run that ended FAIL after three shows `round 3/3`, as ever, and a running one never shows
fewer rounds than it recorded.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, on a project from gitrig.py with the GitHub of fakegh.py, a
config from akconfig.py, a task from taskfile.py and scripted harnesses from fakeadapter.py,
or on a run record written under HOME.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, owner
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


def finding(path):
    """A blocking finding on `path`'s first line, proven until the line reads `ready`."""
    return ["finding", f"{path}:1", "setting is wrong", "breaks callers", "--run",
            f"grep -qx ready {path}"]


ONE = {"final": "Found one.", "hand_in": [finding("retry.txt"), ["done"]]}
THREE = {"final": "Found three.", "hand_in": [finding("retry.txt"), finding("other.txt"),
                                             finding("third.txt"), ["done"]]}
# words but no verdict: the reviewer never answers, asked once more or not
SILENT = {"final": "Looks fine."}
WORK = {"write": {"retry.txt": "wrong\n"}, "commit": "add retry.txt",
        "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
# a fixer that fixes nothing: its done waits on the finding's proof, so it disputes the finding
DISPUTE = {"final": "Disputed.", "hand_in": [
    ["dispute", "retry.txt:1", "not a defect", "--run", "true"], ["done"]]}
# ... and one that adds lines of its own, which the next review's further findings are on
DISPUTE_ADDING = {**DISPUTE, "write": {"other.txt": "wrong\n", "third.txt": "wrong\n"},
                  "commit": "add other.txt and third.txt"}
FIX = {"write": {"retry.txt": "ready\n"}, "commit": "fix retry.txt",
       "final": "## Summary\nfixed retry.txt", "hand_in": [["done"]]}


def record(run_dir):
    """run.json now, or {} while it is missing or being written."""
    try:
        return json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError):
        return {}


class Rows(unittest.TestCase):
    """One run of `Add retry file`, the harnesses scripted: opus builds and fixes, astra alone
    reviews.  `ak run status` is read once the run ended, or once `wait_for` holds of its
    record while it goes on."""

    claude = codex = ()
    wait_for = None

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        GitHub(cls.home).grant(rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakeadapter.install(cls.home, claude=list(cls.claude), codex=list(cls.codex))
        task = taskfile.write(cls.home, rig.path, "Add retry file")
        if cls.wait_for is None:
            cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=600)
            cls.run_dir = taskfile.only_run(cls.home)
            cls.state = record(cls.run_dir)
        else:
            # the run goes on until the Home's close ends it
            proc, cls.state = cls.home.spawn("run", str(task), "--no-merge"), {}
            deadline = time.monotonic() + 300
            while not cls.wait_for(cls.state):
                assert proc.poll() is None and time.monotonic() < deadline, cls.state.get("state")
                time.sleep(0.1)
                cls.run_dir = next(iter(taskfile.runs(cls.home)), None)
                cls.state = record(cls.run_dir) if cls.run_dir else {}
        cls.status = cls.home.ak("run", "status")

    def row(self):
        self.assertEqual(self.status.code, 0, self.status.err)
        rows = [line for line in self.status.out.splitlines()
                if line.startswith(self.run_dir.name)]
        self.assertEqual(len(rows), 1, self.status.out)
        return rows[0]

    def verdicts(self):
        return [summary["verdict"] for summary in self.state["round_summaries"]]

    def result(self):
        """result.md's heading and its rounds line."""
        lines = (self.run_dir / "result.md").read_text().splitlines()
        return [lines[0], *(line for line in lines if line.startswith("rounds: "))]


class FourthReviewParked(Rows):
    claude = [WORK, DISPUTE, DISPUTE, FIX]
    codex = [ONE, ONE, ONE, SILENT]

    def test_its_row_shows_round_4_of_3(self):
        self.assertNotEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["review_pending"]["round"]),
                         ("exhausted", 4))
        self.assertEqual(self.verdicts(), ["FAIL"] * 3)
        self.assertIn("round 4/3", self.row())
        heading, rounds = self.result()
        self.assertIn("(4 of 3)", heading)
        self.assertEqual(rounds, "rounds: 4 of 3")


class FourthFixerWaitingForItsRetry(Rows):
    # a 500 from the provider: its bad minute, which the run waits out before it resumes the turn
    claude = [WORK, DISPUTE, DISPUTE, "flaky", FIX]
    codex = [ONE]
    wait_for = staticmethod(lambda state: state.get("transient_wait"))

    def test_its_row_shows_round_4_of_3(self):
        self.assertEqual((self.state["state"], self.state["step"]), ("running", "executor"))
        self.assertEqual(self.verdicts(), ["FAIL"] * 3)
        self.assertIn("round 4/3", self.row())


class FailedAfterThree(Rows):
    claude = [WORK, DISPUTE, DISPUTE_ADDING]
    codex = [ONE, ONE, THREE]

    def test_its_row_shows_round_3_of_3(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.verdicts()), ("fail", ["FAIL"] * 3))
        self.assertIn("round 3/3", self.row())
        heading, rounds = self.result()
        self.assertIn("(3 of 3)", heading)
        self.assertEqual(rounds, "rounds: 3 of 3")


del Rows


class FiveRecordedWhileRunning(unittest.TestCase):
    def test_its_row_shows_round_5_of_3(self):
        with Home() as home:
            # a running run is owned by a live process, or the listing calls it interrupted
            keeper = subprocess.Popen(["sleep", "3600"], start_new_session=True)
            self.addCleanup(lambda: (keeper.kill(), keeper.wait()))
            run_id = "20261120-0900-fix-api"
            home.write(f".agentkit/runs/{run_id}/run.json", {
                "run_id": run_id, "title": "Fix API", "executor": "opus", "reviewer": "astra",
                "state": "running", "rounds": 3, "started_at": time.time() - 600,
                "round_summaries": [{"round": n, "verdict": "FAIL", "finding_count": 1}
                                    for n in range(1, 6)], **owner(keeper.pid)})
            done = home.ak("run", "status")
            self.assertEqual(done.code, 0, done.err)
            rows = [line for line in done.out.splitlines() if line.startswith(run_id)]
            self.assertEqual(len(rows), 1, done.out)
            self.assertIn("● working", rows[0])
            self.assertIn("round 5/3", rows[0])


if __name__ == "__main__":
    unittest.main()
