"""`ak run gc` ends ak's own copy of a Claude conversation no seat holds once nobody wrote to it
for 30 days, and only ak's copy: Claude's transcript, the same file, is Claude's to end.

A Claude seat holds conversation A as its current one and B as one it left.  ak keeps a copy of
each, and of C, which no seat holds, all three last written forty days ago, and of D, which no
seat holds either, written five days ago.  gc ends C's copy alone, as its dry run says it will,
and A's and B's once the seat's record is gone; every transcript of Claude's own stays.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, boxed
with a /tmp and processes of its own.
"""

import os
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, boxable, Home
from fixtures.garbage import DAY, ROOM

BOX = ("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "--unshare-pid", "--proc", "/proc")
CONVERSATION = "5f0c2a7e-1b3d-4e8f-9a6b-0c1d2e3f4a5{}"
AGES = {"a": 40 * DAY, "b": 40 * DAY, "c": 40 * DAY, "d": 5 * DAY}


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class KeptCopies(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        cwd = str(home.path / "code/acme")
        # where Claude Code files a short path's transcripts
        project = re.sub(r"[^A-Za-z0-9]", "-", cwd)
        self.transcripts, self.copies = {}, {}
        for n, ago in AGES.items():
            conversation = CONVERSATION.format(n)
            self.transcripts[n] = home.write(f".claude/projects/{project}/{conversation}.jsonl",
                                             '{"type": "user"}\n', ago=ago)
            self.copies[n] = home.path / f".agentkit/state/conversations/claude-{conversation}.jsonl"
            self.copies[n].parent.mkdir(parents=True, exist_ok=True)
            os.link(self.transcripts[n], self.copies[n])
        self.record = home.write(".agentkit/state/session-acme-opus.json", {
            "orchestrator": "opus", "cwd": cwd, "conversation": CONVERSATION.format("a"),
            "left": [{"harness": "claude", "conversation": CONVERSATION.format("b"),
                      "cwd": cwd}]})

    def gc(self, *args):
        done = self.home.run(*self.home.box(BOX), AK, "run", "gc", *args, env=ROOM)
        self.assertEqual((done.code, done.err), (0, ""))
        return done.out

    def kept(self):
        return {n for n, path in self.copies.items() if os.path.lexists(path)}

    def test_gc_ends_only_unheld_stale_copies_and_a_seats_once_its_record_is_gone(self):
        planned = {line.split()[4].removesuffix(":") for line in self.gc("--dry-run").splitlines()
                   if line.startswith("gc: would remove conversation ")}
        self.assertEqual(planned, {str(self.copies["c"])})
        self.gc()
        self.assertEqual(self.kept(), {"a", "b", "d"})
        self.assertTrue(all(path.exists() for path in self.transcripts.values()))
        self.record.unlink()
        self.gc()
        self.assertEqual(self.kept(), {"d"})
        self.assertTrue(all(path.exists() for path in self.transcripts.values()))


if __name__ == "__main__":
    unittest.main()
