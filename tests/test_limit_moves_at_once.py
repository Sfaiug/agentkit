"""A Claude seat whose turn its harness ends on a usage limit moves within that hook's look.

Claude Code ends a turn that fails on an API error with `StopFailure`, not `Stop`.  The look
that event starts settles the seat's account before its word is told, as the tick does: with
another subscription having room the seat moves there at once, and no word is told before it
has moved; with none it reads `out of usage`.  A tick after the hook's look moves it no second
time.  Claude Code records the refusal after that hook begins, so the look settles only once the
record holds the words the hook heard.

The fixture is `test_seat_account`'s: temporary HOME, fake tmux and meters, offline.
"""

import json
import os
import unittest
from unittest.mock import patch

import test_seat_account as seats
from agentkit import config, statusbar, watch
from agentkit.harness.claude import transcript_path
from fixtures.clock import Clock

NAME = seats.NAME
LIMIT = "You've hit your weekly limit · resets 2pm (Europe/Berlin)"
READ = watch.recorded_error     # the harness's own record, which the fixture stands in for


class LimitMovesAtOnce(unittest.TestCase):
    setUp, meters, type_into, tick = (
        seats.SeatAccount.setUp, seats.SeatAccount.meters, seats.SeatAccount.type_into,
        seats.SeatAccount.tick)

    def tmux(self, *args, **kwargs):
        if args[0] == "display-message" and args[-1].startswith("#{socket_path}"):
            return 0, f"/tmp/acme-socket\t{NAME}"     # the hook runs in the seat's own pane
        return seats.SeatAccount.tmux(self, *args, **kwargs)

    def fact(self, event):
        config.record_hook_fact(NAME, {"session": NAME, "event": event, "kind": "", "text": "",
                                       "at": self.now}, lambda _: False)

    def stop_failure(self, before="PostToolUse", pane="❯"):
        """The seat was looked at on `pane` after `before`, the owner's answer by default; two
        seconds on its turn failed on the limit, and the look its StopFailure starts ran.  What
        that earlier look read, and each word the last one told, with the subscription the seat
        was on as it was told."""
        os.environ.update(TMUX="/tmp/acme-socket,1,0", TMUX_PANE="%1")
        self.fact(before)
        watch.live_state(self.seat, "claude", pane=pane, cfg=self.cfg)
        before = watch.seat_read(NAME)["state"]
        self.now += 2
        self.pane = f"● {LIMIT}\n❯"
        # the error Claude Code records as its conversation's last event
        self.stack.enter_context(patch.object(watch, "recorded_error", return_value=LIMIT))
        self.fact("StopFailure")
        told = []
        with patch.object(statusbar, "redress",
                          side_effect=lambda _session, answer, **_kw: told.append(
                              (answer["word"], config.session_records()[NAME]["account"]))):
            watch.hook_look(NAME)
        return before, told

    def test_a_turn_ended_on_the_limit_moves_to_a_subscription_with_room_in_its_look(self):
        _, told = self.stop_failure()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertEqual(len(self.commands), 1)
        self.assertIn("AGENTKIT_ACCOUNT=second", self.commands[0])
        # told only once it is on the subscription with room, where its cut turn goes on
        self.assertEqual([account for _, account in told], ["second"])
        self.tick()
        self.assertEqual(len(self.commands), 1)

    def test_a_tool_permission_granted_before_the_limit_does_not_hold_the_move(self):
        # a granted permission fires no hook: only the look after the failure sees it gone
        before, told = self.stop_failure(
            before="PermissionRequest",
            pane="Do you want to proceed?\n❯ 1. Yes\n  2. No\nEsc to cancel · Tab to amend")
        self.assertEqual(before, "asking")
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertEqual([account for _, account in told], ["second"])

    def test_its_look_settles_once_the_record_holds_its_own_words(self):
        # Before this turn's refusal lands the conversation ends on an earlier one, untyped, whose
        # words begin with these: settled on that one, the next tick parked the login it moved to.
        self.meters(20, 20)
        os.environ.update(TMUX="/tmp/acme-socket,1,0", TMUX_PANE="%1")
        # every login reads the usual one's conversations, as Claude's adapter links them
        (self.root / ".claude-second").mkdir()
        (self.root / ".claude-second/projects").symlink_to(self.root / ".claude/projects")
        record = config.session_records()[NAME]
        transcript = transcript_path(record, record["conversation"])
        transcript.parent.mkdir(parents=True, exist_ok=True)    # a long path's is hashed
        words = "You've hit your session limit · resets 1am"
        unwritten = [words]

        def refused(text, kind="usage_limit_reached"):
            with transcript.open("a") as conversation:
                print(json.dumps({"type": "assistant", "isApiErrorMessage": True, "apiError": kind,
                                  "message": {"content": [{"type": "text", "text": text}]}}),
                      file=conversation)
        refused(f"{words}\nResets at 1am (Europe/Berlin)", None)
        config.record_hook_fact(NAME, {"session": NAME, "event": "StopFailure", "kind": "",
                                       "text": words, "at": self.now}, lambda _: False)
        self.stack.enter_context(patch.object(watch, "recorded_error", READ))
        # this turn's refusal lands as the look first waits, and by its end in any case
        with patch.object(watch, "time", Clock(lambda _: unwritten and refused(unwritten.pop()))):
            watch.hook_look(NAME, records=[])
        if unwritten:
            refused(unwritten.pop())
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertEqual(watch.seat_read(NAME)["usage_refusal"]["line"],
                         f"{words}\nusage_limit_reached")
        self.tick()
        accounts = json.loads((config.STATE / "usage.json").read_text())["providers"]
        self.assertFalse(accounts["anthropic"]["accounts"]["second"].get("exhausted_until"))

    def test_with_no_room_it_reads_out_of_usage_from_that_look(self):
        self.meters(100, 100)
        _, told = self.stop_failure()
        self.assertEqual(told, [("out of usage", "default")])
        self.assertEqual(watch.seat_read(NAME)["word"], "out of usage")
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
