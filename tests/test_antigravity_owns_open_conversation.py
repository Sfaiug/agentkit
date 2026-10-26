"""An Antigravity seat owns the conversation its own launch's agy holds open, once and for good.

A fake process table under the test's HOME stands for /proc: each process its environment and
fd links into agy's store.  What a launch was seen holding outlives the process; a database
held by a stale launch, one another seat owns, or one of two held at once is never the seat's.
"""

import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config
from agentkit.harness import antigravity


class OwnsOpenConversation(Sandbox):
    def setUp(self):
        super().setUp()
        self.proc = self.root / "proc"
        self.stack.enter_context(patch.object(antigravity, "PROC", self.proc))
        self.store = self.root / ".gemini/antigravity-cli/conversations"
        self.store.mkdir(parents=True)
        self.pids = 100

    def seat(self, name):
        """A seat launched the usual way: its record, and the token its command carries."""
        config.session_path(name).write_text(json.dumps({"orchestrator": "gemini"}))
        return antigravity.launched(name, self.root, None)[antigravity.LAUNCH_ENV]

    def agy(self, token, *conversations):
        """A process carrying that launch's token, holding each conversation's files open."""
        self.pids += 1
        fd = self.proc / str(self.pids) / "fd"
        fd.mkdir(parents=True)
        (fd.parent / "environ").write_bytes(f"HOME=x\0{antigravity.LAUNCH_ENV}={token}\0".encode())
        files = [f"{c}{suffix}" for c in conversations for suffix in (".db", ".db-wal", ".db-shm")]
        for number, name in enumerate(["../conversation_summaries.db", *files]):
            (fd / str(number)).symlink_to(self.store / name)
        return fd.parent

    def owns(self, name):
        return antigravity.conversation(config.session_records()[name])

    def test_what_its_agy_holds_is_its_own_after_the_process_ends(self):
        process = self.agy(self.seat("acme"), "c-acme")
        self.assertEqual(self.owns("acme"), "c-acme")
        for path in sorted(process.rglob("*"), reverse=True):
            path.rmdir() if path.is_dir() and not path.is_symlink() else path.unlink()
        self.assertEqual(self.owns("acme"), "c-acme")

    def test_another_seats_a_stale_launchs_or_one_of_two_is_never_its_own(self):
        stale = self.seat("acme")
        self.agy(stale, "c-acme")
        self.assertEqual(self.owns("acme"), "c-acme")
        self.agy(self.seat("beta"), "c-acme")
        self.assertIsNone(self.owns("beta"))
        self.seat("acme")                      # relaunched: the stale launch's agy runs on
        self.agy(stale, "c-later")
        self.assertIsNone(self.owns("acme"))
        self.agy(self.seat("gamma"), "c-one", "c-two")
        self.assertIsNone(self.owns("gamma"))

    def test_a_host_without_a_process_table_owns_nothing(self):
        self.seat("acme")
        self.assertIsNone(self.owns("acme"))


if __name__ == "__main__":
    unittest.main()
