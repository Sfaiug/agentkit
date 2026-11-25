"""`a apply to all sessions` on `c` counts the seats it changes in the header and fills the rule.

The owner (24 Nov 2026): "A job ak can count fills the rule step by step and says "3 of 7"
beside the page name, as an update does."  Once `Apply` is picked, the screen stays as it was
but its first two lines: before each seat is changed the header reads `config · applying 2 of
3`, that seat counted, and the rule is heavy from its left by the share of seats done.  Once the
last is done the page is drawn as before, its header and rule as they were.
Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) at 100
columns without colour, over three seats as ak leaves them (tests/fixtures/akseat.py), none of
which restarts; each one's change is held on its record's lock, which this test takes and lets
go once ak waits on it.  This test fails against `/bin/false`.
"""

from contextlib import ExitStack
import fcntl
import json
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_a_job_keeps_a_run_changed_while_it_adopts_it import waited_on
from test_key_defaults_apply_to_all import CALM, KEYS, MODELS, key_line, lines

SEATS = ("acme-api", "acme-app", "acme-web")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ApplyToAllCountsInTheHeader(unittest.TestCase):
    def test_the_header_counts_each_seat_and_the_rule_fills_by_those_done(self):
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, MODELS, workers=["fable"], reviewers=["astra"])
        for name in SEATS:
            Seat(home, name, model="fable", record=CALM)
        term = Terminal(home, size=(100, 30), env={"NO_COLOR": "1"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("c config")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS)
        term.keys("a")
        term.wait(lambda screen: {"  No session restarts.", "  × Apply"} <= set(lines(screen)))
        state = home.path / ".agentkit/state"
        with ExitStack() as stack:
            held = {}
            for name in SEATS:
                held[name] = stack.enter_context((state / f".session-{name}.lock").open("a"))
                fcntl.flock(held[name], fcntl.LOCK_EX)
            term.keys("Down")
            picked = lines(term.wait(lambda screen: "› × Apply" in lines(screen)))
            term.keys("Enter")
            for done in range(len(SEATS)):
                deadline = time.monotonic() + 30
                while not (waiting := [name for name, lock in held.items()
                                       if waited_on(Path(lock.name))]):
                    self.assertLess(time.monotonic(), deadline, "ak never changed a seat")
                    time.sleep(0.05)
                name, = waiting
                header = f"agentkit · config · applying {done + 1} of 3"
                shown = lines(term.wait(lambda screen: lines(screen)[0].startswith(header)))
                with self.subTest(seat=done + 1):
                    self.assertRegex(shown[0], rf"^{re.escape(header)} +\d\d:\d\d$")
                    heavy = round(100 * done / 3)          # 0, 33, 67
                    self.assertEqual(shown[1], "━" * heavy + "─" * (100 - heavy))
                    self.assertEqual(shown[2:], picked[2:])
                fcntl.flock(held.pop(name), fcntl.LOCK_UN)
        after = lines(term.wait(lambda screen: key_line(screen) == KEYS))
        self.assertRegex(after[0], r"^agentkit · config +\d\d:\d\d$")
        self.assertEqual(after[1], "─" * 100)
        for name in SEATS:
            record = json.loads((state / f"session-{name}.json").read_text())
            self.assertEqual((record["workers"], record["reviewers"]), (["fable"], ["astra"]))


if __name__ == "__main__":
    unittest.main()
