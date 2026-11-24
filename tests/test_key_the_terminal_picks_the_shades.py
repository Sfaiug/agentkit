"""Nothing chooses a theme: the terminal's background picks it, and ak adapts by itself.

The owner (20 Nov 2026): one theme, the terminal's own background used, "and ak just sits on top
of that"; on a light terminal, "Adapt by itself".  `c` has no `Theme` row, and config.toml's
`theme` is read by nothing.  A menu whose terminal answers what its background is draws in the
theme it fits and keeps the answer; what cannot ask -- a listing, a seat's bar -- and a menu
whose terminal does not answer draw in the theme the answer last kept fits, black till one is.

Black-box: the program AK_BIN names runs in a person's terminal of 24-bit colour
(tests/fixtures/akterm.py), which answers OSC 11 only once tmux's `window-style` sets its
background, over a working seat (tests/fixtures/akseat.py), each cell judged by how it looks
(tests/fixtures/aklooks.py).  The tests run in their order, in one Home.
"""

import sys
from pathlib import Path
import shutil
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

CONFIG, RUN = ".agentkit/config.toml", "20261120-0900-fix-api"
# the accent, `working`'s chip (on-accent on the accent) and `done`'s success: 0067c6, 007935
WHITE = ("38;2;0;103;198", {"38;2;255;255;255", "48;2;0;103;198"}, "38;2;0;121;53")
BLACK = ("38;2;77;163;255", {"38;2;0;0;0", "48;2;77;163;255"}, "38;2;51;182;95")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheTerminalPicksTheShades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        cls.config = (home.path / CONFIG).read_text()
        Terminal(home, "--help").exit_code()    # its tmux keeps a background only while it is up

    def open(self, *args, background=None):
        """`args` on a terminal of that background, or of none."""
        option = ["window-style", f"bg={background}"] if background else ["-u", "window-style"]
        done = self.home.tmux("set-option", "-g", *option, server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        term = Terminal(self.home, *args, size=(100, 40))
        self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
        return term

    def wait(self, read, wanted):
        """What `read` gives once it is `wanted`, or a minute on."""
        deadline = time.monotonic() + 60
        while (shown := read()) != wanted and time.monotonic() < deadline:
            time.sleep(0.1)
        return shown

    def assert_pointer(self, theme, background=None):
        """The ak screen's `›` is in `theme`'s accent."""
        menu = self.open(background=background)
        menu.wait("esc leave", 60)
        self.assertEqual(self.wait(lambda: look(looks(menu.screen(colours=True)), "›") & {
            WHITE[0], BLACK[0]}, {theme[0]}), {theme[0]})

    def assert_others(self, theme):
        """A seat's bar at its next draw and `ak run status` are in `theme`."""
        bar = self.open("orch", "acme")
        done = self.home.ak("orch", "why", "acme")      # a look at the seat dresses its bar
        self.assertEqual(done.code, 0, done.err)
        chip = lambda: next((set(look([line], "● working")) - ATTRIBUTES for line in looks(
            bar.screen(colours=True).rstrip("\n"))[-2:] if "● working" in plain(line)), None)
        self.assertEqual(self.wait(chip, theme[1]), theme[1], bar.screen())
        self.home.write(f".agentkit/runs/{RUN}/run.json", {      # a menu would sweep it first
            "run_id": RUN, "title": "Fix the API", "executor": "opus", "reviewer": "astra",
            "state": "pass", "merged": True, "rounds": 2, "round_summaries": [{}, {}],
            "started_at": time.time() - 120, "finished_at": time.time() - 60})
        try:
            listing = self.open("run", "status")
            self.assertEqual(listing.exit_code(60), 0, listing.screen())
            shown = look(looks(listing.screen(colours=True)), "done", on=RUN) - ATTRIBUTES
        finally:
            shutil.rmtree(self.home.path / ".agentkit/runs" / RUN)
        self.assertEqual(shown, {theme[2]})

    def test_a_c_shows_no_theme_row(self):
        menu = self.open()
        menu.wait("esc leave", 60)
        menu.keys("c")
        self.assertNotIn("Theme", menu.wait(lambda text: "Limits" in text and "esc back" in text))

    def test_b_a_theme_in_config_toml_is_read_by_nothing(self):
        self.home.write(CONFIG, 'theme = "white"\n' + self.config)
        self.assert_pointer(BLACK)
        self.home.write(CONFIG, 'theme = "black"\n' + self.config)
        self.assert_pointer(WHITE, "#ffffff")

    def test_c_what_cannot_ask_takes_the_theme_the_last_answer_fits(self):
        for background, theme in (("#ffffff", WHITE), ("#000000", BLACK)):
            with self.subTest(background=background):
                self.open(background=background).wait("esc leave", 60)      # a menu keeps it
                self.assert_others(theme)

    def test_d_a_menu_whose_terminal_does_not_answer_takes_the_kept_theme(self):
        self.open(background="#ffffff").wait("esc leave", 60)
        self.assert_pointer(WHITE)


if __name__ == "__main__":
    unittest.main()
