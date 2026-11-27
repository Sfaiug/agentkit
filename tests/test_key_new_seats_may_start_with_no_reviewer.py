"""New seats may start with no reviewer: on `c`'s "For new seats" Space unmarks the last reviewer
and saves `reviewers = []` in [defaults], every other mark changes as with one marked, and the
next seat `n` makes, from [defaults] as config.toml then holds them, has none.  A [defaults]
naming no reviewers makes the seat it always made: its builders review.

A seat's own picker lets its last reviewer go too
(tests/test_key_a_seat_may_leave_no_reviewer_marked.py).  Black-box: the program `AK_BIN` names,
as the menu in a person's terminal (tests/fixtures/akterm.py), its harnesses the fakes of
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
from fixtures.akterm import Terminal

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
class NewSeatsMayStartWithNoReviewer(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")

    def defaults(self):
        return akconfig.read(self.home)["defaults"]

    def made(self, term):
        """The seat `n` makes on Enter on `term`'s menu, named fix-api: its builders and its
        reviewers."""
        term.wait("esc leave")
        term.keys("n")
        term.wait("tab models")
        term.type("fix-api")
        term.keys("Enter")
        made = record(self.home, "fix-api")
        return made["workers"], made["reviewers"]

    def test_the_last_reviewer_unmarks_and_the_next_seat_has_none(self):
        akconfig.write(self.home, MODELS, workers=["astra"], reviewers=["astra"])
        term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "For  new seats" in screen and "␣ mark" in screen)
        term.keys("Down", "Right", "Right", "Right")  # past Astra's build mark and effort
        term.wait(lambda screen: cells(screen, "6 Astra")[4:5] == ["[■]"])
        term.keys("Space")
        term.wait(lambda screen: cells(screen, "6 Astra")[4:] == ["[□]"])
        until(lambda: self.defaults().get("reviewers") == [])
        term.keys("Up", "Left")                       # Opus's build mark, none reviewing
        term.wait(lambda screen: cells(screen, "Opus 5.5")[3:] == ["[□]", "□"])
        term.keys("Space")
        term.wait(lambda screen: cells(screen, "Opus 5.5")[3:4] == ["[■]"])
        until(lambda: self.defaults()["workers"] == ["astra", "opus"])
        self.assertEqual(self.defaults()["reviewers"], [])
        term.keys("Escape")
        self.assertEqual(self.made(term), (["astra", "opus"], []))

    def test_defaults_naming_no_reviewers_make_a_seat_its_builders_review(self):
        akconfig.write(self.home, MODELS, workers=["astra"])
        self.assertNotIn("reviewers", self.defaults())
        term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        self.assertEqual(self.made(term), (["astra"], ["astra"]))


if __name__ == "__main__":
    unittest.main()
