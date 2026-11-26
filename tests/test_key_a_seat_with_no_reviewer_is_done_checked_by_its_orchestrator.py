"""`ak orch check SEAT` on a seat saved with `reviewers: []` takes its turn on the seat's
orchestrator model when `[done_check] model` names none, and on the named model when it does.

A seat with a reviewer marked still refuses with `none of <seat>'s reviewers can run now` when
none of its reviewers can run.  Black-box: `AK_BIN` runs from outside through
tests/fixtures/akbin.py on a seat of tests/fixtures/akseat.py whose transcript the test writes,
with fake harnesses of tests/fixtures/fakeadapter.py, one for each model.  Fails against
`/bin/false`.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.akseat import Seat

CONVERSATION = "7d2b4e90-1a6c-4f38-b5d2-9e8a1c3f6b47"


class DoneCheckWithoutReviewer(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")

    def stage(self, *, workers=(), reviewers=(), model=None):
        """Write config (defaults all on astra, distinct from the seat's fable orchestrator)
        and seat `acme` with one owner message in its transcript."""
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"},
                       orchestrator="astra", workers=["astra"], reviewers=["astra"],
                       extra=f'[done_check]\nmodel = "{model}"' if model else "")
        seat = Seat(self.home, "acme", model="fable", alive=False,
                    record={"conversation": CONVERSATION,
                            "workers": list(workers), "reviewers": list(reviewers)})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", json.dumps(
            {"type": "user", "timestamp": "2026-11-25T10:00:00Z",
             "message": {"role": "user", "content": "Add a retry button."}}) + "\n")

    def check(self, code=0):
        """Run `ak orch check acme`, assert exit `code`, return `(done, harnesses_used)`."""
        before = {harness: fake.n for harness, fake in self.fakes.items()}
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, code, done.out + done.err)
        used = {harness for harness, fake in self.fakes.items() if fake.n > before[harness]}
        return done, used

    def test_seat_with_no_reviewer_is_checked_by_its_orchestrator_unless_model_is_named(self):
        for workers in ((), ("astra",)):
            with self.subTest(workers=workers):
                self.stage(workers=workers, reviewers=())
                _, used = self.check(code=0)
                self.assertEqual(used, {"claude"})

        self.stage(workers=(), reviewers=(), model="astra")
        _, used = self.check(code=0)
        self.assertEqual(used, {"codex"})

    def test_seat_with_unready_reviewer_still_refuses_without_falling_back(self):
        self.stage(workers=("fable",), reviewers=("astra",))
        self.fakes["codex"].answer("auth", "not logged in", code=1)
        done, used = self.check(code=2)
        self.assertIn("none of acme's reviewers can run now", done.err)
        self.assertEqual(used, set())


if __name__ == "__main__":
    unittest.main()
