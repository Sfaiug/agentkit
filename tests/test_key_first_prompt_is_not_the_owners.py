"""A line ak hands a relaunched seat as its first prompt is never read as its owner's.

ak relaunches a seat with a line for its harness to open on ($AGENTKIT_FIRST_PROMPT): a turn its
dead process lost goes on, as one its usage cut off does.  Its harness records that line in the
seat's conversation as it records any prompt, and the owner's messages -- `ak orch check` among
their readers -- once took it for the owner's: a real check quoted "Your turn was cut off when
its usage ran out…" as the owner's words.  A first prompt is ak's line, as one ak types is.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
Claude seat of tests/fixtures/akseat.py whose prompts are submitted as Claude keeps them
(tests/fixtures/hookdrive.py), reopened by a scripted harness of fakeadapter.py, whose fake model
then checks the seat.
"""

import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PANE, Seat
from fixtures.hookdrive import Hooks

CONVERSATION = "5b8e2d4f-1a3c-4e6b-9d7f-2c4e6a8b0d1f"
OWNER = "Add a retry button to the upload page."


def gap(quote):
    """A finding of the checking model's naming a gap on those words, which its workspace's
    conversation holds whoever said them."""
    return ["finding", "conversation.md:1", "not in the work", "the owner asked for it",
            "--quote", quote]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FirstPromptIsNotTheOwners(unittest.TestCase):
    def test_a_check_never_quotes_the_line_a_relaunch_opened_on_as_the_owner_s(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"])
            fakes = fakeadapter.install(home, claude="pass", codex="pass")
            seat = Seat(home, "acme", record={"conversation": CONVERSATION,
                                              "reviewers": ["astra"]})
            fakes["claude"].answer("interactive", shlex.join(
                [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]),
                given=(CONVERSATION,))
            hooks = Hooks(home)
            # the owner's prompt, its turn then cut off as the harness dies
            self.assertEqual(hooks.prompt(OWNER, seat).code, 0)
            done = home.tmux("respawn-pane", "-k", "-t", "=acme:", "true")
            self.assertEqual(done.code, 0, done.err)
            deadline = time.monotonic() + 30
            while home.tmux("display-message", "-p", "-t", "=acme:",
                            "#{pane_dead}").out.strip() != "1":
                self.assertLess(time.monotonic(), deadline, "the pane never died")
                time.sleep(0.05)
            done = home.ak("orch", "acme", tty=True)
            self.assertEqual(done.code, 0, done.out + done.err)
            line = fakes["claude"].calls("interactive")[-1]["env"].get("AGENTKIT_FIRST_PROMPT")
            self.assertTrue(line, "the relaunch handed its harness no first prompt")
            # the reopened harness records its first prompt as it records the owner's
            self.assertEqual(hooks.prompt(line, seat).code, 0)
            fakes["codex"].behave({"final": "Checked.",
                                   "hand_in": [gap(line), gap(OWNER), ["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual([call["code"] for call in fakes["codex"].runs()[-1]["hand_ins"]],
                             [0, 0, 0])
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(OWNER, done.out)
            self.assertNotIn(line, done.out + done.err)


if __name__ == "__main__":
    unittest.main()
