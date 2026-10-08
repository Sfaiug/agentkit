"""Unread input in a pane's own tty holds every ak line, however empty its screen looks.

A real pty pair, a fake tmux naming its slave tty, and test_tell's throwaway seats: no tmux
server or real harness. Reading the slave is the program taking its input, never a repaint.
"""

import os
import select
import subprocess
import tty
import unittest
from unittest.mock import Mock

from test_tell import SEAT, Seats
from agentkit import orch, tell, watch


class UnreadPane(Seats):
    def setUp(self):
        super().setUp()
        self.master, self.slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        tty.setraw(self.slave)
        os.set_blocking(self.slave, False)
        self.tty_reply = (0, os.ttyname(self.slave))
        self.frozen, self.keys = False, []

    def put(self, text):
        self.assertEqual(os.write(self.master, text), len(text))
        self.assertEqual(select.select([self.slave], [], [], 5)[0], [self.slave])

    def read_input(self):
        self.assertEqual(select.select([self.slave], [], [], 5)[0], [self.slave])
        return os.read(self.slave, 65536)

    def tmux(self, *args, **kwargs):
        self.assertEqual(args[args.index("-t") + 1], f"={self.seat['name']}:")
        if args[0] == "display-message":
            self.assertEqual(args, ("display-message", "-p", "-t",
                                    f"={self.seat['name']}:", "#{pane_tty}"))
            self.assertEqual(kwargs.get("socket"), orch.seat_socket(self.seat))
            self.assertIsNotNone(kwargs.get("timeout"))
            if isinstance(self.tty_reply, Exception):
                raise self.tty_reply
            return self.tty_reply
        self.assertEqual(args[0], "send-keys")
        self.keys.append(args)
        text = args[-1].encode() if "-l" in args else b"\r"
        self.put(text)
        if self.frozen:
            if "-l" in args:
                self.typed.append(args[-1])
            return 0, ""
        self.assertEqual(self.read_input(), text)
        return super().tmux(*args, **kwargs)

    def tick(self):
        tell.deliver(self.cfg, lambda _: None)

    def test_a_peer_line_stays_queued_until_the_pane_reads_its_input(self):
        self.frozen = True
        self.put(b"The owner's unread draft")
        self.tell(SEAT, "Parser merged.")
        queued = self.waiting()
        for _ in range(3):
            self.tick()
        self.assertEqual(self.keys, [])
        self.assertEqual(self.waiting(), queued)
        self.assertEqual(self.receipts(), [])
        self.assertEqual(self.read_input(), b"The owner's unread draft")
        self.frozen = False
        for _ in range(3):
            self.tick()
        self.assertEqual(self.typed, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting(), [])

    def test_a_send_left_unread_is_never_retyped_while_the_screen_stands_still(self):
        self.frozen = True
        self.tell(SEAT, "Parser merged.")
        queued = self.waiting()
        for _ in range(3):
            self.tick()
        line = self.header() + "Parser merged."
        self.assertEqual(self.typed, [line])
        self.assertEqual(len(self.keys), 1)
        self.assertEqual(len(self.receipts()), 1)
        self.assertEqual(self.waiting(), queued)
        self.assertEqual(self.read_input(), line.encode())
        self.pane = self.base.replace(self.empty, "❯ " + line + "\n")
        self.frozen = False
        for _ in range(3):
            self.tick()
        self.assertEqual(self.typed, [line])
        self.assertEqual(self.keys[-1][-1], "Enter")
        self.assertEqual(self.waiting(), [])

    def test_notices_nudges_pty_senders_and_pending_enters_share_the_guard(self):
        self.put(b"unread")
        sent, typed = Mock(return_value=(0, "")), Mock()
        for legacy in (False, True):
            self.seat["legacy"] = legacy
            self.assertFalse(watch.type_at_prompt(self.seat, "Run finished.", lambda _: None))
            self.assertFalse(watch.type_into(self.seat, "continue", lambda _: None))
            self.assertFalse(watch._send_line(self.seat, "/compact", lambda _: None,
                                               typed, send=sent))
            self.assertFalse(watch.type_checked(self.seat, "continue", lambda _: None,
                                                pending=True))
            self.assertFalse(watch._send_enter(self.seat, lambda _: None))
        sent.assert_not_called()
        typed.assert_not_called()
        self.assertEqual(self.keys, [])
        self.assertEqual(self.receipts(), [])
        self.assertEqual(self.read_input(), b"unread")

    def test_a_terminal_that_cannot_be_asked_keeps_typing_as_before(self):
        ordinary = self.root / "ordinary-file"
        ordinary.write_text("not a tty")
        for reply in ((1, "no pane"), (0, ""), (0, str(self.root / "missing-tty")),
                      (0, str(ordinary)), subprocess.TimeoutExpired("tmux", 5)):
            with self.subTest(reply=reply):
                self.tty_reply = reply
                self.assertTrue(watch._send_line(self.seat, "Run finished.", lambda _: None))
                self.assertTrue(watch._send_enter(self.seat, lambda _: None))
                self.assertEqual(self.typed[-1], "Run finished.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
