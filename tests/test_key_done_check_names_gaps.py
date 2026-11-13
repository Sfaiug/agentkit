"""`ak orch check SEAT` asks one model whether the seat's work holds everything its owner said
to it, and prints each gap with the owner's own words it rests on: it exits 1 with a gap, 0
with none and 2 where it could not check.

The model is given the owner's messages, the seat's plan and each run the seat launched, and
names a gap as a finding handed in with `--quote`.  One whose quote is not word for word in a
message of the owner's is no gap, whatever the model wrote in its workspace: ak decides that.
The model is the one `[done_check] model` names, else a reviewer the seat marks, and its turn
runs on the account a run's turn on its provider would take.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a Claude seat of
tests/fixtures/akseat.py whose transcript the test writes, with fake harnesses of fakeadapter.py
for the model.
"""

import json
import re
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

CONVERSATION = "3f7a2c91-8b4d-4e6a-9c1f-5d2e7a0b6c84"
FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
MADE_UP = "Paint the whole site purple."
PLANNED = "The upload page has a retry button"
TITLE = "Retry button on the upload page"
PR = "https://github.com/acme/widget/pull/7"


class DoneCheck(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fakes = fakeadapter.install(home, claude="pass", codex="pass")
        self.seen = self.fakes["codex"].dir / "seen.txt"
        seat = Seat(home, "acme", alive=False,
                    record={"conversation": CONVERSATION, "reviewers": ["astra"]})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.transcript = home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", "".join(
            json.dumps({"type": "user", "timestamp": f"2026-11-05T10:0{n}:00Z",
                        "message": {"role": "user", "content": text}}) + "\n"
            for n, text in enumerate((FIRST, SECOND))))
        home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED} · check: `true` · acme · "
                                                   "written 2026-11-05 10:05 · done 2026-11-05 11:00\n")
        run = ".agentkit/runs/20261105-1010-retry-button"
        home.write(f"{run}/run.json", {"run_id": "20261105-1010-retry-button", "title": TITLE,
                                       "launched_session": "acme", "state": "pass",
                                       "verdict": "PASS", "merged": True, "pr": PR})
        self.task = home.write(f"{run}/task.md", f"# {TITLE}\n\n## Goal\n{FIRST}\n")

    def check(self, *quotes, model=None, providers=None):
        """`ak orch check acme`, the model's turn naming a gap for each of `quotes` at whichever
        file of its workspace holds those words (MADE_UP it writes there itself), then done."""
        akconfig.write(self.home, ["opus", "astra"], providers=providers,
                       extra=f'[done_check]\nmodel = "{model}"' if model else "")
        # what the model was given: its prompt, beside its hand-in file, and its workspace
        sh = [f'cat "$(dirname "$AK_HAND_IN")/prompt.md" > {shlex.quote(str(self.seen))}',
              f"find . -type f -exec cat {{}} + >> {shlex.quote(str(self.seen))}"]
        sh += [f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- {shlex.quote(quote)} . | head -n 1):1\" "
               f"'not in the work' 'the owner asked for it' --quote {shlex.quote(quote)}"
               for quote in quotes]
        for fake in self.fakes.values():
            fake.behave({"write": {"notes.md": MADE_UP + "\n"}, "sh": "; ".join(sh),
                         "final": "Checked.", "hand_in": [["done"]]})
        return self.home.ak("orch", "check", "acme")

    def took(self):
        return {harness: fake.n for harness, fake in self.fakes.items() if fake.n}

    def test_a_gap_quoting_the_owner_exits_1_and_a_made_up_quote_is_never_one(self):
        done = self.check(SECOND, MADE_UP)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)
        self.assertNotIn(MADE_UP, done.out + done.err)
        seen = self.seen.read_text()
        for given in (FIRST, SECOND, PLANNED, TITLE, PR):
            self.assertIn(given, seen)

    def test_only_a_made_up_gap_is_no_gap_and_exits_0(self):
        done = self.check(MADE_UP)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertNotIn(MADE_UP, done.out + done.err)

    def test_without_a_done_check_model_the_seat_s_reviewer_takes_the_turn(self):
        self.assertEqual(self.check(SECOND).code, 1)
        self.assertEqual(self.took(), {"codex": 1})

    def test_the_done_check_model_takes_the_turn(self):
        done = self.check(SECOND, model="opus")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)
        self.assertEqual(self.took(), {"claude": 1})

    def test_the_turn_runs_on_the_account_a_run_s_turn_would_take(self):
        done = self.check(SECOND, model="opus", providers={
            "anthropic": {"mode": "subscription", "accounts": ["second"]}})
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual([run["env"].get("AGENTKIT_ACCOUNT")
                          for run in self.fakes["claude"].runs()], ["second"])

    def test_a_turn_that_never_closes_could_not_check_and_exits_2(self):
        akconfig.write(self.home, ["opus", "astra"])
        self.fakes["codex"].behave("silent")
        self.assertEqual(self.home.ak("orch", "check", "acme").code, 2)
        self.assertEqual(self.took(), {"codex": 1})

    def test_a_record_ak_cannot_read_could_not_check_and_exits_2(self):
        akconfig.write(self.home, ["opus", "astra"])
        self.task.unlink()
        self.task.symlink_to("/proc/self/mem")      # a file whose read fails, EIO
        self.assertEqual(self.home.ak("orch", "check", "acme").code, 2)
        self.task.unlink()
        self.transcript.unlink()
        self.transcript.mkdir()     # the owner's messages, unreadable
        self.assertEqual(self.home.ak("orch", "check", "acme").code, 2)
        self.assertEqual(self.took(), {})


if __name__ == "__main__":
    unittest.main()
