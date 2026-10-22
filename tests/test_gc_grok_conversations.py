"""A Grok Build session nobody wrote to for 30 days is ended by `grok sessions delete` on its home.

Offline: HOME, PATH's `grok` and /proc are the fixture's.  The fake `grok sessions delete`
records the home it runs on and its arguments, and removes the session's folder from that home
the way 1.0.46 does.  Sessions are laid out as Grok lays them out: a folder per session under its
url-encoded cwd, in ~/.grok/sessions or an account's own ~/.grok-<account>/sessions.
"""

import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import gc, orch, retention

DAY = 86400
SESSION = "01a0aaaa-1111-7222-8333-44445555666{}"


class GcGrokConversations(Sandbox):
    def setUp(self):
        real_time = time.time
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", real_time))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100",
                                                        "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                                                        "GROK_HOME": str(self.root / "elsewhere")}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", self.proc.iterdir))
        self.stack.enter_context(patch.object(gc, "tmp_hidden_processes", return_value=None))
        bin_dir = self.root / "fake-bin"
        bin_dir.mkdir()
        self.calls = self.root / "grok-calls"
        self.grok = bin_dir / "grok"
        self.grok.write_text(f'#!/bin/sh\necho "$GROK_HOME $*" >> {self.calls}\n'
                             'rm -r "$GROK_HOME"/sessions/*/"$3"\n')
        self.grok.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"}))
        # an account whose sessions link to the usual login's, as grokbuild.sh links them
        (Path.home() / ".grok/sessions").mkdir(parents=True)
        (Path.home() / ".grok-linked").mkdir()
        (Path.home() / ".grok-linked/sessions").symlink_to(Path.home() / ".grok/sessions")

    def session(self, home, n, age):
        folder = Path.home() / home / "sessions" / "%2Ftmp%2Facme" / SESSION.format(n)
        folder.mkdir(parents=True)
        for name in ("summary.json", "updates.jsonl", "chat_history.jsonl"):
            (folder / name).write_text("{}\n")
            os.utime(folder / name, (time.time() - age, time.time() - age))
        return folder

    def test_a_session_untouched_for_thirty_days_is_deleted_by_grok_on_its_own_home(self):
        old = self.session(".grok", 1, 31 * DAY)
        account = self.session(".grok-acme", 2, 31 * DAY)
        recent = self.session(".grok", 3, 29 * DAY)
        written = self.session(".grok-acme", 4, 31 * DAY)
        os.utime(written / "updates.jsonl", (time.time() - DAY, time.time() - DAY))
        gc.gc(lambda _: None)
        self.assertFalse(old.exists() or account.exists())
        self.assertTrue(recent.exists() and written.exists())
        self.assertEqual(self.calls.read_text().splitlines(),
                         [f"{Path.home() / '.grok'} sessions delete {SESSION.format(1)}",
                          f"{Path.home() / '.grok-acme'} sessions delete {SESSION.format(2)}"])

    def test_a_session_grok_leaves_keeps_grok_alone_for_the_pass(self):
        sessions = [self.session(".grok", n, 31 * DAY) for n in (1, 2)]
        self.grok.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\necho "No session found"\n')
        said = []
        gc.gc(said.append)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertEqual(sum(line.startswith("gc: kept") for line in said), 1)
        self.assertTrue(all(folder.exists() for folder in sessions))


if __name__ == "__main__":
    unittest.main(verbosity=2)
