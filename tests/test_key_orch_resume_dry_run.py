"""`ak orch NAME --dry-run` for a seat whose harness is gone says how it would come back.

A seat tmux lost, or one whose harness exited in a pane tmux still holds, is opened again as
what it was: on its own conversation where its record names one, fresh where it names none.  A
person checks which before the real open, so the dry run says where it would resume and on
which conversation, prints the command, and starts, respawns and rewrites nothing.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, with seats from
tests/fixtures/akseat.py and the adapter fixture tests/fixtures/adapters/echo.sh.
"""

import shlex
import shutil
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akseat import Seat

ECHO = """[defaults]
orchestrator = "echo"
workers = ["echo"]

[models.echo]
harness = "echo"
model = "echo-1"
effort = "low"
provider = "test"

[providers.test]
mode = "subscription"
"""


def record(home, name):
    return home.path / ".agentkit/state" / f"session-{name}.json"


def held(home):
    """Each pane ak's tmux server holds and whether its process has exited."""
    return home.tmux("list-panes", "-a", "-F", "#{session_name} #{pane_id} #{pane_dead}").out


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class GoneFromTmux(unittest.TestCase):
    def test_a_seat_with_no_conversation_recorded_would_start_fresh(self):
        with Home() as home:
            home.write(".agentkit/config.toml", ECHO)
            shutil.copytree(REPO / "tests/fixtures/adapters", home.root / "adapters")
            code = home.path / "code"
            code.mkdir()
            kept = home.write(".agentkit/state/session-fix-api.json",
                              {"orchestrator": "echo", "workers": ["echo"], "cwd": str(code),
                               "created": 1000}).read_text()
            done = home.ak("orch", "fix-api", "--dry-run",
                           env={"AGENTKIT_ADAPTER_DIR": str(home.root / "adapters")})
            self.assertEqual(done.code, 0, done.err)
            said, command = done.out.splitlines()
            self.assertEqual(said, f"orch: resuming fix-api on echo in {code} "
                                   f"(no conversation recorded; it starts fresh)")
            self.assertEqual(shlex.split(command)[-1], "/bin/sh")   # the adapter's TUI command
            self.assertEqual(record(home, "fix-api").read_text(), kept)
            self.assertNotEqual(home.tmux("list-sessions").code, 0)   # no server was started

    def test_a_seat_with_its_conversation_recorded_would_reopen_that_one(self):
        with Home() as home:
            seat = Seat(home, "acme", alive=False)
            kept = record(home, "acme").read_text()
            done = home.ak("orch", "acme", "--dry-run")
            self.assertEqual(done.code, 0, done.err)
            said, command = done.out.splitlines()
            self.assertEqual(said, f"orch: resuming acme on opus in {seat.cwd} "
                                   f"(conversation conv-acme)")
            self.assertIn("conv-acme", shlex.split(command))
            self.assertEqual(record(home, "acme").read_text(), kept)
            self.assertNotEqual(home.tmux("list-sessions").code, 0)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ExitedInItsPane(unittest.TestCase):
    def test_it_would_resume_in_the_same_window_and_respawns_nothing(self):
        with Home() as home:
            seat = Seat(home, "beta")
            # the harness ends, and remain-on-exit keeps its pane as the seat's window
            home.tmux("respawn-pane", "-k", "-t", seat.pane, "true")
            self.wait_dead(home, seat.pane)
            before, kept = held(home), record(home, "beta").read_text()
            done = home.ak("orch", "beta", "--dry-run")
            self.assertEqual(done.code, 0, done.err)
            said, command = done.out.splitlines()
            self.assertEqual(said, "orch: resuming beta on opus in the same window "
                                   "(conversation conv-beta)")
            self.assertIn("conv-beta", shlex.split(command))
            self.assertEqual(held(home), before)
            self.assertEqual(record(home, "beta").read_text(), kept)

    def wait_dead(self, home, pane, bound=30):
        deadline = time.monotonic() + bound
        while home.tmux("display-message", "-p", "-t", pane, "#{pane_dead}").out != "1\n":
            self.assertLess(time.monotonic(), deadline, f"pane {pane} never exited")
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
