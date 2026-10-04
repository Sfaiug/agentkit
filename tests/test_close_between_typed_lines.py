"""A seat closes only between the lines typed into it.

Every line ak types into a seat goes in under the seat's own lock (`notify.session_lock`), the
one a rename takes.  `ak orch stop` takes it too, around removing the seat's files, killing its
tmux session and writing the stop mark, so a line under way finishes into the seat it was meant
for and one waiting finds it closed -- never a seat opened again under the same name.  Offline:
fake HOME, fake tmux, no real seat.

Locks survive the close so senders into a reopened seat still wait on the same inode.
"""

import fcntl
import os
import threading
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import browser, config, notify, orch, run, watch

SEAT = "acme-ui"


class CloseBetweenTypedLines(Sandbox):
    def setUp(self):
        super().setUp()
        os.environ.pop(config.SESSION_ENV, None)      # the owner, who may stop any seat
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        self.seat = {"name": SEAT, "path": str(self.root), "created": 100, "attached": False,
                     "exited": False, "legacy": False}
        self.stack.enter_context(patch.object(orch, "find", side_effect=lambda name:
                                              self.seat if name == SEAT else None))
        self.stack.enter_context(patch.object(orch, "records", side_effect=config.session_records))
        self.stack.enter_context(patch.object(run, "stop_owned_runs"))
        self.stack.enter_context(patch.object(run, "release_session"))
        self.stack.enter_context(patch.object(notify, "forget_card"))
        self.stack.enter_context(patch.object(browser, "close_owned"))
        self.killed = []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))

    def tmux(self, *args, **_kw):
        if args[0] == "kill-session":
            self.killed.append(self.lock_free())
        return 0, ""

    def lock_free(self):
        """Could another process take the seat's lock now, on the file it lives in?"""
        with config.notify_path(SEAT).with_suffix(".lock").open("a") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(other, fcntl.LOCK_UN)
            return True

    def test_a_close_waits_for_the_line_being_typed_and_holds_the_lock_while_it_closes(self):
        holding, seen = threading.Event(), []

        def typer():
            # a line going in: the close, started meanwhile, has to wait for it
            with notify.session_lock(SEAT):
                holding.set()
                time.sleep(1.0)
                seen.append((SEAT in config.session_records(), list(self.killed)))

        line = threading.Thread(target=typer)
        line.start()
        holding.wait(10)
        self.assertEqual(orch.cmd_stop([SEAT]), 0)     # signal handlers: the main thread's
        line.join(10)
        self.assertEqual(seen, [(True, [])], "the seat closed under a line being typed")
        self.assertNotIn(SEAT, config.session_records())
        self.assertTrue(watch.seat_read(SEAT).get("stopped_at"))
        # while it closed, its lock was held on the very file a typer waits on
        self.assertEqual(self.killed, [False])

    def test_reopened_seat_keeps_one_typing_lock(self):
        first_typed, release_first, second_typed = (threading.Event() for _ in range(3))
        events, results, threads = [], [], []
        lock_inodes = []
        lock_path = config.notify_path(SEAT).with_suffix(".lock")

        def tmux(*args, **_kw):
            if args[0] == "kill-session":
                self.seat = None
            if args[0] == "send-keys":
                events.append(args[-1])
                if args[-1] == "first":
                    first_typed.set()
                    if not release_first.wait(10):
                        raise AssertionError("first sender was not released")
                elif args[-1] == "second":
                    second_typed.set()
            return 0, ""

        def start(*_args, **_kw):
            self.seat = {"name": SEAT, "path": str(self.root), "created": 200, "legacy": False}

        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=tmux))
        self.stack.enter_context(patch.object(orch, "start", side_effect=start))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))

        real_drop_aliases = orch.drop_aliases

        def reopen_before_last_unlink(name):
            real_drop_aliases(name)
            config.save_session(self.cfg, name, "opus", ["astra"],
                                {"cwd": str(self.root), "created": 200})
            orch.launch(name, "opus", self.root, ["fake-harness"], "new-conversation")
            first = threading.Thread(target=lambda:
                results.append(watch.type_into(dict(self.seat), "first", print)))
            threads.append(first)
            first.start()
            self.assertTrue(first_typed.wait(5), "first sender did not start")
            lock_inodes.append(lock_path.stat().st_ino)

        # Reopen after the close releases its locks, just before its old final cleanup.
        with patch.object(orch, "drop_aliases", side_effect=reopen_before_last_unlink):
            try:
                self.assertEqual(orch.cmd_stop([SEAT]), 0)
                second = threading.Thread(target=lambda:
                    results.append(watch.type_into(dict(self.seat), "second", print)))
                threads.append(second)
                second.start()
                overlapped = second_typed.wait(1)
            finally:
                release_first.set()
                for thread in threads:
                    thread.join(10)
                    self.assertFalse(thread.is_alive(), "sender left running")
        self.assertFalse(overlapped,
                         "stop removed the reopened seat's held lock: two lines overlapped; "
                         + repr(events))
        self.assertEqual(lock_path.stat().st_ino, lock_inodes[0])
        self.assertEqual(events, ["first", "Enter", "second", "Enter"])
        self.assertEqual(results, [True, True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
