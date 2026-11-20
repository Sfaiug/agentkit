"""Nothing chooses a theme: the terminal's background picks the shades, and ak adapts by itself.

The owner (20 Nov 2026): "I dont like that the user can switch and choose. First off I dont want
2 themes, I just want one, and the background of the terminal which the user has in its setting
should be used, and ak just sits on top of that."  On a light terminal: "Adapt by itself".  `c`
has no `Theme` row and config.toml's `theme` is read by nothing.  A menu whose terminal answers
what its background is draws in the shades that background fits and keeps the answer; whatever
cannot ask -- a listing, a seat's bar -- and a menu whose terminal does not answer draw in the
shades the answer last kept fits, the dark ones until one is kept.

The terminal here is tmux, which answers OSC 11 only once its panes' background is set
(`window-style`): unset, it stands for a terminal that never answers.  Black-box: the program
AK_BIN names runs in a person's terminal of 24-bit colour (tests/fixtures/akterm.py) over a
working seat (tests/fixtures/akseat.py), each cell judged by how it looks
(tests/fixtures/aklooks.py).  The tests run in their order, in one Home, each from what the one
before left kept.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

CONFIG = ".agentkit/config.toml"
RUN = "20261120-0900-fix-api"
# role: its colour in the light shades, and in the dark
SHADES = {"accent": ("0067c6", "4da3ff"), "on-accent": ("ffffff", "000000"),
          "success": ("007935", "33b65f")}
LIGHT, DARK = 0, 1


def fg(rgb):
    return "38;2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


def bg(rgb):
    return "48" + fg(rgb)[2:]


def role(name, shade, ground=fg):
    return ground(SHADES[name][shade])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheTerminalPicksTheShades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "Fix the API", "launched_session": "acme", "state": "done",
            "verdict": "PASS", "started_at": time.time() - 120, "finished_at": time.time() - 60})
        cls.config = (home.path / CONFIG).read_text()
        # The terminals' tmux keeps the background a test sets only while it is up, and a
        # terminal left open keeps it up.
        Terminal(home, "--help").exit_code()

    def open(self, *args, background=None):
        """`args` on a true-colour terminal of that background, or of none."""
        option = ["window-style", f"bg={background}"] if background else ["-u", "window-style"]
        done = self.home.tmux("set-option", "-g", *option, server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        term = Terminal(self.home, *args, size=(100, 40), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
        return term

    def pointer(self, background=None):
        """The ak screen's `›` once it is in the accent of either shade, or the look it has 30
        seconds on."""
        menu = self.open(background=background)
        menu.wait("esc leave", 60)
        accents = {role("accent", shade) for shade in (LIGHT, DARK)}
        deadline = time.monotonic() + 30
        while not (shown := look(looks(menu.screen(colours=True)), "›")) & accents:
            if time.monotonic() > deadline:
                break
            time.sleep(0.05)
        return shown

    def kept(self, background):
        """A menu run on a terminal of that background, which answers what it is."""
        self.open(background=background).wait("esc leave", 60)

    def assert_pointer(self, shade, background=None):
        self.assertIn(role("accent", shade), self.pointer(background))

    def assert_bar(self, shade):
        """A seat's bar, at its next draw, opens with `working` on-accent on the accent."""
        bar = self.open("orch", "acme")
        done = self.home.ak("orch", "why", "acme")      # a look at the seat dresses its bar
        self.assertEqual(done.code, 0, done.err)
        wanted, deadline = {role("on-accent", shade), role("accent", shade, bg)}, None
        while True:     # judged as it settles: ak's tmux learns the terminal takes true colour
            last = looks(bar.screen(colours=True).rstrip("\n"))[-2:]
            shown = (set(look(last, "● working")) - ATTRIBUTES
                     if any("● working" in plain(line) for line in last) else None)
            deadline = deadline or (shown is not None and time.monotonic() + 30)
            if shown == wanted or deadline and time.monotonic() > deadline:
                break
            time.sleep(0.2)
        self.assertEqual(shown, wanted)

    def assert_listing(self, shade):
        """`ak run status` colours its run's state in that shade's success."""
        listing = self.open("run", "status")
        self.assertEqual(listing.exit_code(60), 0, listing.screen())
        shown = look(looks(listing.screen(colours=True)), "done", on=RUN)
        self.assertEqual(shown - ATTRIBUTES, {role("success", shade)})

    def test_a_c_shows_no_theme_row(self):
        menu = self.open()
        menu.wait("esc leave", 60)
        menu.keys("c")
        screen = menu.wait(lambda text: "Limits" in text and "esc back" in text, 60)
        self.assertNotIn("Theme", screen)

    def test_b_a_theme_in_config_toml_is_read_by_nothing(self):
        self.home.write(CONFIG, 'theme = "white"\n' + self.config)
        self.assert_pointer(DARK)
        self.home.write(CONFIG, 'theme = "black"\n' + self.config)
        self.assert_pointer(LIGHT, "#ffffff")

    def test_c_what_cannot_ask_takes_the_shades_the_last_answer_fits(self):
        self.kept("#ffffff")
        self.assert_bar(LIGHT)
        self.assert_listing(LIGHT)
        self.kept("#000000")
        self.assert_bar(DARK)
        self.assert_listing(DARK)

    def test_d_a_menu_whose_terminal_does_not_answer_takes_the_kept_shades(self):
        self.kept("#ffffff")
        self.assert_pointer(LIGHT)


if __name__ == "__main__":
    unittest.main()
