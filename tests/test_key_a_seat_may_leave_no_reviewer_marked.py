"""A seat's last reviewer unmarks on its `c`, and a new seat's on `n`'s models screen, so a seat
with no builder and no reviewer, its orchestrator's alone, is picked there, and [defaults]
remember it so for the next new seat.

A seat with no reviewer lands on its checks
(tests/test_key_a_seat_with_no_reviewer_lands_on_its_checks.py), and new seats' own marks may
leave none (tests/test_key_new_seats_may_start_with_no_reviewer.py).  Black-box: the program
`AK_BIN` names, as the popup over a seat of tests/fixtures/akseat.py and as the menu in a
person's terminal (tests/fixtures/akterm.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py, judged by the terminal, the seats' records and config.toml; fails
against `/bin/false`.  The terminal has no colour (NO_COLOR).
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
MODELS = {"opus": {"effort": "high"}, "astra": {"harness": "codex", "effort": "high"}}


def cells(screen, name):
    """What `name`'s row draws after its label, mark by mark and effort by effort."""
    line = next((line for line in screen.split("\n") if line.lstrip("› ").startswith(name)), "")
    return line.lstrip("› ")[len(name):].split()


def record(home, name):
    """Seat `name`'s record, once it is written."""
    path = home.path / ".agentkit" / "state" / f"session-{name}.json"
    deadline = time.monotonic() + 30
    while not path.exists():
        assert time.monotonic() < deadline, f"{name} never had a record"
        time.sleep(0.05)
    return json.loads(path.read_text())


def until(test):
    deadline = time.monotonic() + 30
    while not test():
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatMayLeaveNoReviewerMarked(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")

    def test_a_seat_with_no_builder_unmarks_its_last_reviewer(self):
        akconfig.write(self.home, MODELS)
        Seat(self.home, SEAT, model="opus", record={"workers": [], "reviewers": ["astra"]})
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "␣ mark" in screen and cells(screen, "6 Astra")[:3] == [
            "○", "□", "■"])
        term.keys("Down", "Right", "Right")          # Astra's review mark
        term.wait(lambda screen: cells(screen, "6 Astra")[:3] == ["○", "□", "[■]"])
        term.keys("Space")
        term.wait(lambda screen: cells(screen, "6 Astra") == ["○", "□", "[□]"])
        until(lambda: record(self.home, SEAT)["reviewers"] == [])
        self.assertEqual(record(self.home, SEAT)["workers"], [])
        self.assertNotIn("at least one model reviews", term.screen())

    def test_a_new_seat_is_made_with_no_builder_and_no_reviewer(self):
        # Astra builds and so reviews, [defaults] naming no reviewer of its own
        akconfig.write(self.home, MODELS, workers=["astra"])
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        term.wait("esc leave")
        term.keys("n")
        term.wait("tab models")
        term.type("fix-api")
        term.keys("Tab")
        term.wait(lambda screen: "␣ mark" in screen and cells(screen, "6 Astra")[:1] == ["○"])
        term.keys("Down", "Right", "Space")          # Astra's build mark off
        term.wait(lambda screen: cells(screen, "6 Astra")[:2] == ["○", "[□]"])
        term.keys("Right", "Space")                  # and its review mark, the last
        term.wait(lambda screen: cells(screen, "6 Astra") == ["○", "□", "[□]"])
        term.keys("Enter")
        made = record(self.home, "fix-api")
        self.assertEqual((made["orchestrator"], made["workers"], made["reviewers"]),
                         ("opus", [], []))
        until(lambda: akconfig.read(self.home)["defaults"]["workers"] == [])
        self.assertEqual(akconfig.read(self.home)["defaults"]["reviewers"], [])


if __name__ == "__main__":
    unittest.main()
