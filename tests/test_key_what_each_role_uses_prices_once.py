"""What each role uses, as `ak models` prints it, prices a role's task no more often than the
answer `ak models --json` prints.  Pricing it reads history.db, and saying what each role uses
priced it again for each role: the models screen held its keys for 28 seconds on a busy host
(7 Nov 2026).  The two are set side by side by how often each opens history.db or its log, by the
kernel's count (inotify), once an `ak models` has stored the lineup.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on the boards and models of
tests/test_key_role_cost_from_runs.py.  Fails against /bin/false.
"""

import ctypes
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from test_key_models_answer import ENV
from test_key_role_cost_from_runs import board

# A close between each two opens, or the kernel counts them as one.
IN_OPEN, IN_CLOSE = 0x20, 0x18
EVENT = struct.Struct("iIII")


class WhatEachRoleUsesPricesOnce(unittest.TestCase):
    def setUp(self):
        self.home = Home(tmux_log=False)
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {name: {"harness": "echo", "model": f"{name}-1"}
                                   for name in ("anvil", "bloom", "crown")},
                       settings={"companies": ["Acme"]})
        self.home.write(".agentkit/state/boards.json", board())
        self.opens()

    def opens(self, *flags):
        """How often one `ak models` with `flags` opens history.db or its log."""
        libc = ctypes.CDLL(None, use_errno=True)
        queue = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
        self.assertGreaterEqual(queue, 0, os.strerror(ctypes.get_errno()))
        self.addCleanup(os.close, queue)
        self.assertGreaterEqual(libc.inotify_add_watch(queue, os.fsencode(
            self.home.path / ".agentkit"), IN_OPEN | IN_CLOSE), 0, os.strerror(ctypes.get_errno()))
        done = self.home.ak("models", *flags, env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        events = b""
        while True:
            try:
                events += os.read(queue, 1 << 20)
            except BlockingIOError:
                break
        count, at = 0, 0
        while at < len(events):
            _, mask, _, size = EVENT.unpack_from(events, at)
            name = events[at + EVENT.size:at + EVENT.size + size].rstrip(b"\0")
            # SQLite opens the database once a process holds it, and its log at each read
            count += bool(mask & IN_OPEN and name.startswith(b"history.db"))
            at += EVENT.size + size
        return count

    def test_saying_what_each_role_uses_prices_no_task_again(self):
        answer = self.opens("--json")
        self.assertGreater(answer, 0, "the answer priced no task")
        self.assertLessEqual(self.opens(), answer)


if __name__ == "__main__":
    unittest.main()
