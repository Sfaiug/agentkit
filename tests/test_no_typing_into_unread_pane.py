"""Unread input in a pane's own tty holds every ak line, however empty its screen looks.

A real pty pair, a fake tmux naming its slave tty, and test_tell's throwaway seats: no tmux
server or real harness. Reading the slave is the program taking its input, never a repaint.
"""

import os
import select
import subprocess
import tty
import unittest
from unittest.mock import Mock, patch

from test_tell import NOW, REPO, SEAT, Seats
from agentkit import config, orch, tell, watch


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

    def read_input(self, size=None):
        data = b""
        while size is None or len(data) < size:
            self.assertEqual(select.select([self.slave], [], [], 5)[0], [self.slave])
            data += os.read(self.slave, size - len(data) if size is not None else 65536)
            if size is None:
                break
        return data

    def tmux(self, *args, **kwargs):
        self.assertEqual(args[args.index("-t") + 1], f"={self.seat['name']}:")
        if args[0] == "display-message":
            self.assertEqual(args, ("display-message", "-p", "-t",
                                    f"={self.seat['name']}:",
                                    "#{pane_tty}\t#{" + orch.INPUT_TTY_OPTION + "}"))
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
        self.assertEqual(self.read_input(len(text)), text)
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

    def test_reboot_and_account_notices_keep_their_tries_while_input_is_unread(self):
        for accounts in (False, True):
            with self.subTest(accounts=accounts):
                self.frozen = True
                self.put(b"prior unread input")
                line = watch.ACCOUNT_LINE if accounts else watch.MIDTURN_LINE
                mark = {"boot": watch.boot_id(), "at": NOW - 100, "name": SEAT,
                        "tries": watch.MIDTURN_TRIES - 1}
                if accounts:
                    mark["line"] = line
                watch.seat_write(SEAT, midturn=mark)
                before = list(self.keys)
                for _ in range(watch.MIDTURN_TRIES + 1):
                    watch.continue_turns(self.cfg, lambda _: None, accounts=accounts)
                self.assertEqual(watch.seat_read(SEAT).get("midturn"), mark)
                self.assertEqual(self.keys, before)
                self.assertEqual(self.read_input(), b"prior unread input")
                self.frozen = False
                for _ in range(3):
                    watch.continue_turns(self.cfg, lambda _: None, accounts=accounts)
                self.assertEqual(self.typed.count(line), 1)
                self.assertEqual(self.keys[-1][-1], "Enter")
                self.assertIsNone(watch.seat_read(SEAT).get("midturn"))

    def test_stop_nudges_finish_the_line_that_began_before_the_terminal_froze(self):
        for harness, model in (("antigravity", "gemini"), ("muse", "spark"),
                               ("opencode", "mimo")):
            with self.subTest(harness=harness):
                config.save_session(self.cfg, SEAT, model, ["astra"], {
                    "cwd": str(self.root), "created": 10})
                self.pane = (REPO / f"tests/fixtures/{harness}-prompt-pane.txt").read_text()
                self.frozen = True
                self.keys.clear()
                watch.seat_write(SEAT, state="at_prompt", turn_began=NOW - 7200,
                                 stop_said_at=NOW - 3600, stop_nudged=None,
                                 stop_said=watch.progress_output(harness, watch.pane_tail(self.pane)))
                watch.stop_nudge(self.seat, harness, self.pane, None, [], False, lambda _: None)
                # The Enter completes this line; only a new literal line must wait for the
                # tty to drain. No pending draft or extra receipt state is needed on recovery.
                self.assertEqual(self.read_input(len(b"continue\r")), b"continue\r")
                self.frozen = False
                self.pane = (REPO / f"tests/fixtures/{harness}-working-pane.txt").read_text()
                for tick in range(1, 4):
                    with patch.object(watch.time, "time", return_value=NOW + tick * watch.STALL_WAIT * 2):
                        watch.stop_nudge(self.seat, harness, self.pane, None, [], False, lambda _: None)
                self.assertEqual([args[-1] for args in self.keys], ["continue", "Enter"])

    def test_notices_nudges_and_pty_senders_share_the_line_guard(self):
        self.put(b"unread")
        sent, typed = Mock(return_value=(0, "")), Mock()
        for legacy in (False, True):
            self.seat["legacy"] = legacy
            self.assertFalse(watch.type_at_prompt(self.seat, "Run finished.", lambda _: None))
            self.assertIsNone(watch.type_into(self.seat, "continue", lambda _: None))
            self.assertIsNone(watch._send_line(self.seat, "/compact", lambda _: None,
                                              typed, send=sent))
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
