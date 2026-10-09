"""A question a seat asks during its own turn is asked of its owner when that turn ends.

A seat asked with `ak notify needs` and worked on: its owner got a `Needs you` card for a seat
whose screen showed no question and which was not waiting for his answer.  So the command, run
in the seat it speaks for, keeps the question back in the seat's record, apart from every
notice: the seat reads, recovers and is typed into as its turn and runs say, no card goes out,
and nothing typed meanwhile answers it.  The first fresh look that finds that turn ended -- a
prompt, or a Stop on background work -- asks it, and from there it is the question it always
was: `needs you` until his answer, whatever its runs do and whatever turn a hand-back opens
meanwhile.  A question asked while one of the seat's own already stands takes its place at
once, as it always did.
hooks/seat-state.sh and hooks/orchestrator-stop.sh run as the harness runs them, on their own
JSON on stdin, in a temporary HOME, with card delivery and tmux faked.
"""

import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, orch, watch

NOW = 1_800_000_000
SEAT = "fix-api"
QUESTION = "Which schema should acme use? The parser reads both; v2 drops the legacy fields."
FIX = REPO / "tests/fixtures"
WORKING = (FIX / "claude-working-pane.txt").read_text(encoding="utf-8")
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8")
DIALOG = (FIX / "claude-question-pane.txt").read_text(encoding="utf-8")
AFTER_DIALOG = (FIX / "claude-working-after-question-pane.txt").read_text(encoding="utf-8")
CARD = "Needs you · " + SEAT
CLOCK = time.time       # the hooks' clock: the sandbox stops this process's own


class QuestionWaitsForTheStop(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        home = self.root / ".agentkit"
        home.mkdir()
        (home / "state").symlink_to(config.STATE)
        self.posts, self.closed = [], []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0

        def close_needs(previous, status):
            self.closed.extend(status for _ in previous.get("open_needs") or ())
            return []
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off",
            "AK_RUN_ROLE": ""}))
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=close_needs))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        # somebody is in the seat: a seat nobody is in names its number, whatever it asked
        self.stack.enter_context(patch.object(orch, "listing", return_value=[
            {"name": SEAT, "attached": False}]))

    def hook(self, event, script="seat-state.sh", **payload):
        """One hook call the way the harness makes it; the seat's record as it stands after."""
        done = subprocess.run(
            ["bash", str(REPO / "hooks" / script)], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": event, **payload}),
            env={"PATH": os.environ["PATH"], "HOME": str(self.root), "AGENTKIT_SESSION": SEAT,
                 "AK_RUN_ROLE": "orchestrator", "IDLE_COMPACT_STATE": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads((self.root / f".agentkit/state/hook-{SEAT}.json").read_text())

    def asks(self, question=QUESTION):
        """The seat's own `ak notify needs`, as its model runs it during a turn: on the clock
        its hooks read, which date the turn it is asked in."""
        self.says("needs", question)

    def says(self, *argv):
        with patch.object(notify.time, "time", CLOCK):
            self.assertEqual(notify.main(list(argv)), 0)

    def looked(self, pane, fact, records=(), after=0):
        """What every screen says of the seat `after` seconds on, looked at afresh and written
        down as its hook's look and a menu do it: its hooks' last fact, and its pane."""
        with patch.object(watch, "hook_facts", return_value=fact), \
                patch.object(watch, "pane_text", return_value=pane), \
                patch.object(watch.time, "time", return_value=NOW + after):
            return watch.announce_state({"name": SEAT, "attached": False}, cfg=self.cfg,
                                        look=True, records=list(records), auth_out={},
                                        gh_out={}, token_out={})

    def carded(self, after):
        """The cards sent so far, once the tick's card pass has run `after` seconds on."""
        notify.transition(SEAT, now=NOW + after, seat={"name": SEAT, "attached": False})
        return self.posts

    def stop(self, **payload):
        return self.hook("Stop", script="orchestrator-stop.sh", **{
            "background_tasks": [], "last_assistant_message": "The schema is yours to pick.",
            **payload})

    def test_the_seat_reads_working_while_the_turn_that_asked_runs(self):
        fact = self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        self.assertEqual(self.looked(WORKING, fact)["word"], "working")
        # Claude draws its composer mid-turn too: the hook, not the screen, says the turn runs
        self.assertEqual(self.looked(PROMPT, fact)["word"], "working")
        # kept back, it is no notice yet: recovery and typing treat the seat as working
        self.assertIsNone(notify.last(SEAT, include_seen=True))
        self.assertEqual(watch.seat_read(SEAT)["unasked"]["text"], QUESTION)
        for later in (60, 600, 3600):
            self.assertEqual(self.carded(later), [])

    def test_its_stop_asks_it_and_the_card_follows(self):
        fact = self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        self.assertEqual(self.looked(WORKING, fact)["word"], "working")
        answer = self.looked(PROMPT, self.stop(), after=4000)
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))
        self.assertEqual(self.carded(4001), [])                 # the stop begins its minute
        self.assertEqual(self.carded(4000 + notify.CARD_WAIT), [CARD])

    def test_a_stop_on_background_work_asks_it_too(self):
        """Its composer is open and the seat waits, however long a background shell runs."""
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        fact = self.stop(background_tasks=[{"id": "b1", "type": "local_bash"}])
        answer = self.looked(PROMPT, fact)
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))

    def test_a_run_going_does_not_hide_a_question_the_seat_stopped_on(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        run = {"run_id": "acme-parser", "state": "running", "launched_session": SEAT,
               "started_at": NOW - 60}
        with patch("agentkit.run.going", return_value=True):
            answer = self.looked(PROMPT, self.stop(), [(config.RUNS / "acme-parser", run)])
        self.assertEqual(answer["word"], "needs you")

    def test_a_turn_a_hand_back_opens_leaves_it_his_and_its_card_as_it_is(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        self.looked(PROMPT, self.stop())
        self.assertEqual(self.carded(notify.CARD_WAIT), [CARD])
        fact = self.hook("UserPromptSubmit", prompt="run acme-parser finished PASS merged.")
        answer = self.looked(WORKING, fact, after=1000)
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))
        self.looked(PROMPT, self.stop(), after=2000)
        for later in (2001, 2000 + notify.CARD_WAIT, 5600):
            self.assertEqual(self.carded(later), [CARD])
        self.assertEqual(self.closed, [])
        notify.answered(SEAT, NOW + 5000)                       # his prompt, and its turn
        fact = self.hook("UserPromptSubmit", prompt="Use v2.")
        self.assertEqual(self.looked(WORKING, fact, after=6000)["word"], "working")
        self.assertEqual(self.carded(6001), [CARD])
        self.assertEqual(self.closed, ["Answered"])

    def test_a_dialog_in_the_turn_that_asked_is_no_end_of_it(self):
        """A dialog is the turn waiting, not over: its card is the dialog's, closed as the
        turn runs on, and the question is asked at the stop with a card of its own."""
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        fact = self.hook("Notification", notification_type="permission_prompt",
                         message="Claude needs your permission")
        answer = self.looked(DIALOG, fact)
        self.assertEqual((answer["word"], answer["reason"] == QUESTION), ("needs you", False))
        self.assertEqual(self.carded(notify.CARD_WAIT), [CARD])
        self.assertEqual(self.looked(AFTER_DIALOG, fact, after=600)["word"], "working")
        self.carded(601)
        self.assertEqual(self.closed, ["Answered"])
        answer = self.looked(PROMPT, self.stop(), after=1200)
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))
        self.assertEqual(self.carded(1200 + notify.CARD_WAIT), [CARD, CARD])

    def test_what_he_types_while_the_turn_that_asked_runs_answers_nothing(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        notify.answered(SEAT, NOW)              # his line into the running turn
        answer = self.looked(PROMPT, self.stop())
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))

    def test_a_line_queued_into_the_turn_that_asked_does_not_send_its_stop_back(self):
        """A prompt typed mid-turn goes in at the next tool step and dates the turn anew."""
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        self.hook("UserPromptSubmit", prompt="run acme-lint finished PASS merged.")
        fact = self.stop()
        self.assertEqual(fact["kind"], "")              # the stop stands: not `held`
        answer = self.looked(PROMPT, fact)
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))

    def test_a_newer_question_takes_the_place_of_one_that_stands_at_once(self):
        """The owner is asked already: its card stays as it is and no second one follows."""
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        self.looked(PROMPT, self.stop())
        self.assertEqual(self.carded(notify.CARD_WAIT), [CARD])
        fact = self.hook("UserPromptSubmit", prompt="run acme-parser finished PASS merged.")
        self.asks("Ship v2 to acme today?")
        answer = self.looked(WORKING, fact, after=1000)
        self.assertEqual((answer["word"], answer["reason"]),
                         ("needs you", "Ship v2 to acme today?"))
        self.assertEqual(self.carded(1000 + notify.CARD_WAIT), [CARD])
        self.assertEqual(self.closed, [])

    def test_the_later_of_two_questions_asked_in_one_turn_is_the_one_asked(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        self.asks("Ship v2 to acme today?")
        answer = self.looked(PROMPT, self.stop())
        self.assertEqual((answer["word"], answer["reason"]),
                         ("needs you", "Ship v2 to acme today?"))

    def test_a_watchers_alert_in_the_turn_that_asked_does_not_lose_it(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        notify.shaped("needs", f"{SEAT} looks stuck", session=SEAT, event_id="stuck:1")
        answer = self.looked(PROMPT, self.stop())
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))

    def test_a_done_declared_after_it_in_the_same_turn_is_said_in_its_place(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        self.says("done", "Parser built.")
        self.assertIsNone(watch.seat_read(SEAT).get("unasked"))
        self.assertEqual(self.looked(PROMPT, self.stop())["word"], "done")

    def test_a_look_under_the_seats_typing_lock_asks_nothing_and_never_waits(self):
        """The typing lock is the notice's own: a look made under it leaves the question for
        the next look instead of waiting on the lock its own caller holds."""
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.asks()
        fact = self.stop()
        with notify.session_lock(SEAT):
            self.looked(PROMPT, fact)
            self.assertEqual(watch.seat_read(SEAT)["unasked"]["text"], QUESTION)
        answer = self.looked(PROMPT, fact)
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))
        self.assertIsNone(watch.seat_read(SEAT).get("unasked"))

    def test_asked_for_another_seat_it_is_asked_at_once(self):
        """`--session` speaks for a seat the caller is not in: no turn of its own to wait for."""
        config.save_session(self.cfg, "acme-inbox", "opus", ["astra"], {"cwd": str(self.root)})
        self.assertEqual(notify.main(["needs", QUESTION, "--session", "acme-inbox"]), 0)
        self.assertEqual(notify.last("acme-inbox")["text"], QUESTION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
