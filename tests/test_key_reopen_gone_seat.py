"""A seat tmux lost opens again on the conversation its record holds, from no terminal at all.

`ak orch NAME` for a seat whose process and session are gone starts it again where it ran, and
hands its harness the conversation id the record kept and only that one: what comes back is the
seat's own conversation, never a stranger's, and the record keeps owning it.  A run or an agent
reopens a dead seat this way without a terminal, which a new seat never opens without.  Where
the harness has not written that conversation down yet, the id is handed over as one to open
rather than one to resume.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and the seat is only its record (tests/fixtures/akseat.py).
"""

import json
import re
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

OWNED = "0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f"     # acme's conversation, which Claude wrote down
UNOPENED = "6e1d2c3b-4a5f-4e6d-9c8b-7a6f5e4d3c2b"  # beta's, which nobody has typed into yet
REOPENED = "2d4f6a8c-0e1b-4d3f-a5c7-e9b1d3f5a7c9"  # fix-api's, which is reopened for real


def contains(words, run):
    return any(words[i:i + len(run)] == run for i in range(len(words)))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ReopenGoneSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.seats = {name: Seat(cls.home, name, record={"conversation": conversation},
                                alive=False)
                     for name, conversation in (("acme", OWNED), ("beta", UNOPENED),
                                                ("fix-api", REOPENED))}
        # Claude files a workspace's conversations under its path, each character that is not
        # a letter or a digit a dash; a transcript there is a conversation it has opened.
        for name in ("acme", "fix-api"):
            seat = cls.seats[name]
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            cls.home.write(f".claude/projects/{folder}/{seat.record['conversation']}.jsonl",
                           '{"type":"user","message":{"role":"user","content":"hello"}}\n')

    def record(self, name):
        return json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())

    def planned(self, name):
        """What `--dry-run` says reopening that seat would do: its line and its command."""
        done = self.home.ak("orch", name, "--dry-run")
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        return lines[0], shlex.split(lines[-1])

    def test_the_harness_resumes_the_conversation_the_record_holds(self):
        line, command = self.planned("acme")
        self.assertEqual(line, f"orch: resuming acme on opus in {self.seats['acme'].cwd} "
                               f"(conversation {OWNED})")
        self.assertTrue(contains(command, ["claude", "--resume", OWNED]), command)

    def test_a_conversation_never_opened_is_handed_over_as_one_to_open(self):
        line, command = self.planned("beta")
        self.assertEqual(line, f"orch: resuming beta on opus in {self.seats['beta'].cwd} "
                               f"(conversation {UNOPENED})")
        self.assertTrue(contains(command, ["claude", "--session-id", UNOPENED]), command)
        self.assertNotIn("--resume", command)

    def test_a_dry_run_opens_nothing(self):
        self.planned("beta")
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=beta").code, 0)

    def test_the_seat_opens_again_where_it_ran_without_a_terminal(self):
        seat = self.seats["fix-api"]
        done = self.home.ak("orch", "fix-api")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[0], f"orch: resuming fix-api on opus in "
                                                   f"{seat.cwd} (conversation {REOPENED})")
        shown = self.home.tmux("display-message", "-p", "-t", "=fix-api:",
                               "#{session_name}\t#{session_path}\t#{@ak_orch}")
        self.assertEqual(shown.code, 0, shown.err)
        self.assertEqual(shown.out, f"fix-api\t{seat.cwd}\t1\n")
        kept = self.record("fix-api")
        self.assertEqual((kept["conversation"], kept["id_source"]), (REOPENED, "launcher"))


if __name__ == "__main__":
    unittest.main()
