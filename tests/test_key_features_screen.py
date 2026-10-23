"""A project naming a features command in its AGENTS.md has its switches in the menu.

Its heading says how many features are hidden (off for everyone); Enter on the heading opens
`agentkit · <project>`, one row a feature with a mark under `you` and under `everyone` and
nothing else, and Enter flips the mark the keys are on by calling the project's own `set`.  A
person reads production's switches here, and the project's command is the one thing that changes
them: a switch is only ever you or everyone, never a user picked by id.  Black-box: ak runs in a
terminal of its own beside a seat filed under ~/code/ACME, and the features command is a script
of the test's that answers from a JSON file and logs every call.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

ROWS = [{"id": "dark", "name": "Dark mode", "you": False, "everyone": False},
        {"id": "beta", "name": "Beta search", "you": True, "everyone": False},
        {"id": "fixed", "name": "Locked", "you_switchable": False, "everyone": False}]
# `list` prints every row; `set <id> you|everyone on|off` the row as it now stands.
FAKE = """#!{python}
import json, sys
from pathlib import Path
here = Path(__file__).parent
with open(here / "calls.log", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
rows = json.loads((here / "features.json").read_text())
if sys.argv[1] == "list":
    print(json.dumps(rows))
else:
    feature, who, value = sys.argv[2:]
    row = next(row for row in rows if row["id"] == feature)
    row[who] = value == "on"
    (here / "features.json").write_text(json.dumps(rows))
    print(json.dumps(row))
"""
SWITCHES = ["               you  everyone",
            "› Dark mode     ○      ○",
            "  Beta search   ●      ○",
            "  Locked        —      ○",
            "",
            "  ↑↓←→ move   ⏎ flip   esc back"]


def row(screen, name):
    return next((line for line in screen.split("\n") if name in line), "")


def steady(term, shown):
    """The screen once it shows that text, or that test of it holds, alike in two captures
    running: a frame is written a line at a time, and a capture can land inside one."""
    test = shown if callable(shown) else (lambda screen: shown in screen)
    last = None

    def settled(screen):
        nonlocal last
        same, last = screen == last, screen
        return same and test(screen)
    return term.wait(settled)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FeaturesScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        acme = home.path / "code" / "ACME"
        acme.mkdir(parents=True)
        assert home.run("git", "init", "-q", str(acme)).code == 0
        fake = home.write("acme-features/features.py", FAKE.format(python=sys.executable))
        fake.chmod(0o755)
        home.write("code/ACME/AGENTS.md", f"---\nfeatures: {fake}\n---\n\n# ACME\n")
        Seat(home, "acme-fix", cwd=acme, record={"repo": str(acme)})

    def setUp(self):
        self.home.write("acme-features/features.json", ROWS)
        self.home.path.joinpath("acme-features", "calls.log").unlink(missing_ok=True)

    def calls(self):
        log = self.home.path / "acme-features" / "calls.log"
        return [json.loads(line) for line in log.read_text().splitlines()]

    def menu(self, **env):
        """The menu once the project's heading counts its features."""
        term = Terminal(self.home, size=(100, 30), env=env)
        self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
        steady(term, "hidden features")
        return term

    def switches(self, **env):
        """The project's switches, opened from its heading."""
        term = self.menu(**env)
        term.keys("k")
        steady(term, "› ACME")
        term.keys("Enter")
        # the header writes itself out as the screen opens
        return term, steady(term, lambda screen: screen.startswith("agentkit · ACME ")
                            and "esc back" in screen)

    def leave(self, term, heading):
        """Esc back to the menu, its heading counting again, and Esc out of it."""
        term.keys("Escape")
        steady(term, lambda screen: "esc leave" in screen
               and row(screen, "ACME").endswith(heading))
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)

    def test_the_heading_counts_the_features_hidden_from_everyone_at_its_right(self):
        term = self.menu()
        screen = steady(term, "› 1  acme-fix")    # a seat is highlighted before its heading
        heading = row(screen, "ACME")
        self.assertRegex(heading, r"^ACME {2,}3 hidden features$")
        term.keys("k")
        screen = steady(term, "› ACME")
        self.assertEqual(row(screen, "ACME"), "› " + heading)
        self.assertEqual(row(screen, "acme-fix"), "  1  acme-fix  Opus 5.5  ○ idle")
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)

    def test_enter_on_the_heading_opens_its_switches_under_you_and_everyone(self):
        term, screen = self.switches()
        lines = screen.split("\n")
        self.assertTrue(lines[0].startswith("agentkit · ACME"), lines[0])
        self.assertEqual(lines[1], "─" * 100)
        self.assertEqual(lines[2:8], SWITCHES)
        self.assertEqual("".join(lines[8:]), "")
        calls = self.calls()
        self.assertEqual(calls, [["list"]] * len(calls))
        self.leave(term, "3 hidden features")

    def test_enter_flips_the_mark_by_calling_the_projects_set(self):
        term, _ = self.switches()
        term.keys("Enter")
        steady(term, lambda screen: row(screen, "Dark mode") == "› Dark mode     ●      ○")
        calls = self.calls()
        self.assertEqual(calls[0], ["list"])
        self.assertEqual([call for call in calls if call != ["list"]],
                         [["set", "dark", "you", "on"]])
        self.leave(term, "3 hidden features")      # on for you is still hidden from everyone

    def test_the_only_switches_are_you_and_everyone(self):
        term, screen = self.switches()
        self.assertEqual(screen.split("\n")[2].split(), ["you", "everyone"])
        term.keys("Right", "Right", "Enter")    # there is no third column to go on to
        steady(term, lambda screen: row(screen, "Dark mode") == "› Dark mode     ●      ●")
        self.assertEqual([call for call in self.calls() if call != ["list"]],
                         [["set", "dark", "everyone", "on"]])
        self.leave(term, "2 hidden features")

    def test_without_colour_the_keys_mark_is_bracketed(self):
        term, screen = self.switches(NO_COLOR="1")
        self.assertEqual(row(screen, "Dark mode"), "› Dark mode    [○]     ○")
        term.keys("Right", "Right", "Down")
        screen = steady(term, "› Beta search")
        self.assertEqual(row(screen, "Beta search"), "› Beta search   ●     [○]")
        self.assertEqual(row(screen, "Dark mode"), "  Dark mode     ○      ○")
        self.leave(term, "3 hidden features")


if __name__ == "__main__":
    unittest.main()
