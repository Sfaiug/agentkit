"""A question a reopened seat asks takes the place of those its ended process left open.

Reopened told to ask again (`watch.ASKED_LINE`) by the owner's number, the boot pass or the tick,
a seat's next question, in any words, takes the place of all it said before, at its answer and as
it becomes the notice, the owner's time one wait from the first wording (11 Nov 2026).  Offline.
"""

import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, notify, orch, questions, watch

FIRST, AGAIN = "Which layout should acme use?", "Compact or wide layout for acme?"
THIRD, NAMING = "Should acme's layout be compact?", "Which naming should acme use?"
SCOPE, LINT = "Which audit scope should acme use?", "Which linter should acme use?"


class AskedAgain(Sandbox):
    def setUp(self):
        super().setUp()
        self.now = 100.0
        for name, value in (("time", lambda: self.now), ("sleep", lambda _s: None)):
            self.stack.enter_context(patch.object(watch.time, name, value))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(watch, "seat_model", return_value=("claude", "x")))
        self.stack.enter_context(patch.object(orch, "resume", return_value="resumed"))
        config.save_session(self.cfg, "acme", "fable", ["astra"], {"cwd": str(self.root),
                            "created": 1, "conversation": "c-acme", "id_source": orch.LAUNCHER})

    def asks(self, at, question):       # mid-turn, on its card, kept back for the turn's end
        self.now = at
        watch.keep("acme", question)
        watch.seat_write("acme", state="asking")

    def answers(self, at, question):    # the owner, on that card
        self.now = at
        notify.answered("acme", at, replies=[[question, "Compact", "Wide"]])

    def turn_ends(self, at):            # a look finds it over: what stands, and its word
        self.now = at
        watch.seat_write("acme", state="at_prompt")
        watch.ask_kept_back("acme", "claude", {"state": "at_prompt"})
        return questions.pending("acme"), watch.session_state("acme")["word"]

    def standing(self, at, question):
        self.asks(at, question)
        self.turn_ends(at)

    def reopened(self, at, how="owner"):    # its process ended asking; reopened told so
        self.now = at
        if how == "owner":
            orch.reopen(self.cfg, "acme")
        elif how == "boot":
            watch.save_state({**watch.load_state(), "boot_id": "before"})
            with patch.object(watch, "boot_id", return_value=f"after {at}"):
                watch.resume_after_boot(self.cfg, log=lambda _line: None)
        else:
            with patch.object(orch, "listing", return_value=[{"name": "acme", "exited": True}]), \
                    patch.object(orch, "ensure", return_value="resumed"):
                watch.revive_seats(self.cfg, lambda _line: None)
        self.assertEqual(watch.seat_read("acme")["asked_again"], at)

    def answered_in_other_words(self, first, how):     # 1, 6
        first(100.0, FIRST)
        self.reopened(200.0, how)
        self.asks(210.0, AGAIN)
        self.answers(220.0, AGAIN)
        self.assertEqual((questions.pending("acme"), notify.last("acme")), ([], None))
        self.assertEqual(self.turn_ends(230.0), ([], "idle"))
        self.assertEqual(sorted(history.owner(0, 10_000)),     # one wait, from the first
                         [(100.0, "asked", None), (220.0, "answered", 120.0)])

    def test_kept_back_its_answer_in_other_words_leaves_nothing(self):
        self.answered_in_other_words(self.asks, "owner")

    def test_standing_its_answer_in_other_words_leaves_nothing(self):
        self.answered_in_other_words(self.standing, "tick")

    def test_cut_off_again_its_notice_asks_the_newest_wording_alone_from_the_first(self):  # 2, 6
        self.standing(100.0, FIRST)
        self.reopened(200.0)
        self.asks(210.0, AGAIN)
        self.reopened(230.0, "boot")
        self.asks(235.0, THIRD)
        self.assertEqual(self.turn_ends(240.0), ([THIRD], "needs you"))
        self.assertEqual(notify.last("acme")["asked_at"], {notify.question_key(THIRD): 100.0})
        self.answers(250.0, THIRD)
        self.assertEqual(self.turn_ends(260.0)[0], [])
        self.assertEqual(sorted(history.owner(0, 10_000)),     # one wait, from the first
                         [(100.0, "asked", None), (250.0, "answered", 150.0)])

    def asks_nothing(self, first):      # 3: it stands as it was, then its next question
        first(100.0, FIRST)
        self.reopened(200.0)
        self.assertEqual(self.turn_ends(240.0), ([FIRST], "needs you"))
        self.assertEqual(notify.last("acme")["question_times"], {notify.question_key(FIRST): 100.0})
        self.asks(300.0, NAMING)            # in its next turn

    def test_asking_nothing_kept_back_it_stands_till_its_next_question_takes_its_place(self):
        self.asks_nothing(self.asks)
        self.assertEqual(self.turn_ends(310.0), ([NAMING], "needs you"))

    def test_asking_nothing_standing_it_stands_till_its_next_question_is_answered(self):
        self.asks_nothing(self.standing)
        self.answers(310.0, NAMING)
        self.assertEqual(self.turn_ends(320.0), ([], "idle"))

    def test_never_reopened_another_cards_answer_leaves_the_standing_one(self):    # 4
        self.standing(100.0, FIRST)
        self.asks(210.0, AGAIN)
        self.answers(220.0, AGAIN)
        self.assertEqual(self.turn_ends(230.0), ([FIRST], "needs you"))

    def test_one_said_since_the_reopening_is_left_by_a_later_card_and_its_answer(self):  # 5
        self.standing(100.0, FIRST)
        self.reopened(200.0)
        self.standing(210.0, AGAIN)     # in its place
        self.standing(300.0, NAMING)
        self.asks(400.0, LINT)          # one kept back beside it, both left by this card
        self.asks(410.0, SCOPE)
        self.answers(420.0, SCOPE)
        self.assertEqual(self.turn_ends(430.0), ([AGAIN, NAMING, LINT], "needs you"))
        self.asks(500.0, SCOPE)         # and by one becoming the notice
        self.assertEqual(self.turn_ends(510.0), ([AGAIN, NAMING, LINT, SCOPE], "needs you"))


if __name__ == "__main__":
    unittest.main()
