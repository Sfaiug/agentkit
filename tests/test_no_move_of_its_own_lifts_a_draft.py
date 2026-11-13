"""No move ak makes by itself lifts a draft out of a seat's input field.

`watch.seat_account` asked `carry_draft` before respawning a seat off a spent account or out of a
usage wait, so ak's editor lifted the owner's text into the pane's kept buffer, respawned the
harness with an empty field, and handed the text back on a later tick.  Every move `seat_account`
makes now waits for an empty input field instead, touching neither editor nor buffer; only the
owner's own switch (`test_switch_carries_draft.py`) lifts a draft.  Offline:
fixtures.editor_seat's seat.
"""

import json
import time
import unittest
from unittest.mock import patch

from fixtures.editor_seat import EditorSeat
from fixtures.seats import NOW, REPO, SEAT
from agentkit import aside_editor, config, orch, statusbar, usage, watch
from agentkit.harness import claude

CONVERSATION = "d6fae368-678c-444e-8032-9c5c5338c84e"
DRAFT = "and add these posts\nto the list  \n\n"


class NoMoveOfItsOwnLiftsADraft(EditorSeat):
    def setUp(self):
        super().setUp()
        self.now = NOW
        for target, name, kwargs in (
                (time, "time", {"side_effect": lambda: self.now}),
                (watch.worker, "auth_ok", {"return_value": (True, "fake seat login")}),
                (usage, "replenish", {"return_value": (False, 0)}),
                (usage, "_probe", {"side_effect": AssertionError("no real usage probes")}),
                (statusbar, "dress", {})):
            patcher = patch.object(target, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cfg["providers"]["anthropic"]["accounts"] = ["default", "second"]
        config.save(self.cfg)
        cwd = self.root / SEAT
        cwd.mkdir(parents=True, exist_ok=True)
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(cwd), "conversation": CONVERSATION,
            "id_source": orch.LAUNCHER, "account": "default"})
        transcript = claude.transcript_path({"cwd": str(cwd), "account": "default"}, CONVERSATION)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text('{"message":"unfinished task"}\n')
        self.respawns = []
        self.untouched(0)

    def tmux(self, *args, data=None, **kwargs):
        if "respawn-pane" in args:
            self.respawns.append(args)
            self.show("")
            return 0, ""
        if args[0] == "display-message" and args[-1] == "#{pane_tty}":
            return 0, str(self.tty)
        if args[0] in ("show-options", "set-option") and aside_editor.ASK not in args:
            return 0, ""
        if args[0] in ("show-environment", "set-environment", "select-pane", "run-shell"):
            return 0, ""
        return super().tmux(*args, data=data, **kwargs)

    def meters(self, first, second):
        def reading(used, reset):
            return {"provider": "anthropic", "resets": 0, "meters": [usage._normalized({
                "name": "session", "used": used, "resets_at": reset,
                "window_secs": 18000}, self.now)]}
        default = reading(first, self.now + 10800)
        other = reading(second, self.now + 10800)
        (config.STATE / "usage.json").write_text(json.dumps({
            "fetched_at": self.now, "reset_checked_at": self.now, "providers": {
                "anthropic": {**default, "accounts": {"default": default, "second": other}}}}))

    def account(self):
        return config.session_records()[SEAT]["account"]

    def move(self):
        watch.seat_account(self.cfg, self.seat, "claude", "anthropic", self.pane, False,
                           lambda _: None)

    def test_a_spent_account_leaves_a_draft_in_place_and_moves_once_the_field_is_empty(self):
        self.meters(100, 10)
        self.show(DRAFT)
        self.move()
        self.assertEqual(self.account(), "default")
        self.assertEqual(self.respawns, [])
        self.assertEqual(self.composer, DRAFT)
        self.assertEqual((self.buffers, self.keys, self.typed), ({}, [], []))
        self.assertIsNone(watch.seat_read(SEAT).get("usage_wait"))

        self.show("")
        self.move()
        self.assertEqual(self.account(), "second")
        self.assertEqual(len(self.respawns), 1)
        self.assertEqual((self.buffers, self.keys, self.typed), ({}, [], []))

    def test_usage_coming_back_after_a_wait_leaves_a_draft_in_place_until_the_field_is_empty(self):
        self.meters(100, 100)
        self.show("")
        self.move()
        self.assertIsNotNone(watch.seat_read(SEAT).get("usage_wait"))

        self.meters(100, 10)
        self.show(DRAFT)
        self.move()
        self.assertEqual(self.account(), "default")
        self.assertEqual(self.respawns, [])
        self.assertEqual(self.composer, DRAFT)
        self.assertEqual((self.buffers, self.keys, self.typed), ({}, [], []))
        self.assertIsNotNone(watch.seat_read(SEAT).get("usage_wait"))

        self.show("")
        self.move()
        self.assertEqual(self.account(), "second")
        self.assertEqual(len(self.respawns), 1)
        self.assertIsNone(watch.seat_read(SEAT).get("usage_wait"))

    def test_a_refusal_over_a_draft_waits_past_the_park_window_and_continues_once_emptied(self):
        self.meters(20, 10)     # only the refusal on the screen says the login is spent
        self.base = (REPO / "tests/fixtures/claude-session-limit-pane.txt").read_text()
        self.show(DRAFT)
        with patch.object(watch, "recorded_error", return_value=None):
            self.move()
            self.assertEqual((self.account(), self.composer, self.respawns, self.buffers,
                              self.keys), ("default", DRAFT, [], {}, []))
            self.now += usage.DRY_FOR + 60
            self.meters(20, 10)
            self.show("")
            self.move()
        self.assertEqual(self.account(), "second")
        self.assertEqual(len(self.respawns), 1)
        self.assertEqual(watch.seat_read(SEAT)["midturn"]["line"], watch.ACCOUNT_LINE)

    def test_a_tall_draft_not_read_whole_leaves_the_seat_and_its_field_untouched(self):
        self.meters(100, 10)
        self.pane = (REPO / "tests/fixtures/claude-ten-row-draft-pane.txt").read_text()
        self.composer = DRAFT
        self.move()
        self.assertEqual((self.account(), self.respawns, self.buffers, self.keys),
                         ("default", [], {}, []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
