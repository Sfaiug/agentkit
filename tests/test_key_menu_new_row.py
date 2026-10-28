"""`n` on the menu makes the new seat's row in place, and its name is typed into that row.

A person starts a seat from the menu by pressing `n`: a row numbered as the seat will be appears
last, under a `not assigned yet` heading of its own, with a caret, a hinted name, the default
orchestrator and `new`, and the crew it will start with on the line under it.  What is typed
there becomes the name, lower-case with a dash for a space; Backspace takes a character back and
Esc drops the row.  A name a seat or tmux already has is called out on that line, and Enter then
starts nothing, since a second seat of one name would write over the first's record.
Black-box: the program `AK_BIN` names runs in a terminal from outside
(tests/fixtures/akterm.py) beside seats as ak's launch leaves them (tests/fixtures/akseat.py).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
ROW_KEYS = "  ⏎ start   tab models   esc back"
UNFILED = "not assigned yet"
CREW = "     Fable 5.1 ⚒◎   GPT-6-Astra ⚒◎"
SHIPPED = 'orchestrator = "opus"\nworkers = ["opus", "astra"]'
DEFAULTS = 'orchestrator = "fable"\nworkers = ["fable", "astra"]'


def shown(line):
    """A test of the screen: that line is on it, whole."""
    return lambda screen: line in screen.splitlines()


def highlighted(screen):
    """The highlighted row and the line under it."""
    rows = screen.splitlines()
    at = next(n for n, row in enumerate(rows) if row.startswith("›"))
    return rows[at], rows[at + 1]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NewRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        config = home.path / ".agentkit" / "config.toml"
        text = config.read_text()
        assert text.count(SHIPPED) == 1, "the shipped config's [defaults] changed"
        config.write_text(text.replace(SHIPPED, DEFAULTS))
        acme = home.path / "code" / "acme"
        acme.mkdir(parents=True)
        done = home.run("git", "init", "-q", str(acme))
        assert done.code == 0, done.err
        # both filed under acme, so `not assigned yet` is the new row's heading alone
        for name in ("atoll-ask", "atoll-fix"):
            Seat(home, name, cwd=acme, record={"repo": str(acme)})
        # a session of ak's tmux that is no seat: `new-session` would refuse its name too
        done = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "acme-watch",
                         "sleep 86400")
        assert done.code == 0, done.err

    def menu(self):
        """The menu on a 100x30 terminal, once it lists the seats; Esc leaves it at the end."""
        menu = Terminal(self.home, size=(100, 30))
        self.addCleanup(self.leave, menu)
        menu.wait(lambda screen: MAIN_KEYS in screen.splitlines() and "atoll-fix" in screen)
        return menu

    def leave(self, menu):
        if ROW_KEYS in menu.screen().splitlines():
            menu.keys("Escape")
            menu.wait(shown(MAIN_KEYS))
        menu.keys("Escape")
        menu.exit_code()

    def new_row(self, menu):
        menu.keys("n")
        return menu.wait(shown(ROW_KEYS))

    def test_n_adds_a_row_last_under_a_heading_of_its_own_with_the_default_crew(self):
        menu = self.menu()
        self.assertNotIn(UNFILED, menu.screen().splitlines())
        screen = self.new_row(menu)
        row, under = highlighted(screen)
        self.assertRegex(row, r"^› 3  ▏[a-z-]+ +Fable 5.1  new$")
        self.assertEqual(under, CREW)
        rows = screen.splitlines()
        headings = [line for line in rows[:rows.index(row)] if line[:1].isalpha()]
        self.assertEqual(headings[-2:], ["acme", UNFILED])

    def test_typing_builds_a_lower_case_dashed_name_and_esc_drops_the_row(self):
        menu = self.menu()
        self.new_row(menu)
        menu.type("My Seat!")            # `!` can be no part of a name
        screen = menu.wait(lambda screen: "my-seat▏" in screen)
        self.assertRegex(highlighted(screen)[0], r"^› 3  my-seat▏ +Fable 5.1  new$")
        menu.keys("BSpace")
        screen = menu.wait(lambda screen: "my-sea▏" in screen)
        self.assertRegex(highlighted(screen)[0], r"^› 3  my-sea▏ +Fable 5.1  new$")
        menu.keys("Escape")
        rows = menu.wait(shown(MAIN_KEYS)).splitlines()
        self.assertNotIn(UNFILED, rows)
        self.assertNotIn(ROW_KEYS, rows)
        self.assertFalse([row for row in rows if "▏" in row or "my-sea" in row], rows)

    def test_a_name_in_use_is_called_out_and_enter_starts_nothing(self):
        state = self.home.path / ".agentkit" / "state"
        records = sorted(path.name for path in state.glob("session-*.json"))
        menu = self.menu()
        self.new_row(menu)
        for name in ("atoll-fix", "acme-watch"):
            with self.subTest(name):
                menu.type(name)
                refusal = f"     a seat is called {name} already"
                row, under = highlighted(menu.wait(shown(refusal)))
                self.assertRegex(row, rf"^› 3  {name}▏ +Fable 5.1  new$")
                self.assertEqual(under, refusal)
                menu.keys("Enter")
                # keys are read in turn: one taken back on the row is read after the Enter
                menu.keys("BSpace")
                screen = menu.wait(lambda screen: f"{name[:-1]}▏" in screen)
                self.assertEqual(highlighted(screen)[1], CREW)
                self.assertIn(ROW_KEYS, screen.splitlines())
                sessions = self.home.tmux("list-sessions", "-F", "#{session_name}").out
                self.assertEqual(sorted(sessions.split()), ["acme-watch", "atoll-ask",
                                                            "atoll-fix"])
                self.assertEqual(sorted(path.name for path in state.glob("session-*.json")),
                                 records)
                menu.keys(*["BSpace"] * (len(name) - 1))
                menu.wait(lambda screen: highlighted(screen)[0].startswith("› 3  ▏"))


if __name__ == "__main__":
    unittest.main()
