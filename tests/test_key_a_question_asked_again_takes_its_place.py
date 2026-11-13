"""A question a reopened seat asks takes the place of those its ended process left open.

Its harness ended while its question was open, kept back on its card or standing, a seat comes
back told to ask it again: its next question, in any words, takes the place of all it said before,
and the owner's answer there leaves nothing (11 Nov 2026).  One whose harness never ended keeps its
standing question past another card's answer.  Black-box, as test_key_native_card_answer_scope.py
is, reopened by `ak orch NAME` on a fake Claude taking ak's line as its first prompt.
"""

import re
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PANE, Seat
from fixtures.hookdrive import Hooks
import test_key_native_card_answer_scope as scope
from test_key_native_card_answer_scope import ASKED, LAYOUT, NAMING, card, settled

AGAIN = "Should acme get the compact layout or the wide one?"     # the same, in other words
CONVERSATION = "3a4b5c6d-7e8f-4a0b-9c1d-2e3f4a5b6c"     # one apiece, its last two digits


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AQuestionAskedAgain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus"])
        cls.fake = fakeadapter.install(cls.home, claude="pass")["claude"]
        cls.hooks = Hooks(cls.home)

    # asked and standing at a turn's end, then a new turn; the owner's answer on a card; a stop
    ask, standing, answer, stop = (vars(scope.NativeCardAnswerScope)[verb]
                                   for verb in ("ask", "standing", "answer", "stop"))

    def shows(self, seat, asked):
        """The seat asks on its card: its hook keeps the question back, the card is up."""
        fired = self.hooks.fire("PreToolUse", {k: v for k, v in asked.items()
                                               if k != "tool_response"}, seat=seat.name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        seat.show("claude-question-pane.txt")

    def asks_again(self, seat):
        """Its harness ends and the owner opens the seat on the conversation Claude filed under its
        path; ak's line is its first prompt, and it asks in other words on a card he answers."""
        conversation = seat.record["conversation"]
        self.home.write(f".claude/projects/{re.sub(r'[^A-Za-z0-9]', '-', str(seat.cwd))}/"
                        f"{conversation}.jsonl",
                        '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        self.fake.answer("interactive", shlex.join([sys.executable, str(PANE),
                                                    str(seat.screen_file), str(seat.typed_file)]),
                         given=(conversation,))
        self.assertEqual(self.home.tmux("respawn-pane", "-k", "-t", seat.pane, "true").code, 0)
        deadline = time.monotonic() + 30
        while self.home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_dead}").out != "1\n":
            self.assertLess(time.monotonic(), deadline, f"{seat.name} never ended")
            time.sleep(0.05)
        done = self.home.ak("orch", seat.name, tty=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        line = next((call["env"].get("AGENTKIT_FIRST_PROMPT") for call in
                     self.fake.calls("interactive") if conversation in call["argv"]), None)
        self.assertTrue(line, f"{seat.name} came back told nothing")
        seat._settle()
        self.assertEqual(self.hooks.fire("UserPromptSubmit", {"prompt": line}, seat=seat.name,
                                         pane=seat).code, 0)
        asked = card(AGAIN, answers={AGAIN: "Compact"}, shown=["Compact", "Wide"])
        self.shows(seat, asked)
        seat.show("claude-working-pane.txt")
        self.answer(seat, asked)
        self.assertEqual(settled(self.home, seat.name, "working"), (f"{seat.name}  working", "-"))
        self.stop(seat, "acme gets the compact layout.")
        self.assertEqual(settled(self.home, seat.name, "idle"), (f"{seat.name}  idle", "-"))

    def test_standing_as_its_harness_ended_the_answer_in_other_words_leaves_nothing(self):
        seat = Seat(self.home, "acme", record={"conversation": f"{CONVERSATION}7d"})
        self.standing(seat, ASKED[LAYOUT])
        self.asks_again(seat)

    def test_kept_back_on_its_card_as_its_harness_ended_the_answer_leaves_nothing(self):
        seat = Seat(self.home, "gamma", record={"conversation": f"{CONVERSATION}7e"})
        self.hooks.prompt("go", seat)
        self.shows(seat, card(LAYOUT))
        self.assertEqual(settled(self.home, "gamma", "needs you")[0], "gamma  needs you")
        self.asks_again(seat)

    def test_never_ended_another_cards_answer_leaves_the_standing_one(self):
        seat = Seat(self.home, "beta")
        self.standing(seat, ASKED[LAYOUT])
        self.answer(seat, card(NAMING, answers={NAMING: "snake_case (Recommended)"}))
        self.stop(seat, ASKED[LAYOUT])
        self.assertEqual(settled(self.home, "beta", "needs you", ASKED[LAYOUT]),
                         ("beta  needs you", ASKED[LAYOUT]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
