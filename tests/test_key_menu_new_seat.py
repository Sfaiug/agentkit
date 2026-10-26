"""`n` on the ak menu opens a new seat's row: Enter starts the seat and opens it, Tab picks its
models first, and a seat opened from a pipe without `--model` is asked who orchestrates.

A person starts most seats from this row, and the owner's rule is that a new seat keeps the
orchestrator question so they can switch models freely: the row makes the seat with the last
creation's models and hands its harness the conversation it records, the picker shows each
marked model under its harness with its roles and effort, and a pipe is asked a line at a time.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
menu on a terminal of tests/fixtures/akterm.py, its harnesses tests/fixtures/fakeadapter.py's
and tests/fixtures/adapters/echo.sh, and this test fails against `/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

ROW_KEYS = "  ⏎ start   tab models   esc back"
PICKER_KEYS = "  ↑↓←→ move   ⏎ choose   esc back"
# The born row before a key: the pointer, its number, the caret, the name Enter alone gives it.
BORN = re.compile(r"› 2  ▏[a-z0-9-]+ +Fable 5.1  new")


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def under(screen, heading):
    """The line below `heading` on the screen."""
    shown = rows(screen)
    return shown[shown.index(heading) + 1]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NewRow(unittest.TestCase):
    """One seat, acme, is up; the defaults are fable orchestrating, fable and astra building and
    reviewing.  Each case starts its own: a seat one makes would be on the next one's menu."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        config = akconfig.write(self.home, {"fable": {}, "astra": {"effort": "high"}})
        # akconfig writes no reviewers into [defaults]
        config.write_text(config.read_text().replace(
            "[defaults]\n", '[defaults]\nreviewers = ["fable", "astra"]\n'))
        Seat(self.home, "acme", model="fable")
        self.menu = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.menu.wait("acme")
        self.menu.keys("n")
        self.menu.wait(ROW_KEYS)

    def opened(self, name):
        """The seat's record once its session is up on ak's server with this terminal in it."""
        deadline = time.monotonic() + 30
        while True:
            listed = self.home.tmux("list-sessions", "-F", "#{session_name} #{session_attached}")
            if f"{name} 1" in listed.out.splitlines():
                break
            if time.monotonic() > deadline:
                raise AssertionError(f"{name} never opened; tmux holds {listed.out!r} and the "
                                     f"terminal shows:\n{self.menu.screen()}")
            time.sleep(0.05)
        return json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())

    def back_on_the_menu(self, name, row):
        """The menu's lines once the person has left the seat, by detaching, and it lists the
        seat as `row`, after the pointer's column."""
        self.assertEqual(self.home.tmux("detach-client", "-s", f"={name}").code, 0)
        return rows(self.menu.wait(lambda shown: any(line[2:] == row
                                                     for line in rows(shown))))

    def test_enter_on_a_typed_name_starts_the_seat_opens_it_and_lists_it(self):
        self.menu.type("fix-api")
        self.menu.keys("Enter")
        record = self.opened("fix-api")
        self.assertEqual(record["orchestrator"], "fable")
        self.assertEqual(record["workers"], ["fable", "astra"])
        self.assertEqual(record["reviewers"], ["fable", "astra"])
        self.assertEqual(record["id_source"], "launcher")
        self.assertEqual(record["session_title"], "fix-api")
        self.assertTrue(record["conversation"])
        # the harness is told the conversation the record keeps, so a reopen resumes this one
        launched = self.fakes["claude"].calls("interactive")[-1]
        self.assertEqual(launched["argv"],
                         ["claude-fable-5-1", "xhigh", record["conversation"], "new"])
        shown = self.back_on_the_menu("fix-api", "2  fix-api  Fable 5.1  ○ idle")
        self.assertLess(shown.index("not assigned yet"),
                        next(at for at, line in enumerate(shown) if "  fix-api  " in line))

    def test_tab_opens_the_model_picker_and_esc_comes_back_to_the_row(self):
        self.menu.keys("Tab")
        screen = self.menu.wait(PICKER_KEYS)
        self.assertTrue(rows(screen)[0].startswith("agentkit · new session"), screen)
        self.assertIn("               orch  builds  reviews", rows(screen))
        self.assertEqual(under(screen, "Claude Code"),
                         "› Fable 5.1    [●]     ■        ■     xhigh")
        self.assertEqual(under(screen, "Codex"),
                         "  GPT-6-Astra   ○      ■        ■     high")
        self.menu.keys("Escape")
        screen = self.menu.wait(ROW_KEYS)
        self.assertTrue(any(BORN.fullmatch(line) for line in rows(screen)), screen)
        records = (self.home.path / ".agentkit/state").glob("session-*.json")
        self.assertEqual([path.name for path in records], ["session-acme.json"])

    def test_enter_in_the_picker_marks_and_esc_brings_the_picks_to_the_row(self):
        self.menu.type("fix-api")
        self.menu.keys("Tab")
        self.menu.wait(PICKER_KEYS)
        self.menu.keys("Right", "Down", "Enter")    # astra no longer builds
        screen = self.menu.wait("[□]")
        self.assertEqual(under(screen, "Codex"),
                         "› GPT-6-Astra   ○     [□]       ■     high")
        self.menu.keys("Escape")
        screen = self.menu.wait(ROW_KEYS)
        # the row's line names the picks: astra only reviews
        self.assertEqual(under(screen, "› 2  fix-api▏  Fable 5.1  new"),
                         "     Fable 5.1 ⚒◎   GPT-6-Astra ◎")
        self.menu.keys("Enter")
        record = self.opened("fix-api")
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("fable", ["fable"], ["fable", "astra"]))
        # what the next new seat starts from
        self.assertEqual(akconfig.read(self.home)["defaults"]["workers"], ["fable"])
        self.back_on_the_menu("fix-api", "2  fix-api  Fable 5.1  ○ idle")


class OrchestratorQuestion(unittest.TestCase):
    """Two models, beta and delta, on the echo fixture's harness; beta orchestrates by
    default.  A dry run writes no seat, so the cases share a Home."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.env["AGENTKIT_ADAPTER_DIR"] = str(REPO / "tests/fixtures/adapters")
        akconfig.write(cls.home, {"beta": {"harness": "echo", "provider": "acme"},
                                  "delta": {"harness": "echo", "provider": "acme"}})

    def asked(self, answers):
        done = self.home.ak("orch", "fix-api", "--dry-run", input=answers)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("  1 beta · 2 delta", done.out)
        self.assertIn("Orchestrator [beta]:", done.out)
        return [line for line in done.out.splitlines() if line.startswith("orch: ")]

    def test_a_number_or_a_name_picks_the_orchestrator(self):
        for answer in ("2", "delta"):
            with self.subTest(answer=answer):
                self.assertEqual(self.asked(f"{answer}\n\n"), ["orch: delta (selected)"])

    def test_enter_keeps_the_default_orchestrator(self):
        picked = self.asked("\n\n")
        self.assertEqual(len(picked), 1, picked)
        self.assertTrue(picked[0].startswith("orch: beta ("), picked)
        self.assertNotEqual(picked[0], "orch: beta (selected)")


if __name__ == "__main__":
    unittest.main()
