"""A question a seat records while its turn runs reaches nobody until that turn ends.

A seat asked with `ak notify needs` and worked on: its owner got a `Needs you` card for a seat
whose screen showed no question and which was not waiting for his answer.  So the seat reads
`working` while the turn that asked runs, and `needs you` with the question once its Stop is
written, whatever its runs do; the card follows the word, and none goes out before the stop.
hooks/seat-state.sh and hooks/orchestrator-stop.sh run as the harness runs them, on their own
JSON on stdin, in a temporary HOME, with card delivery and tmux faked.
"""

import json
import os
import subprocess
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
CARD = "Needs you \u00b7 " + SEAT


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

    def looked(self, pane, fact, records=()):
        """What every screen says of the seat, its look written down as the tick writes it."""
        live = watch.classify("claude", watch.pane_tail(pane), fact, None, {}, NOW)
        watch.seat_write(SEAT, **live)
        return watch.session_state(SEAT, NOW, session={"name": SEAT, "attached": False},
                                   cfg=self.cfg, records=list(records), live=live,
                                   harness="claude", auth_out={}, gh_out={}, token_out={},
                                   previous={})

    def carded(self, now):
        notify.transition(SEAT, now=now, seat={"name": SEAT, "attached": False})
        return self.posts

    def stop(self):
        return self.hook("Stop", script="orchestrator-stop.sh", background_tasks=[],
                         last_assistant_message="The schema is yours to pick.")

    def test_the_seat_reads_working_while_the_turn_that_asked_runs(self):
        fact = self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        notify.record(SEAT, "needs", QUESTION)
        self.assertEqual(self.looked(WORKING, fact)["word"], "working")
        # Claude draws its composer mid-turn too: the hook, not the screen, says the turn runs
        self.assertEqual(self.looked(PROMPT, fact)["word"], "working")

    def test_its_stop_makes_it_needs_you_with_the_question(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        notify.record(SEAT, "needs", QUESTION)
        answer = self.looked(PROMPT, self.stop())
        self.assertEqual((answer["word"], answer["reason"]), ("needs you", QUESTION))

    def test_a_run_going_does_not_hide_a_question_the_seat_stopped_on(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        notify.record(SEAT, "needs", QUESTION)
        run = {"run_id": "acme-parser", "state": "running", "launched_session": SEAT,
               "started_at": NOW - 60}
        with patch("agentkit.run.going", return_value=True):
            answer = self.looked(PROMPT, self.stop(), [(config.RUNS / "acme-parser", run)])
        self.assertEqual(answer["word"], "needs you")

    def test_no_card_goes_out_before_the_stop_and_one_after_it(self):
        fact = self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        self.looked(WORKING, fact)
        notify.shaped("needs", QUESTION, session=SEAT)          # the command, mid-turn
        for later in (60, 600, 3600):
            self.assertEqual(self.carded(10000 + later), [])
        self.looked(PROMPT, self.stop())
        self.assertEqual(self.carded(20000), [])                # the stop begins its minute
        self.assertEqual(self.carded(20000 + notify.CARD_WAIT), [CARD])

    def test_a_hand_back_turn_neither_closes_its_card_nor_sends_another(self):
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        notify.record(SEAT, "needs", QUESTION)
        self.looked(PROMPT, self.stop())
        self.carded(20000)
        self.assertEqual(self.carded(20000 + notify.CARD_WAIT), [CARD])
        fact = self.hook("UserPromptSubmit", prompt="run acme-parser finished PASS merged.")
        self.looked(WORKING, fact)
        self.assertEqual(self.carded(21000), [CARD])
        self.looked(PROMPT, self.stop())
        for later in (0, notify.CARD_WAIT, 3600):
            self.assertEqual(self.carded(22000 + later), [CARD])
        self.assertEqual(self.closed, [])
        notify.answered(SEAT, 30000)                            # his prompt, and its turn
        self.looked(WORKING, self.hook("UserPromptSubmit", prompt="Use v2."))
        self.assertEqual(self.carded(30010), [CARD])
        self.assertEqual(self.closed, ["Answered"])

    def test_a_dialogs_card_is_not_the_questions(self):
        """A dialog went up after the seat asked: its card closes as the turn runs on, and the
        question gets its own at the stop."""
        self.hook("UserPromptSubmit", prompt="Build the acme parser.")
        notify.record(SEAT, "needs", QUESTION)
        fact = self.hook("Notification", notification_type="permission_prompt",
                         message="Claude needs your permission")
        self.assertEqual(self.looked(DIALOG, fact)["word"], "needs you")
        up = fact["at"]                 # the hook's own clock dates a dialog, not the sandbox's
        self.assertEqual(self.carded(up + notify.CARD_WAIT), [CARD])
        self.assertEqual(self.looked(AFTER_DIALOG, fact)["word"], "working")
        self.carded(up + 600)
        self.assertEqual(self.closed, ["Answered"])
        self.looked(PROMPT, self.stop())
        self.carded(up + 1200)
        self.assertEqual(self.carded(up + 1200 + notify.CARD_WAIT), [CARD, CARD])


if __name__ == "__main__":
    unittest.main(verbosity=2)
