"""A red target whose repair ended without mending it gets another repair, a ladder step on.

The target's tip fails a named test alone, so the lander starts its repair and checks no member
until the target is mended.  A repair on its way holds the line, and so does one that ended
blocked, until the retry ladder's step past its top, an hour, has gone by from its end: the next
pass then starts another repair of that red, which mends the target and lands, and the member
is checked and lands after it.  Black-box: the program `AK_BIN` names checks the line from
outside through tests/fixtures/akline.py, the repairs' worker scripted by fakeadapter.py and
their GitHub by fakegh.py; the test moves the clock by putting the first repair's end back.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import _strays
from fixtures.akline import READINGS, Line
from fixtures.fakegh import GitHub

STEP = 3600     # the retry ladder's step past its top


def record(run):
    return json.loads((run / "run.json").read_text())


class ARedTargetGetsAnotherRepair(unittest.TestCase):
    def setUp(self):
        self.line = Line({"t/ok.sh": "true\n", "t/red.sh": "test -f retry.txt\n"})
        self.addCleanup(self.line.close)
        home = self.line.home
        home.env.update(AK_HOST_READINGS=READINGS)
        GitHub(home).grant(self.line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        self.worker, self.release = fakes["claude"], fakes["claude"].dir / "release"
        # the first repair's turn waits for the test, then hands in blocked; the next writes the
        # retry.txt the target lacks (`work`)
        self.worker.behave(
            {"sh": f"until [ -f '{self.release}' ]; do sleep 0.1; done", "final": "Blocked.",
             "hand_in": [["blocked", "the fixture needs the owner"]]}, "work")
        home.write(".agentkit/state/session-seat.json", {"orchestrator": "opus", "workers": ["opus"]})
        self.line.member({"work.txt": "work\n"})
        path = self.line.members[0] / "run.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "launched_session": "seat"}))

    def repairs(self):
        runs = self.line.members[0].parent
        return sorted((path for path in runs.iterdir()
                       if path.is_dir() and path not in self.line.members),
                      key=lambda path: record(path)["started_at"])

    def land(self):
        done = self.line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return done

    def until(self, what, why, timeout=300):
        deadline = time.monotonic() + timeout
        while not what():
            self.assertLess(time.monotonic(), deadline, why)
            time.sleep(0.2)

    def ended(self, run, ago):
        """Put `run`'s end `ago` seconds back."""
        (run / "run.json").write_text(json.dumps({**record(run), "finished_at": time.time() - ago}))

    def landed(self):
        if "land" in self.line.verdict(1):
            return True
        self.land()     # where the line's own lander has not checked it yet
        return False

    def test_a_repair_that_ended_blocked_gets_another_a_step_after_its_end(self):
        self.land()
        first, = self.repairs()
        self.until(lambda: self.worker.n >= 1, "the first repair never took a turn")
        # on its way, it holds the line: a pass starts no other
        self.land()
        self.assertEqual(self.repairs(), [first])
        self.assertEqual(set(self.line.verdict(1)), {"line", "joined"})
        self.release.touch()
        self.until(lambda: record(first)["state"] == "blocked"
                   and record(first)["pid"] not in _strays(self.line.home.path),
                   "the first repair never ended blocked")
        # ended blocked, it holds the line until the step has gone by from its end
        for ago in (0, STEP - 600):
            self.ended(first, ago)
            self.land()
            self.assertEqual(self.repairs(), [first], ago)
            self.assertEqual(set(self.line.verdict(1)), {"line", "joined"})
        self.ended(first, STEP + 1)
        done = self.land()
        repairs = self.repairs()
        self.assertEqual(len(repairs), 2, done.out + done.err)
        second = record(repairs[1])
        self.assertIn(second["state"], ("queued", "running"))
        self.assertEqual((second["repair"], second["repair_tip"]),
                         (record(first)["repair"], record(first)["repair_tip"]))
        # the second mends the target and lands; the member is checked and lands after it
        self.until(lambda: record(repairs[1]).get("merged"), "the second repair never merged", 600)
        self.until(self.landed, "the member was never checked after the repair landed")


if __name__ == "__main__":
    unittest.main()
