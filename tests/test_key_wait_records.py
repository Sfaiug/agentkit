"""`ak wait` records a seat's wait on a run still going, or on an open pull request a going run
reviews or lands, and refuses one already over, saying why.

The wait is the seat's own word, kept in its record (`state/seat-<seat>.json`'s `wait`: what it
is on, its kind and when it began), which the tick reads to tell the seat once that is over.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, the seat
its name in the environment, as a seat's `ak` has it, runs records under its HOME and GitHub the
fake of tests/fixtures/fakegh.py.
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RUN = "20261031-0900-fix-api"           # going, no seat's
REVIEW = "20261031-0901-review-cli"     # going, the seat `beta`'s, reviewing PR 1
OWN = "20261031-0902-fix-db"            # going, the seat `owner`'s, landing PR 2
STALLED = "20261031-0903-fix-docs"
PASSED = "20261031-0904-fix-cli"        # ended PASS, merged
FAILED = "20261031-0905-fix-ui"         # ended FAIL, not merged
GONE = "20261031-0906-fix-ci"           # its directory left, its record empty
# a member of its line is going till its lander ends it, whatever process holds it
LINE = {"state": "waiting", "waiting_on": {"line": "acme/widgets"}}


def pr(number):
    return f"https://github.com/acme/widgets/pull/{number}"


class WaitRecordsASeatsWait(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig, gh = Rig(home), GitHub(home)
        for n in range(1, 6):
            sha = rig.branch(f"change-{n}", {f"f{n}.py": f"x = {n}\n"})
            assert gh.open_pr(rig, f"change-{n}") == pr(n)
        gh.edit(3, state="MERGED", mergeCommit={"oid": sha})
        gh.edit(4, state="CLOSED")
        for run_id, fields in ((RUN, LINE), (REVIEW, {**LINE, "review_pr": pr(1),
                                                      "launched_session": "beta"}),
                               (OWN, {**LINE, "pr": pr(2), "launched_session": "owner"}),
                               (STALLED, {"state": "stalled"}),
                               (PASSED, {"state": "pass", "verdict": "PASS", "merged": True,
                                         "finished_at": time.time() - 60}),
                               (FAILED, {"state": "fail", "verdict": "FAIL",
                                         "finished_at": time.time() - 60})):
            home.write(f".agentkit/runs/{run_id}/run.json",
                       {"run_id": run_id, "title": run_id[14:], **fields})
        home.write(f".agentkit/runs/{GONE}/run.json", {})

    def wait(self, seat, on):
        env = {"AGENTKIT_SESSION": seat} if seat else None
        return self.home.ak("wait", on, env=env)

    def record(self, seat):
        path = self.home.path / f".agentkit/state/seat-{seat}.json"
        return path.read_bytes() if path.exists() else None

    def assert_waits(self, seat, on, kind, shown, recorded=None):
        before = time.time()
        done = self.wait(seat, on)
        after = time.time()
        self.assertEqual((done.code, done.out), (0, f"{seat}: waiting on {shown}\n"), done.err)
        wait = json.loads(self.record(seat))["wait"]
        self.assertEqual((wait["on"], wait["kind"]), (recorded or on, kind))
        self.assertTrue(before <= wait["at"] <= after, wait)

    def assert_refused(self, seat, on, *why):
        kept = self.record(seat)
        done = self.wait(seat, on)
        self.assertEqual(done.code, 1, done.out + done.err)
        for words in why:
            self.assertIn(words, done.err)
        self.assertEqual(self.record(seat), kept)
        return done.err

    def test_outside_a_seat_or_on_neither_a_pr_nor_a_run_it_refuses_and_writes_nothing(self):
        for seat, word in ((None, RUN), (None, pr(1)), ("acme", "beta"),
                           ("acme", "https://github.com/acme/widgets/issues/1"),
                           ("acme", "20261031-0999-no-such-run")):
            with self.subTest(seat=seat, word=word):
                before = self.home.tree()
                done = self.wait(seat, word)
                self.assertEqual(done.code, 1, done.out + done.err)
                self.assertEqual(self.home.tree(), before)

    def test_a_going_run_is_waited_on(self):
        self.assert_waits("acme", RUN, "run", f"run {RUN}")

    def test_an_open_pr_a_going_run_reviews_or_lands_is_waited_on(self):
        self.assert_waits("acme", pr(1), "pr", "PR #1")
        self.assert_waits("beta", pr(2), "pr", "PR #2")

    def test_a_pr_the_seats_own_going_run_reviews_or_lands_is_waited_on_as_that_run(self):
        self.assert_waits("beta", pr(1), "run", f"run {REVIEW}, on PR #1", recorded=REVIEW)
        self.assert_waits("owner", pr(2), "run", f"run {OWN}, on PR #2", recorded=OWN)

    def test_a_second_wait_replaces_the_first(self):
        self.assert_waits("twice", RUN, "run", f"run {RUN}")
        self.assert_waits("twice", pr(1), "pr", "PR #1")

    def test_what_is_already_over_is_refused_saying_why_and_the_record_kept(self):
        self.assert_waits("late", RUN, "run", f"run {RUN}")
        self.assert_refused("late", PASSED, "PASS", "merged")
        self.assertNotIn("merged", self.assert_refused("late", FAILED, "FAIL"))
        self.assert_refused("late", STALLED, f"ak run resume {STALLED}")
        self.assert_refused("late", GONE, f"run {GONE} is gone; nothing is left to wait on")
        self.assert_refused("late", pr(3), "PR #3 merged")
        self.assert_refused("late", pr(4), "PR #4 closed")
        self.assert_refused("late", pr(5), "PR #5 is open with no ak run going on it")
        self.assert_refused("late", pr(9), pr(9), "Could not resolve to a PullRequest")

    def test_a_seat_whose_plan_is_done_and_changes_live_is_refused(self):
        self.assert_waits("done", RUN, "run", f"run {RUN}")
        self.home.write(".agentkit/state/plan-done.md", "- [x] Fix the api\n")
        self.assert_refused("done", RUN, "your plan is done and its changes are live")


if __name__ == "__main__":
    unittest.main()
