"""A seat stalled on an error for an hour that typing has not moved asks the owner, once.

The tick types a stalled seat back past its error every few minutes, and after an hour of that
nothing it types will move it: only the owner can.  So the pass that finds the stall an hour old
types nothing and asks instead: the seat's question is the stall in plain words, which the
seat's row gives as its reason, and the seat reads `needs you`; the passes after it neither type
nor ask again.  The hour is the stall's clock as ak keeps it, set back an hour, not waited out.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
pass in the box `home.tick()` builds, before a seat of tests/fixtures/akseat.py showing a real
Claude pane stopped on an API error.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

ASKED = ("acme is stalled on API Error for an hour and typing has not moved it; open the host, "
         "press this session's number, and get it going again.")
HOUR = 3700


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


def row(home, seat):
    """That seat's lines of `ak orch list`: its name, then the lines indented under it."""
    done = home.ak("orch", "list", "--why")
    assert done.code == 0, done.err
    lines, mine = [], False
    for line in done.out.splitlines():
        if not line.startswith(" "):
            mine = line.split()[:1] == [seat]
        if mine:
            lines.append(line)
    return "\n".join(lines)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class StalledAnHour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.seat = Seat(home, "acme", screen="claude-stall-pane.txt")
        cls.passes = [home.tick()]      # the stall, seen for the first time
        watched = state(home, "watch.json") or {}
        stall = (watched.get("stalls") or {}).get("acme")
        assert stall, f"the first pass kept no stall for acme: {cls.passes[0]}"
        assert {"since", "stall_at", "changed_at"} <= set(stall), stall
        # standing an hour, nudged at its third minute, and nothing on the pane since
        now = time.time()
        stall.update(since=now - HOUR, stall_at=now - HOUR, changed_at=now - HOUR,
                     nudged_at=now - HOUR + 200)
        home.write(".agentkit/state/watch.json", watched)
        cls.passes.append(home.tick())
        cls.notice = state(home, "notify-acme.json")
        cls.told = state(home, "watch.json")["stalls"]["acme"].get("told")
        cls.row = row(home, "acme")
        cls.passes.append(home.tick())

    def test_every_pass_succeeds(self):
        for done in self.passes:
            self.assertEqual(done.code, 0, done.err)

    def test_the_hour_old_stall_is_asked_as_the_seat_s_question(self):
        self.assertIsNotNone(self.notice, "no question was kept for acme")
        self.assertEqual({key: self.notice.get(key) for key in ("session", "kind", "text")},
                         {"session": "acme", "kind": "needs", "text": ASKED})
        self.assertIs(self.notice.get("watcher"), True)
        self.assertTrue(str(self.notice.get("source")).startswith("stall:acme:"),
                        self.notice.get("source"))
        self.assertIsInstance(self.told, (int, float))

    def test_the_seat_reads_needs_you_with_the_stall_as_its_reason(self):
        self.assertIn("needs you", self.row)
        self.assertIn(ASKED, self.row)
        self.assertEqual(state(self.home, "card-acme.json")["word"], "needs you")

    def test_nothing_is_typed_and_the_next_pass_asks_nothing_again(self):
        self.assertEqual(self.seat.typed(), "")
        self.assertEqual(state(self.home, "notify-acme.json"), self.notice)
        self.assertEqual(state(self.home, "watch.json")["stalls"]["acme"].get("told"),
                         self.told)


if __name__ == "__main__":
    unittest.main()
