"""A seat that marks no builder shows none marked on its `c`, its orchestrator's build mark open.

Its orchestrator then builds every change itself, yet drawn filled that mark read exactly as an
orchestrator marked to launch tasks to itself; the owner, 25 Nov 2026: "Make it so when no builder
is selected that nothing is then selected its fine."  So the builds column shows every mark open
and no effort beside one, and Space on the orchestrator's open build mark marks it as on any
other row, Space again leaving the column empty.  Black-box: the program `AK_BIN` names, as the
popup over a seat of tests/fixtures/akseat.py (tests/fixtures/akterm.py), its harnesses the fakes
of tests/fixtures/fakeadapter.py; fails against `/bin/false`.  The terminal has no colour
(NO_COLOR).
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


def cells(screen, name):
    """What `name`'s row draws after its label, mark by mark and effort by effort."""
    line = next((line for line in screen.split("\n") if line.lstrip("› ").startswith(name)), "")
    return line.lstrip("› ")[len(name):].split()


def until(test):
    deadline = time.monotonic() + 30
    while not test():
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatWithNoBuilderShowsNoneMarked(unittest.TestCase):
    def test_its_orchestrators_build_mark_is_open_and_two_spaces_mark_and_unmark_it(self):
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, {"opus": {"effort": "high"},
                              "astra": {"harness": "codex", "effort": "high"}})
        Seat(home, SEAT, model="opus", record={"workers": [], "reviewers": ["astra"]})
        record = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        # the orchestrator's effort, then its build mark and review mark open, nothing beside them
        term.wait(lambda screen: "␣ mark" in screen and cells(screen, "Opus 5.5") == [
            "[●]", "━━━──", "high", "□", "□"] and cells(screen, "6 Astra") == [
            "○", "□", "■", "━━━───", "high"])
        term.keys("Right", "Right", "Space")          # Space on Opus 5.5's build mark
        term.wait(lambda screen: cells(screen, "Opus 5.5") == [
            "●", "━━━──", "high", "[■]", "━━━──", "high", "□"])
        until(lambda: json.loads(record.read_text())["workers"] == ["opus"])
        term.keys("Space")
        term.wait(lambda screen: cells(screen, "Opus 5.5") == ["●", "━━━──", "high", "[□]", "□"])
        until(lambda: json.loads(record.read_text())["workers"] == [])


if __name__ == "__main__":
    unittest.main()
