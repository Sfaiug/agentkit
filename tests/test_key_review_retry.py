"""A review of someone else's PR that never reached GitHub is tried again, later each time.

A head is never abandoned: when the review the tick started for another person's PR ends
without its verdict on GitHub, a later tick starts another, until one gets there.  It is not
started again at once: ten minutes after the tick saw the first fail, half an hour after the
second, an hour after the third and hourly from then on, so an outage is not met with a review
every tick.  The tick writes the next try down in watch.json, and putting it in the past stands
in for the wait.  Black-box: the program `AK_BIN` names runs `ak watch` from outside, in the
box `home.tick()` of tests/fixtures/akbin.py builds, against the bare origin of gitrig.py and
the GitHub of fakegh.py, which refuses the first four reviews' posts, with a scripted reviewer
from fakeadapter.py; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

REFUSED = 4
LADDER = [600, 1800, 3600, 3600]


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux and a bwrap able to box a tick")
class RetriedLater(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig, cls.gh = Rig(home, "widgets"), GitHub(home)
        akconfig.write(home, ["opus"])
        fakeadapter.install(home, claude="pass")
        Seat(home, "inbox")      # the pass at the end is offered there, or ak opens it
        cls.head = rig.branch("fix-api", {"api.py": "x = 2\n"})
        cls.url = cls.gh.open_pr(rig, "fix-api", title="Fix api", author="beta")
        cls.gh.reply(f"api repos/{rig.slug}/pulls/1/reviews", err="HTTP 502: bad gateway\n",
                     code=1, times=REFUSED)
        cls.waits, cls.held = [], []
        for tried in range(1, REFUSED + 1):
            cls.tick()
            cls.ended(tried)
            before = time.time()
            cls.tick()
            cls.waits.append((before, time.time(), cls.note()["reviewed"][cls.url]["retry_at"]))
            cls.held.append(len(taskfile.runs(home)))
            cls.due()
        cls.tick()
        cls.last = cls.ended(REFUSED + 1)
        cls.tick()
        cls.runs = len(taskfile.runs(home))

    @classmethod
    def tick(cls):
        done = cls.home.tick()
        assert done.code == 0, done.out + done.err

    @classmethod
    def note(cls):
        return json.loads((cls.home.path / ".agentkit/state/watch.json").read_text())

    @classmethod
    def due(cls):
        """The next try, put in the past."""
        note = cls.note()
        note["reviewed"][cls.url]["retry_at"] = time.time() - 1
        cls.home.write(".agentkit/state/watch.json", note)

    @classmethod
    def ended(cls, count, bound=120):
        """The newest run's record once `count` runs have ended: a review runs detached."""
        deadline = time.monotonic() + bound
        while True:
            runs = taskfile.runs(cls.home)
            try:
                state = json.loads((runs[-1] / "run.json").read_text()) if runs else {}
            except (FileNotFoundError, ValueError):
                state = {}
            if len(runs) >= count and state.get("state") in ("pass", "fail", "error"):
                return state
            if time.monotonic() > deadline:
                raise AssertionError(f"{count} ended runs expected: {runs} {state}")
            time.sleep(0.2)

    def test_a_review_that_did_not_reach_github_is_not_started_again_at_once(self):
        self.assertEqual(self.held, [1, 2, 3, 4])

    def test_each_try_waits_ten_minutes_half_an_hour_an_hour_then_hourly(self):
        for (before, after, retry), wait in zip(self.waits, LADDER):
            with self.subTest(wait=wait):
                self.assertTrue(before + wait <= retry <= after + wait,
                                (before, after, retry))

    def test_tries_go_on_until_github_has_the_review_and_then_stop(self):
        self.assertEqual((self.last["state"], self.last["head_sha"]), ("pass", self.head))
        reviews = self.gh.pr(1)["reviews"]
        self.assertEqual([review["commit"]["oid"] for review in reviews], [self.head])
        self.assertEqual(self.runs, REFUSED + 1)


if __name__ == "__main__":
    unittest.main()
