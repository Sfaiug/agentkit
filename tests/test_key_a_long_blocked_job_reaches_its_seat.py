"""An ordered job ending at a task blocked with a 1,900-character reason still reaches its seat.

The seat takes one line a composer shows whole -- no longer than the shortest `folds_over` of
the shipped manifests -- naming the job, the task, BLOCKED and a file holding the whole reason.
Black-box through AK_BIN: fake adapters and GitHub in acme/widget, and the seat that launched
the job.
"""

import json
import sys
import time
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, REPO, Home, boxable, rerun_boxed
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

REASON = ("The done-when command reads fixtures/api.json, which the task never names, so no "
          "change can make it pass; " * 20)[:1899] + "."
MOST = min(fold for path in (REPO / "adapters").glob("*.toml")
           if (fold := tomllib.loads(path.read_text()).get("screen", {}).get("folds_over")))


def wait_for(read, bound=180):
    deadline = time.monotonic() + bound
    while not (seen := read()):
        if time.monotonic() > deadline:
            raise AssertionError("the job did not reach its expected state")
        time.sleep(.1)
    return seen


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ALongBlockedJobReachesItsSeat(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        rig = Rig(home, "widget")
        GitHub(home)
        seat = Seat(home, "acme", cwd=rig.path, planned=True,
                    record={"workers": ["opus"], "reviewers": ["astra"]})
        fakeadapter.install(home, codex="pass", claude={"final": "Blocked.",
                                                        "hand_in": [["blocked", REASON]]})
        tasks = [taskfile.write(home, rig.path, f"Add {name}", name=name,
                                done_when=(f"test -f {name}.txt",)) for name in "ab"]
        done = home.ak("run", *map(str, tasks), "--in-order", "--bg",
                       env={"AGENTKIT_SESSION": seat.name})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.directory, = (home.path / ".agentkit/jobs").iterdir()
        job = self.directory / "job.json"
        wait_for(lambda: json.loads(job.read_text()).get("finished_at"))
        self.lines = seat.wait_lines(1)

    def test_its_seat_takes_one_line_that_fits_and_names_where_the_rest_is(self):
        line, = self.lines
        self.assertLessEqual(len(line), MOST, line)
        self.assertTrue(line.startswith(f"job {self.directory.name}: a.md: BLOCKED: "), line)
        self.assertTrue(line.endswith(". Decide the next step."), line)
        named = line.rpartition("Result: ")[2].removesuffix(". Decide the next step.")
        whole = Path(named.replace("~", str(self.home.path), 1) if named.startswith("~/")
                     else named)
        self.assertIn(REASON, whole.read_text())


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
