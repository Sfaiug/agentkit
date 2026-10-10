"""A seat whose subscription runs out moves to the next one and goes on, question open or not.

Claude Code 2.1.292 refuses a spent window with `You've hit your session limit · resets ...`,
and before that tells the running turn to wrap up and stop (its `usageLimitNote: wrap_up`), so
the model ends the turn itself with nothing refused.  Either way the seat resumes its
conversation on an account with room and is told to continue, even while a question it put to
the owner stands; a seat whose turn ended on its own, or whose job is done, is left idle.
A seat with no proven conversation goes on in place once its own window is back, question or
not; a bare rate limit spends no subscription and, like any stall, waits on the answer.
While no subscription has room, the question, not the wait, is what the owner is shown and sent.
The pane is one captured from a real seat (renamed); the stage is `test_seat_account`'s.
"""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from test_seat_account import CONVERSATION, NAME, SeatAccount  # noqa: E402
from agentkit import config, notify, orch, watch  # noqa: E402

TYPE_INTO = watch.type_into     # the real one: the stage fakes it, and its veto is what counts
REFUSED = (REPO / "tests/fixtures/claude-session-limit-pane.txt").read_text(encoding="utf-8")


class SpentSeat(SeatAccount):
    def ask(self):
        notify.record(NAME, "needs", "Which end card goes on the clip?")
        self.assertTrue(watch.owner_question(notify.last(NAME)))

    def sent(self, step):
        """`step`, typing through the real veto; what reached the pane."""
        sent = []
        with patch.object(watch, "type_into", TYPE_INTO), \
                patch.object(watch, "_send_line", side_effect=lambda s, text, *a, **k:
                             sent.append(text) or True), \
                patch.object(watch, "_send_enter", return_value=True), \
                patch.object(watch, "_wait_sent", return_value=True):
            step()
        return sent

    def go_on(self):
        """The tick's continue pass; what reached the pane."""
        return self.sent(lambda: watch.continue_turns(self.cfg, self.logs.append, accounts=True))

    def transcript(self, *entries):
        slug = "".join(c if c.isalnum() else "-" for c in str(self.root))
        path = self.root / ".claude/projects" / slug / f"{CONVERSATION}.jsonl"
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))

    def entry(self, ago, kind, content, **fields):
        at = datetime.fromtimestamp(self.now - ago, timezone.utc).isoformat()
        return {"type": kind, "timestamp": at, "message": {"role": kind, "content": content},
                **fields}

    def wrapped(self, *after):
        self.transcript(
            self.entry(600, "user", "Render the remaining clips."),
            self.entry(120, "user", "[Usage limit reached; a short grace allowance remains, "
                       "then this turn is cut off without warning.]", isMeta=True,
                       usageLimitNote="wrap_up"),
            self.entry(60, "assistant", [{"type": "text", "text": "Your usage limit was "
                                          "reached, so I'm stopping here."}]),
            *after)

    def test_a_refused_seat_with_its_question_open_moves_and_goes_on(self):
        self.meters(20, 20)       # only the refusal on its screen says the window is spent
        self.ask()
        self.pane = REFUSED
        self.refusal_tick()
        record = config.session_records()[NAME]
        self.assertEqual(record["account"], "second")
        self.assertEqual(record["conversation"], CONVERSATION)
        self.assertEqual(self.go_on(), [watch.ACCOUNT_LINE])
        self.assertTrue(watch.owner_question(notify.last(NAME)))   # still the owner's to answer

    def test_a_seat_kept_in_place_goes_on_after_its_reset_question_open(self):
        config.save_session(self.cfg, NAME, "opus", ["astra"], {
            "cwd": str(self.root), "account": "default", "conversation": None, "id_source": None})
        self.meters(20, 20)
        self.ask()
        self.pane = REFUSED
        self.refusal_tick()
        self.assertTrue(watch.seat_read(NAME).get("usage_wait"))
        self.now += 2 * 86400
        self.meters(20, 20)
        self.pane = "❯"
        self.assertEqual(self.sent(self.tick), [watch.keystroke("claude", "❯")])
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))
        self.assertTrue(watch.owner_question(notify.last(NAME)))

    def test_a_bare_rate_limit_under_an_open_question_waits_on_the_answer(self):
        self.meters(30, 20)
        self.ask()
        self.pane = "API Error: 429 rate limit"

        def ticks():
            for wait in (0, watch.STALL_WAIT, watch.GIVE_UP):
                self.now += wait
                self.meters(30, 20)
                self.tick()
        self.assertEqual(self.sent(ticks), [])
        self.assertTrue(watch.owner_question(notify.last(NAME)))

    def test_a_question_open_with_no_room_anywhere_is_what_the_owner_sees(self):
        for name, kw in (("installed_at", {"return_value": 0}), ("_attempt", {"return_value": 0}),
                         ("terminal_notice", {})):
            self.stack.enter_context(patch.object(notify, name, **kw))
        self.meters(100, 100)
        self.ask()
        for _ in range(2):
            self.tick()
            notify.transition(NAME, seat=self.seat)
            self.now += notify.CARD_WAIT + 1
            self.meters(100, 100)
        self.assertTrue(watch.seat_read(NAME).get("usage_wait"))    # kept, to go on after it
        cards = [json.loads(path.read_text())["text"] for path in notify.outbox().glob("*.json")]
        self.assertEqual(cards, ["Which end card goes on the clip?"])
        self.assertEqual(self.answer()["reason"], "Which end card goes on the clip?")

    def test_a_question_open_at_an_idle_prompt_moves_and_types_nothing(self):
        self.ask()
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertEqual(self.go_on(), [])

    def test_a_turn_the_limit_wrapped_up_goes_on_where_it_stopped(self):
        self.wrapped()
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertEqual(self.go_on(), [watch.ACCOUNT_LINE])

    def test_a_wrapped_turn_prompted_since_or_done_since_stays_idle(self):
        cases = {"prompted": lambda: self.wrapped(self.entry(30, "user", "Thanks, stop here.")),
                 "done": lambda: (self.wrapped(),
                                  notify.record(NAME, "done", "Both clips are rendered."))}
        for case, arrange in cases.items():
            with self.subTest(case), patch.object(orch, "resume", return_value="resumed"):
                arrange()
                watch.seat_write(NAME, midturn=None)
                config.update_session(NAME, account="default")
                self.tick()
                self.assertFalse(watch.seat_read(NAME).get("midturn"))
                self.assertEqual(self.go_on(), [])

    def test_only_a_spent_session_limit_is_a_refusal(self):
        plugin = orch.harness_plugin("claude")
        self.assertEqual(plugin.failure("You've hit your session limit · resets 3:20pm "
                                        "(Europe/Berlin)"), (watch.SPENT, "hit your session limit"))
        self.assertEqual(plugin.failure("You've used 84% of your session limit · resets 3:20pm"),
                         (None, None))


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the stage's run from their own file."""
    return unittest.TestSuite(SpentSeat(name) for name in loader.getTestCaseNames(SpentSeat)
                              if name in vars(SpentSeat))


if __name__ == "__main__":
    unittest.main()
