"""A terminal whose entry says it takes true colour gets it, said elsewhere or not.

Over ssh a terminal's name (TERM) arrives and COLORTERM does not, so the menu in the whole window
drew the nearest of 256 colours while the one over a seat, told by tmux that its client takes
true colour, drew the look's own: one terminal, two looks.  tmux reads that from the terminal's
entry (`Tc`, `RGB`, or `setrgbf` with `setrgbb`), and so does the menu.  And the menu over a seat
(Ctrl-b m), whose tmux ak tells that every client takes true colour, draws what its client's
terminal says of itself, as the one in the whole window does: its entry, its NO_COLOR, and its
background, which `ak orch` asks as it opens the seat on it.  Black-box, through
tests/fixtures/akterm.py; the entries are compiled here, as no host need have one.
"""

import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ink, look, settled
from fixtures.akterm import SERVER, Terminal

ENTRIES = {"acme-tc": "Tc,", "acme-rgb": "RGB,", "acme-256": "",
           "acme-set": "setrgbf=\\E[38;2;%p1%d;%p2%d;%p3%dm, setrgbb=\\E[48;2;%p1%d;%p2%d;%p3%dm,"}
# A terminal a seat is opened on: what its environment says, whether it is light, and how both
# menus draw the highlighted row's mark and a key of the key line on it -- the look's own accent
# and dim, the nearest of 256 colours, none, and the light theme's.
CLIENTS = (({"TERM": "acme-tc"}, False, [{"1", "38;2;77;163;255"}, {"38;2;134;141;151"}]),
           ({"TERM": "acme-256"}, False, [{"1", "38;5;75"}, {"38;5;245"}]),
           ({"TERM": "acme-tc", "NO_COLOR": "1"}, False, [set(), set()]),
           ({"TERM": "acme-256"}, True, [{"1", "38;5;26"}, {"38;5;243"}]))


def compiled(home):
    """ENTRIES, each over xterm-256color, in a directory of that Home."""
    entries = Path(home.path) / "terminfo"
    for name, says in ENTRIES.items():
        source = f"{name}|a terminal, colors#256, {says} use=xterm-256color,\n"
        subprocess.run(["tic", "-x", "-o", str(entries), "-"], input=source, text=True,
                       check=True, capture_output=True)
    return entries


def drawn(term):
    """How the menu on `term` draws its mark and a key."""
    screen = settled(term, "esc leave")
    return [ink(look(screen, "›")), ink(look(screen, "esc", on="esc leave"))]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TrueColour(unittest.TestCase):
    def test_the_text_is_the_look_s_own_where_the_entry_says_true_colour(self):
        home = Home()
        self.addCleanup(home.close)
        entries = compiled(home)
        for name in ENTRIES:
            with self.subTest(entry=name):
                menu = Terminal(home, env={"TERM": name, "TERMINFO": str(entries)})
                self.addCleanup(home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
                shown = settled(menu, lambda text: "n starts one" in text)
                self.assertEqual(ink(look(shown, "n starts one")) - {"1"},
                                 {"38;5;254"} if name == "acme-256" else {"38;2;226;232;239"})

    def test_the_menu_over_a_seat_draws_a_terminal_as_the_one_in_the_whole_window_does(self):
        home = Home()
        self.addCleanup(home.close)
        home.fake("claude", "#!/bin/sh\nexec sleep 600\n")
        # its tmux starts with no NO_COLOR, the Home's for a piped run: a client's own is told
        # from it
        opened = home.ak("orch", "acme", "--model", "opus", "--workers", "opus", tty=True,
                         env={"NO_COLOR": None})
        self.assertEqual(opened.code, 0, opened.err)
        entries = compiled(home)
        Terminal(home, "--help").exit_code()    # its tmux keeps a background only while it is up
        for says, light, wanted in CLIENTS:
            with self.subTest(says=says, light=light):
                if light:       # the last: every terminal after it answers that background
                    done = home.tmux("set-option", "-g", "window-style", "bg=#ffffff",
                                     server=SERVER)
                    self.assertEqual(done.code, 0, done.err)
                env = {**says, "TERMINFO": str(entries)}
                # the seat first: nothing has asked that terminal its background before it
                seat = Terminal(home, "orch", "acme", env=env)
                self.addCleanup(home.tmux, "kill-session", "-t", seat.pane, server=SERVER)
                seat.wait("Ctrl-b m")           # its bar is up: the seat has the keys
                seat.keys("C-b", "m")
                over = drawn(seat)
                whole = Terminal(home, env=env)
                self.addCleanup(home.tmux, "kill-session", "-t", whole.pane, server=SERVER)
                self.assertEqual([over, drawn(whole)], [wanted, wanted])


if __name__ == "__main__":
    unittest.main()
