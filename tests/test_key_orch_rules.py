"""`ak orch rules CODE` is how a seat's conversation says it read the rulebook file its prompt named.

A harness reads its rulebook only when it opens, so a seat left open across a change to its
rules too long for its prompt is told to read a file on its next prompt, ending with a code, and
every prompt tells it again until that code comes back.  The code is taken only from inside the seat, from the
conversation it was given to and for the rules it was given for: a client started in the seat,
or rules that changed since the prompt, must not say the rules were read.  What is recorded --
those rules' digest for that conversation, and a copy of them -- is what the next change is
told against.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, beside a seat of tests/fixtures/akseat.py, and this test fails against
`/bin/false`.
"""

import hashlib
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akseat import Seat

SHIPPED = Path(AK).resolve().parents[1] / "orchestrator.md"   # ak's own rules, beside it
OWN = "Always write tests first.\n"                             # this host's, in rules.md
CODE = "3f2a9c81d0e4"
IN_SEAT = {"AGENTKIT_SESSION": "fix-api"}
RECORD = ".agentkit/state/session-fix-api.json"
HELD = ".agentkit/state/held-fix-api.md"
WRONG_CODE = ("that is not the code the seat's latest prompt gave; read the rulebook that "
              "prompt names and run the code it gives")


def rulebook():
    """What a seat filed under no project is handed: ak's rules, then the host's own."""
    return f"{SHIPPED.read_text().rstrip()}\n\n{OWN}"


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def told(**fields):
    """What the seat's latest prompt gave conversation conv-1, for the rules it has now."""
    return {"code": CODE, "conversation": "conv-1", "sha": digest(rulebook()), **fields}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheCodeGiven(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write(".agentkit/rules.md", OWN)
        Seat(cls.home, "fix-api", record={"conversation": "conv-1", "rulebook_told": told()})
        cls.done = cls.home.ak("orch", "rules", CODE, env=IN_SEAT)
        cls.record = json.loads((cls.home.path / RECORD).read_text())
        cls.again = cls.home.ak("orch", "rules", CODE, env=IN_SEAT)

    def test_is_taken_and_says_so(self):
        self.assertEqual((self.done.code, self.done.out), (0, "rulebook read\n"), self.done.err)

    def test_records_that_its_conversation_read_those_rules_and_nothing_is_owed(self):
        self.assertEqual(self.record.get("rulebook_read"),
                         {"conversation": "conv-1", "sha": digest(rulebook())})
        self.assertIsNone(self.record.get("rulebook_told"))

    def test_keeps_a_copy_of_the_rules_read_whole(self):
        self.assertEqual((self.home.path / HELD).read_text(), rulebook())

    def test_is_not_taken_a_second_time(self):
        self.assertEqual((self.again.code, self.again.err), (2, f"ak orch: {WRONG_CODE}\n"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Refused(unittest.TestCase):
    """Each refusal exits 2 with one line saying why, and records nothing read."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write(".agentkit/rules.md", OWN)
        cls.seat = Seat(cls.home, "fix-api", record={"conversation": "conv-1"})

    def refused(self, args, why, env=IN_SEAT, **fields):
        self.home.write(RECORD, {**self.seat.record, "rulebook_told": told(), **fields})
        done = self.home.ak("orch", "rules", *args, env=env)
        self.assertEqual((done.code, done.out, done.err), (2, "", f"ak orch: {why}\n"))
        record = json.loads((self.home.path / RECORD).read_text())
        self.assertEqual(record.get("rulebook_told"), told())
        self.assertIsNone(record.get("rulebook_read"))
        self.assertFalse((self.home.path / HELD).exists())

    def test_outside_a_seat(self):
        self.refused([CODE], "ak orch rules belongs to a seat; run it inside one", env=None)

    def test_a_code_the_prompt_did_not_give(self):
        for code in ("wrongcode", ""):
            with self.subTest(code=code):
                self.refused([code], WRONG_CODE)

    def test_with_no_code_or_more_than_one_it_prints_its_usage(self):
        for args in ([], [CODE, CODE]):
            with self.subTest(args=args):
                self.refused(args, "usage: ak orch rules CODE")

    def test_when_the_rules_changed_since_the_prompt(self):
        self.addCleanup(self.home.write, ".agentkit/rules.md", OWN)
        self.home.write(".agentkit/rules.md", OWN + "Never deploy on Fridays.\n")
        self.refused([CODE], "the rules changed since that prompt; the next one names them")

    def test_from_a_conversation_the_code_was_not_given_to(self):
        self.refused([CODE], "fix-api's conversation is not the one that code was given to",
                     conversation="conv-2")


if __name__ == "__main__":
    unittest.main()
