"""A review of a seat's own PR that finds no reviewer with room waits for a reviewer, not its fixer.

A FAIL on a seat's own PR is fixed by a turn on the orchestrator's model, and the next round's
review is all that is left.  When no marked reviewer has room for it, the run parks `exhausted`
saying so, and the tick brings it back once a reviewer has room, whatever the fixer's window
reads.  Until 21 Nov 2026 the run parked with the fixer's step on it and a reason naming every
worker's meter, and the tick waited for the fixer's model.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, on the fixtures of
tests/test_key_own_pr_review_resumes_its_fixer.py, its seat open so the tick reopens nothing,
and meters the test sets, which ak reads again a second after its last read, not on the
harness's own cadence.  The day astra's spent week has left passes where ak keeps its reading.
"""

import json
from pathlib import Path
import re
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_own_pr_fix_and_land import FIND, FIX, RULES

WEEK = 604800


def reading(used):
    """A usage answer: the week at `used`%, a day from rolling over."""
    return json.dumps({"meters": [{"name": "weekly", "used": used, "window_secs": WEEK,
                                   "resets_at": int(time.time()) + 86400}], "error": None})


def snapshot(home, change):
    """ak's usage snapshot as `change` leaves it, a second past ak's last read (`probe_every`)."""
    cache = home.path / ".agentkit" / "state" / "usage.json"
    blob = json.loads(cache.read_text())
    change(blob)
    cache.write_text(json.dumps(blob))
    time.sleep(1.5)


def stale(blob):
    """Every reading past the snapshot's five minutes, so the next pick reads them again."""
    blob["fetched_at"] -= 600


def astra_reset(blob):
    """Astra's week past its reset, as the day it had left would leave it."""
    for meter in blob["providers"]["openai"]["meters"]:
        meter["resets_at"] = int(time.time()) - 1


def until(shown, what, bound=120):
    deadline = time.monotonic() + bound
    while not shown():
        if time.monotonic() > deadline:
            raise AssertionError(f"not {what} after {bound} s")
        time.sleep(0.1)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AReviewerIsWaitedFor(unittest.TestCase):
    """The acme seat's orchestrator is opus, its one worker; astra alone reviews."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets", files={"AGENTS.md": RULES})
        gh = GitHub(home)
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        cls.fakes = fakes = fakeadapter.install(home, claude=FIX, codex=[FIND, "pass"])
        started, go = (fakes["claude"].dir / name for name in ("started", "go"))
        fakes["claude"].behave({**FIX, "sh": f": >{shlex.quote(str(started))}; until "
                                             f"[ -e {shlex.quote(str(go))} ]; do sleep 0.1; done"})
        for fake in fakes.values():
            text = re.sub(r"(?m)^probe_every = .*\n", "", fake.manifest.read_text())
            fake.manifest.write_text(text.replace("[usage]\n", "[usage]\nprobe_every = 1\n", 1))
            fake.answer("usage", reading(10))
        Seat(home, "acme", cwd=rig.path,
             record={"workers": ["opus"], "reviewers": ["astra"]}, planned=True)
        rig.branch("contrib", {"contrib.txt": "c\n"})
        run = home.spawn("run", "--review-pr", gh.open_pr(rig, "contrib", title="Add contrib"),
                         env={"AGENTKIT_SESSION": "acme"}, cwd=rig.path)
        until(lambda: started.exists() or run.poll() is not None, "fixing")
        # astra's window is spent while opus fixes, and read again at the next pick
        fakes["codex"].answer("usage", reading(100))
        snapshot(home, stale)
        go.touch()
        cls.code = run.wait(timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.parked = json.loads((cls.run_dir / "run.json").read_text())
        # then opus's window is spent too, and astra's is past its reset, its adapter reporting
        # the week after it
        fakes["claude"].answer("usage", reading(100))
        fakes["codex"].answer("usage", reading(0))
        snapshot(home, astra_reset)
        cls.tick = home.tick()      # which waits out the run it resumes
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_parks_waiting_for_a_reviewer(self):
        self.assertEqual(self.code, 1, self.home.log("spawn-1.err").read_text())
        self.assertEqual((self.parked["state"], self.parked["verdict"]), ("exhausted", None))
        self.assertIn("reviewer", self.parked["error"])
        self.assertNotRegex(self.parked["error"], r"worker|meter")

    def test_the_tick_resumes_it_for_its_reviewer_while_its_fixer_is_spent(self):
        self.assertEqual(self.tick.code, 0, self.tick.out + self.tick.err)
        self.assertTrue([line for line in self.tick.out.splitlines()
                         if line.startswith(f"resumed {self.run_dir.name}: ")],
                        self.tick.out + self.tick.err)

    def test_astra_reviews_and_its_verdict_stands(self):
        self.assertEqual([(turn["role"], turn["step"]) for turn in self.fakes["codex"].runs()],
                         [("reviewer", FIND), ("reviewer", "pass")])
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()], ["fixer"])
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "reviewer",
                                                               "merged")},
                         {"state": "pass", "verdict": "PASS", "reviewer": "astra",
                          "merged": True})


if __name__ == "__main__":
    unittest.main()
