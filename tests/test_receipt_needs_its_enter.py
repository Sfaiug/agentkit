"""A typing receipt cannot confirm bytes a pane has not read, even over an empty composer.

Real pty input, a captured Claude prompt and fake tmux; no live seat or server. The same
receipt keeps a run's hand-back and its own-PR round notice pending until Enter is read.
"""

import os
import select
import time
import tty
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch, record, run, watch, worktrees

SEAT = "acme-docs"
PROMPT = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text(encoding="utf-8")


class ReceiptNeedsEnter(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_NOTIFY_SINK": "dry-run"}))
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root), "conversation": "thread", "id_source": orch.LAUNCHER})
        self.seat = {"name": SEAT, "created": 10, "legacy": False}
        self.master, self.slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        tty.setraw(self.slave)
        os.set_blocking(self.slave, False)
        self.tty_reply = (0, os.ttyname(self.slave))
        self.pane, self.keys, self.read_text, self.read_enter = PROMPT, [], False, False
        self.stack.enter_context(patch.object(orch, "find", return_value=self.seat))
        self.stack.enter_context(patch.object(orch, "watching", return_value=True))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "at_prompt", return_value=True))
        self.stack.enter_context(patch.object(watch, "pane_text", side_effect=lambda *_a, **_kw: self.pane))
        clock = self.stack.enter_context(patch.object(watch, "time", wraps=time))
        clock.sleep.return_value = None
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.stack.enter_context(patch.object(worktrees, "_drop_told"))

    def put(self, data):
        self.assertEqual(os.write(self.master, data), len(data))
        self.assertEqual(select.select([self.slave], [], [], 5)[0], [self.slave])

    def read_input(self, data):
        self.assertEqual(select.select([self.slave], [], [], 5)[0], [self.slave])
        self.assertEqual(os.read(self.slave, len(data)), data)

    def held(self, line):
        return PROMPT.replace("❯\u00a0\n", "❯ " + line + "\n")

    def tmux(self, *args, **kwargs):
        self.assertEqual(args[args.index("-t") + 1], f"={SEAT}:")
        self.assertEqual(kwargs.get("socket"), orch.seat_socket(self.seat))
        if args[0] == "display-message":
            self.assertEqual(args[-1], "#{pane_tty}\t#{" + orch.INPUT_TTY_OPTION + "}")
            self.assertIsNotNone(kwargs.get("timeout"))
            return self.tty_reply
        self.assertEqual(args[0], "send-keys")
        self.keys.append(args[-1])
        data = args[-1].encode() if "-l" in args else b"\r"
        self.put(data)
        if "-l" in args and self.read_text:
            self.read_input(data)
            self.pane = self.held(args[-1])
        elif "-l" not in args:
            if self.read_enter:
                self.read_input(data)
            self.pane = PROMPT
        return 0, ""

    def type(self, line, **kwargs):
        return watch.type_at_prompt(self.seat, line, lambda _: None, cfg=self.cfg, **kwargs)

    def check_unread_receipt(self):
        line, marks = "Parser merged.", []
        self.assertFalse(self.type(line, receipt=marks.append))
        self.assertEqual(marks, [{"line": line, "seat": 10}])
        self.assertTrue(watch.pane_unread(self.seat))
        for _ in range(3):
            self.assertFalse(self.type(line, typed=marks[0], receipt=marks.append))
        self.assertEqual(self.keys, [line])
        self.assertEqual(len(marks), 1)
        self.read_input(line.encode())
        self.pane = self.held(line)
        self.assertFalse(self.type(line, typed=marks[0]))
        self.assertEqual(self.keys, [line, "Enter"])
        self.assertFalse(self.type(line, typed=marks[0]))
        self.read_input(b"\r")
        self.assertTrue(self.type(line, typed=marks[0]))
        self.assertEqual(self.keys, [line, "Enter"])

    def test_a_receipt_waits_for_unread_pane_text_then_completes_its_line(self):
        self.check_unread_receipt()

    def test_a_receipt_waits_for_unread_wrapper_text_then_completes_its_line(self):
        self.tty_reply = (0, str(self.root / "missing-tty") + "\t" + os.ttyname(self.slave))
        self.check_unread_receipt()

    def test_a_new_send_waits_for_its_unread_enter_before_confirming(self):
        self.read_text = True
        line, marks = "Parser merged.", []
        self.assertFalse(self.type(line, receipt=marks.append))
        self.assertEqual(self.keys, [line, "Enter"])
        self.assertFalse(self.type(line, typed=marks[0]))
        self.read_input(b"\r")
        self.assertTrue(self.type(line, typed=marks[0]))
        self.assertEqual(self.keys, [line, "Enter"])

    def test_unread_input_does_not_withhold_an_enter_completing_a_held_line(self):
        line = "Parser merged."
        self.pane = self.held(line)
        self.put(line.encode())
        mark = {"line": line, "seat": 10}
        self.assertFalse(self.type(line, typed=mark))
        self.assertEqual(self.keys, ["Enter"])
        self.read_input(line.encode() + b"\r")
        self.assertTrue(self.type(line, typed=mark))

    def test_an_unaskable_terminal_keeps_the_previous_receipt_behavior(self):
        line, marks = "Parser merged.", []
        self.assertFalse(self.type(line, receipt=marks.append))
        self.tty_reply = (1, "no terminal")
        self.assertTrue(self.type(line, typed=marks[0]))
        self.assertEqual(self.keys, [line])
        self.read_input(line.encode())

    def check_notice(self, own_pr):
        directory = self.ended("own-pr-round" if own_pr else "hand-back", owner=SEAT,
                               handback_pending=True, rounds=3, round_summaries=[{}])
        state = record.read_state(directory)
        typed = "own_pr_round_typed" if own_pr else "handback_typed"
        delivered = "own_pr_round_told" if own_pr else "handed_back"

        def tick():
            if own_pr:
                run.tell_own_pr_round(self.cfg, directory, state, lambda _: None)
            else:
                run.hand_back(state, directory, lambda _: None, self.cfg)

        tick()
        mark = record.read_state(directory)[typed]
        line = mark["line"]
        for _ in range(3):
            tick()
            saved = record.read_state(directory)
            self.assertEqual(saved.get(typed), mark)
            self.assertFalse(saved.get(delivered))
        self.assertEqual(self.keys, [line])
        self.read_input(line.encode())
        self.pane = self.held(line)
        self.read_enter = True
        tick()
        tick()
        saved = record.read_state(directory)
        self.assertTrue(saved.get(delivered))
        self.assertNotIn(typed, saved)
        self.assertEqual(self.keys, [line, "Enter"])

    def test_hand_back_keeps_its_receipt_until_enter(self):
        self.check_notice(False)

    def test_own_pr_round_keeps_its_receipt_until_enter(self):
        self.check_notice(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
