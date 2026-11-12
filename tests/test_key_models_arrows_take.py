"""← and → on `r recommended` on `c` move the role `▸` is on to its next cheaper or next better
choice at once, passing a choice no configured model runs, and past either end change nothing,
the owner's design of 5 Nov 2026.  Over a seat its executor becomes that model at the choice's
effort in its record; its orchestrator asks first, as the move restarts it, `Keep` leaving the
record as it was and `Restart` moving it, on a terminal too short for every line the role lines
paged around the question, under the header and over the key line.  On `· new seats`
[defaults] takes the orchestrator at once.  The key line says `← cheaper` and `better →`, `r`
takes nothing, and a save that fails changes nothing and says why.

Black-box: the program `AK_BIN` names in a terminal of 100 cells and of 40, and one 40 by 16
(tests/fixtures/akterm.py), over a seat (tests/fixtures/akseat.py) or in a window of its own,
its harness a fake running three of four invented choices, the boards held as just asked
(tests/test_key_role_choices.py); judged by the screen, the seats' records, config.toml and
the launches the harness is asked for.  Fails against /bin/false.
"""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_role_choices import hold

SEAT, MOVED = "acme-fix", "acme-move"
WIDTHS = (100, 40)
# Release, name, effort, every measure's share and cost a task: four choices a point or more
# apart, cheapest first; no harness runs Gap
ROWS = [("acme-base-1", "Acme Base 1", "high", 0.82, 2),
        ("acme-gap-1", "Acme Gap 1", "high", 0.84, 3),
        ("acme-step-1", "Acme Step 1", "medium", 0.86, 4),
        ("acme-top-1", "Acme Top 1", "high", 0.90, 8)]
MODELS = {name: {"harness": "claude", "model": f"acme-{name}-1"}
          for name in ("base", "step", "top")}
CREW = {"orchestrator": "base", "workers": ["base"], "reviewers": ["top"]}
# what moving seat `name` onto Step asks, whatever name the harness gives Step
ASK = re.compile(r"Restart (\S+) on .+? at medium\?")


def asked(screen, name):
    """Whether the screen asks to move seat `name` onto Step at `medium`."""
    return name in ASK.findall(said(screen))


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def said(screen):
    """The screen's words on one line, as a question wraps them on 40 cells."""
    return " ".join(screen.split())


def key_line(screen):
    """The key line's words, on as many lines as it wraps onto: those after the last blank."""
    shown = lines(screen.rstrip())
    return said("\n".join(shown[len(shown) - shown[::-1].index(""):]))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ArrowsTake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.fake = fakeadapter.install(home, claude="pass")["claude"]
        cls.fake.answer("models", "acme-base-1\tAcme Base 1\thigh\n"
                                  "acme-step-1\tAcme Step 1\tmedium high\n"
                                  "acme-top-1\tAcme Top 1\thigh\n")
        cls.config = home.path / ".agentkit/config.toml"
        cls.seats = {name: Seat(home, name, model="base", record=CREW) for name in (SEAT, MOVED)}

    def fresh(self):
        """The config, the boards and the seats' records as each test starts from them."""
        akconfig.write(self.home, MODELS, **CREW)
        hold(self.home, ROWS)
        for name, seat in self.seats.items():
            self.home.write(f".agentkit/state/session-{name}.json", seat.record)
        self.given = self.config.read_bytes()

    def models(self, width, seat=None, height=60):
        """`r` on `c`, `width` cells wide and `height` high, over `seat` or in a window of its
        own, once the orchestrator's choices are drawn."""
        term = Terminal(self.home, *(("attach", "--overlay") if seat else ()), size=(width, height),
                        env={**ENV, **({"AGENTKIT_SESSION": seat} if seat else {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("orchestrator · four choices")
        return term

    def path(self, name):
        return self.home.path / f".agentkit/state/session-{name}.json"

    def record(self, name):
        return json.loads(self.path(name).read_text())

    def launches(self):
        return self.fake.calls("interactive")

    def ended(self, name):
        """Seat `name`'s harness ended, so a move restarts it (its harness took one in place)."""
        pane = self.seats[name].pane
        self.home.tmux("respawn-pane", "-k", "-t", pane, "true")
        self.until(lambda: self.home.tmux("display-message", "-p", "-t", pane,
                                          "#{pane_dead}").out.strip() == "1", "it never ended")

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_right_and_left_take_a_seats_executor_to_its_next_better_and_cheaper_choice(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                self.fresh()
                term = self.models(width, SEAT)
                term.keys("Down", "Right")      # past Gap, which no harness runs
                self.until(lambda: self.record(SEAT)["workers"] == ["step"], "→ took nothing")
                record = self.record(SEAT)
                self.assertEqual(record["efforts"]["step"],
                                 {"effort": "high", "exec_effort": "medium"})
                self.assertEqual((record["orchestrator"], record["reviewers"]), ("base", ["top"]))
                term.keys("Left")
                self.until(lambda: self.record(SEAT)["workers"] == ["base"], "← took nothing")
                # at its entry's effort, the executor follows it again
                self.assertEqual(self.record(SEAT)["efforts"]["base"], {"effort": "high"})
                taken = self.path(SEAT).read_bytes()
                term.keys("Left", "Enter")      # the cheapest: nothing further, then its why
                term.wait("why Acme Base 1 high builds")
                self.assertEqual(self.path(SEAT).read_bytes(), taken)
                self.assertEqual(self.config.read_bytes(), self.given)

    def test_a_seats_orchestrator_asks_first_and_keep_leaves_its_record(self):
        for width, height in [*((width, 60) for width in WIDTHS), (40, 16)]:   # 16: too short
            with self.subTest(width=width, height=height):
                self.fresh()
                self.ended(SEAT)
                term = self.models(width, SEAT, height)
                before, launched = self.path(SEAT).read_bytes(), self.launches()
                term.keys("Right")
                shown = term.wait(lambda screen: asked(screen, SEAT)
                                  and "› ✓ Keep" in lines(screen)
                                  and "  × Restart" in lines(screen))
                self.assertTrue(shown.startswith("agentkit"), shown)
                self.assertIn("esc back", key_line(shown))
                self.assertIn("▸ orchestrator", shown)
                self.assertEqual(self.path(SEAT).read_bytes(), before)
                term.keys("Enter")              # Keep, the answer highlighted
                term.wait(lambda screen: "orchestrator · four choices" in screen
                          and not asked(screen, SEAT))
                time.sleep(1)       # a restart, were one under way, would have begun
                self.assertEqual((self.path(SEAT).read_bytes(), self.launches()),
                                 (before, launched))

    def test_restart_moves_a_seat_onto_the_choice_at_its_effort(self):
        self.fresh()
        self.ended(MOVED)
        term = self.models(100, MOVED)
        term.keys("Right")
        term.wait(lambda screen: asked(screen, MOVED))
        term.keys("Down", "Enter")
        self.until(lambda: self.launches(), "the seat's harness was never launched")
        self.assertEqual(self.launches()[-1]["argv"][:2], ["acme-step-1", "medium"])
        self.until(lambda: self.record(MOVED)["orchestrator"] == "step", "the record never moved")
        self.assertEqual(self.record(MOVED)["efforts"]["step"]["effort"], "medium")

    def test_on_new_seats_defaults_take_the_orchestrator_at_once(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                self.fresh()
                term = self.models(width)
                term.keys("Right")
                self.until(lambda: akconfig.read(self.home)["defaults"]["orchestrator"] == "step",
                           "→ took nothing")
                saved = akconfig.read(self.home)
                self.assertEqual(saved["defaults"], {**CREW, "orchestrator": "step"})
                self.assertEqual(saved["models"]["step"]["effort"], "medium")
                self.assertEqual([self.record(name)["orchestrator"] for name in self.seats],
                                 ["base", "base"], "an open seat moved")
                term.wait("Acme Step 1 medium")         # what the orchestrator uses now

    def test_the_key_line_says_cheaper_and_better_and_r_takes_nothing(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                self.fresh()
                term = self.models(width)
                shown = key_line(term.screen())
                self.assertIn("← cheaper", shown)
                self.assertIn("better →", shown)
                term.keys("r", "Enter")
                term.wait("why Acme Base 1 high orchestrates")
                self.assertEqual(self.config.read_bytes(), self.given)

    def test_a_config_that_cannot_be_saved_changes_nothing_and_says_why(self):
        self.fresh()
        # the save's temporary file cannot be written: a directory stands in its place
        blocked = self.home.path / ".agentkit/config.tmp"
        blocked.mkdir()
        self.addCleanup(blocked.rmdir)
        term = self.models(100)
        term.keys("Right")
        term.wait("Is a directory")
        self.assertEqual(self.config.read_bytes(), self.given)

    def test_efforts_that_cannot_be_saved_change_no_mark(self):
        self.fresh()
        term = self.models(100, SEAT)
        before = self.path(SEAT).read_bytes()
        blocked = self.home.path / f".agentkit/state/session-{SEAT}.tmp"
        blocked.mkdir()
        self.addCleanup(blocked.rmdir)
        term.keys("Down", "Right")
        term.wait("Is a directory")
        self.assertEqual(self.path(SEAT).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
