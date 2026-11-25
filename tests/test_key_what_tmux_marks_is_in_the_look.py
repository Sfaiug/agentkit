"""What tmux itself marks in a seat is in ak's look (the owner, 10 Nov 2026: "Only ever use these
colors to color everythign inside ak."): copy mode's selection, a search's matches and its mark,
the menu's pick, the pane borders, the clock and the pane numbers are ak's tmux server's defaults
in the look's colours, in the theme kept as a seat is started, so a window made by hand takes
them too.  Black-box: the program `AK_BIN` names starts the seats through tests/fixtures/akbin.py
on a real tmux, judged by the server's options as tmux reads them, each this tmux has.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home

# The roles tmux's marks take, dark and light (agentkit/themes.py).
SHADES = {"text": ("e2e8ef", "181c22"), "selection": ("08305d", "dcecff"),
          "accent": ("4da3ff", "0067c6"), "on-accent": ("000000", "ffffff"),
          "warning": ("d79200", "8e5e00"), "border": ("3a3f46", "b1b8c0")}
MARKS = {"mode-style": "fg=#{text},bg=#{selection}",
         "copy-mode-match-style": "bg=#{selection}", "menu-selected-style": "bg=#{selection}",
         "copy-mode-current-match-style": "fg=#{on-accent},bg=#{accent}",
         "copy-mode-mark-style": "fg=#{on-accent},bg=#{warning}",
         "pane-active-border-style": "fg=#{accent}", "clock-mode-colour": "#{accent}",
         "display-panes-active-colour": "#{accent}",
         "pane-border-style": "fg=#{border}", "display-panes-colour": "#{border}"}
DARK, LIGHT = ({option: form.format_map({role: shades[at] for role, shades in SHADES.items()})
                for option, form in MARKS.items()} for at in (0, 1))
BY_HAND = ("copy-mode-match-style", "pane-active-border-style")


def open_seat(home, name):
    cwd = home.path / "code" / name
    cwd.mkdir(parents=True, exist_ok=True)
    done = home.ak("orch", name, "--model", "opus", "--workers", "opus", tty=True, cwd=cwd)
    assert done.code == 0, done.err


def ask(home, *args):
    done = home.tmux(*args)
    assert done.code == 0, done.err
    return done.out.strip()


def has(home):
    """The options of MARKS this tmux has: one before 3.2 lacks copy mode's, one before 3.4 the
    menu's, and asked with `-q` it shows nothing for an option it lacks."""
    return [option for option in MARKS if ask(home, "show-options", "-gq", option)]


def defaults(home, options):
    return {option: ask(home, "show-options", "-gv", option) for option in options}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhatTmuxMarksIsInTheLook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        open_seat(home, "acme")
        cls.options = has(home)
        cls.dark = defaults(home, cls.options)
        window = ask(home, "new-window", "-d", "-P", "-F", "#{window_id}", "-t", "=acme:",
                     "sleep 600")
        cls.by_hand = {option: ask(home, "show-options", "-wAv", "-t", window, option)
                       for option in BY_HAND if option in cls.options}
        home.write(".agentkit/state/background", "light\n")
        open_seat(home, "beta")
        cls.light = defaults(home, cls.options)

    def shades(self, theme, options):
        return {option: theme[option] for option in options if option in self.options}

    def test_the_servers_defaults_are_the_dark_shades(self):
        self.assertEqual(self.dark, self.shades(DARK, MARKS))

    def test_a_window_made_by_hand_takes_them(self):
        self.assertEqual(self.by_hand, self.shades(DARK, BY_HAND))

    def test_a_seat_started_after_a_light_answer_makes_them_the_light_shades(self):
        self.assertEqual(self.light, self.shades(LIGHT, MARKS))


if __name__ == "__main__":
    unittest.main()
