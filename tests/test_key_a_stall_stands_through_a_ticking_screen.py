"""A stalled seat is typed `continue` though a counter ticks on its screen.

Claude Code 2.1.322 draws a goal's age right-aligned over the composer, `◎ /goal active (5m)` and
later `◎ /goal active (1h)`, where the effort sits otherwise.  That row is harness chrome around
the conversation, not the conversation itself: its ticking does not restart the three-minute stand
before `continue` is typed, while a change in the conversation still restarts it.  The three
minutes are the stall's clock in ak's own record, set back rather than waited out.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each pass boxed, before
seats of tests/fixtures/akseat.py showing tests/fixtures/claude-stall-pane.txt with a goal's age.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PANE = (FIXTURES / "claude-stall-pane.txt").read_text(encoding="utf-8")
EFFORT = next(line for line in PANE.splitlines() if "/effort" in line)
WAIT = 300


def goal_pane(age, *, said="Say OK"):
    return (PANE
            .replace(EFFORT, f"◎ /goal active ({age})".rjust(len(EFFORT)), 1)
            .replace("❯ Say OK", f"❯ {said}", 1))


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class StallStandsThroughATickingScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.standing = Seat(home, "acme", screen=goal_pane("5m"))
        cls.hour = Seat(home, "acme-hour", screen=goal_pane("59m"))
        cls.moved = Seat(home, "fix-api", screen=goal_pane("5m"))
        cls.passes = [home.tick()]
        watched = state(home, "watch.json") or {}
        stalls = watched.get("stalls") or {}
        cls.back = back = time.time() - WAIT
        for name in ("acme", "acme-hour", "fix-api"):
            stall = stalls.get(name)
            assert stall, f"the first pass kept no stall for {name}: {cls.passes[0]}"
            stall.update(since=back, stall_at=back, changed_at=back)
        home.write(".agentkit/state/watch.json", watched)
        cls.standing.show(goal_pane("6m"))
        cls.hour.show(goal_pane("1h"))
        cls.moved.show(goal_pane("6m", said="Say OK\n\n● OK\n\n❯ Say OK again"))
        cls.passes.append(home.tick())

    def test_every_pass_succeeds(self):
        for done in self.passes:
            self.assertEqual(done.code, 0, done.err)

    def test_a_ticking_goal_row_does_not_restart_the_stand(self):
        self.assertEqual(self.standing.wait_lines(1), ["continue"])
        self.assertEqual(self.hour.wait_lines(1), ["continue"])

    def test_a_changed_conversation_restarts_the_stand(self):
        self.assertEqual(self.moved.lines(), [])
        self.assertEqual(self.moved.typed(), "")
        stall = state(self.home, "watch.json")["stalls"]["fix-api"]
        self.assertGreater(stall["changed_at"], self.back)


if __name__ == "__main__":
    unittest.main()
