"""Text has three weights and a line its own colour: each a role of the theme in force.

The owner (12 Nov 2026): "look at every place where things are visual to the end user inside of
ak, and see through to apply the following two themes."  A name or a number is in `text`; what
says more about the thing beside it -- the header's name and clock, a key's word, a seat's model
and its count, a row's value on `c` -- in `muted`; what the eye passes over -- a row's number, a
key, a ` · ` -- in `dim`; a line that is not text -- the rule, a bar's empty part -- in `border`; and what
ak says of its own accord, `1 reset in hand`, in `info` (docs/cli-design.md, Colour).
Black-box: the program AK_BIN names runs in a person's terminal of 24-bit colour
(tests/fixtures/akterm.py) over a working seat with a plan (tests/fixtures/akseat.py) and a
subscription holding a reset, each cell judged by the colour of its text, whatever it is on
(tests/fixtures/aklooks.py).  Its clock injected as tests/test_key_themes.py injects it, so what
moves as a screen opens has moved on however busy the host.
"""

import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import look, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

# each role in the white theme, and in the black
ROLES = {"border": ("b1b8c0", "3a3f46"), "muted": ("535962", "acb4bd"),
         "text": ("181c22", "e2e8ef"), "dim": ("6f757e", "868d97"), "info": ("00747d", "00b0bf")}
WHITE, BLACK = 0, 1
OPENED = 1000.0     # the moment ak's motion stands at as the menu opens


def fore(shown):
    """A look's text colour, whatever it is on and however bold."""
    return {part for part in shown if part.startswith("38")}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TextHasThreeWeights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        now = time.time()
        home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {"anthropic": {
            "meters": [{"name": "weekly", "used": 60, "window_secs": 604800}], "resets": 1,
            "error": None, "probed_at": now}}})
        home.write(".agentkit/state/logins.json", {"anthropic": {"default": {
            "email": "owner@acme.test", "plan": "max 20x", "checked_at": now}}})
        home.write(".agentkit/state/plan-acme.md",
                   "- [x] One\n- [x] Two\n- [ ] Three\n- [ ] Four\n- [ ] Five\n")
        Seat(home, "acme", screen="claude-working-pane.txt")
        # and one closed, its plan 3 of 4 done, for `p`
        home.write(".agentkit/state/session-fix-api.json", {
            "orchestrator": "opus", "workers": ["opus"], "cwd": str(home.path / "code/acme"),
            "created": int(now) - 7200, "conversation": "conv-fix-api", "id_source": "launcher",
            "resumable": True, "session_title": "fix-api"})
        home.write(".agentkit/state/seat-fix-api.json",
                   {"stopped_at": now - 3600, "closed_by_owner": True})
        home.write(".agentkit/state/plan-fix-api.md",
                   "- [x] One\n- [x] Two\n- [x] Three\n- [ ] Four\n")
        # The terminals' tmux keeps the background a test sets only while it is up, and a
        # terminal left open keeps it up.
        Terminal(home, "--help").exit_code()
        cls.clock = home.root / "clock"

    def at(self, seconds):
        """ak's motion at `seconds` from now on, its clock's file swapped whole."""
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def rest(self, term, shown, moment, check):
        """What `check` makes of the screen's looks once it shows `shown` with ak's motion at
        `moment`: asked again until it holds, as a busy host draws that moment late, and at last
        failing as it does."""
        term.wait(shown, 60)
        self.at(moment)
        deadline = time.monotonic() + 60
        while True:
            try:
                return check(looks(term.screen(colours=True)))
            except AssertionError:
                if time.monotonic() > deadline:
                    raise
            time.sleep(0.1)

    def assert_in(self, theme, role, shown, what):
        self.assertEqual(fore(shown), {"38;2;" + ";".join(map(str, bytes.fromhex(
            ROLES[role][theme])))}, f"{what} is not in {role}")

    def assert_line(self, theme, line, what, start=0, end=None):
        """Every `─` of `line`'s plain text from `start` to `end` in the border."""
        drawn = [shown for char, shown in line[start:end] if char == "─"]
        self.assertTrue(drawn, f"no `─` in {what}: {plain(line)!r}")
        for shown in drawn:
            self.assert_in(theme, "border", shown, what)

    def assert_weights(self, background, theme):
        option = ["window-style", f"bg={background}"] if background else ["-u", "window-style"]
        done = self.home.tmux("set-option", "-g", *option, server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        self.at(OPENED)
        menu = Terminal(self.home, size=(100, 50), env={"COLORTERM": "truecolor",
                                                        "AK_MOTION_CLOCK": str(self.clock)})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)

        def first(texts, *words):
            """The number of the first of `texts` showing every one of `words`."""
            found = [n for n, text in enumerate(texts) if all(word in text for word in words)]
            self.assertTrue(found, f"no line shows {words}")
            return found[0]

        def ak(rows):
            texts = [plain(line) for line in rows]
            top = first(texts, "agentkit")
            self.assert_in(theme, "text", look(rows, "agentkit"), "`agentkit`")
            self.assert_in(theme, "muted", look(rows, texts[top].split()[-1], on="agentkit"),
                           "the header's clock")
            self.assert_line(theme, rows[top + 1], "the rule")
            meter = first(texts, "40% left")
            self.assert_line(theme, rows[meter], "the meter", texts[meter].index("━"),
                             texts[meter].index("40% left"))
            self.assert_in(theme, "text", look(rows, "40% left"), "the meter's `% left`")
            seat = first(texts, " 1  acme  ", "2 of 5")
            self.assert_line(theme, rows[seat], "the seat's line", texts[seat].index("━"))
            self.assert_in(theme, "muted", look(rows, "2 of 5"), "the seat's count")
            self.assert_in(theme, "text", look(rows, "acme", on="2 of 5"), "the seat's name")
            number = texts[seat].index(" 1  acme") + 1
            self.assert_in(theme, "dim", rows[seat][number][1], "the seat's number")
            model = re.search(r" 1  acme  (.+?)  ", texts[seat])[1]
            self.assert_in(theme, "muted", look(rows, model, on="2 of 5"), "the seat's model")
            keys = first(texts, "esc leave")
            self.assert_in(theme, "dim", rows[keys][texts[keys].index("c config")][1],
                           "the `c` of `c config`")
            self.assert_in(theme, "muted", look(rows, "config", on="esc leave"), "`config`")
            return meter, model
        meter, model = self.rest(menu, lambda text: "esc leave" in text and " of 5" in text,
                                 OPENED + 10, ak)

        # the pointer on the meter says its resets in hand under the grid; off it, every model
        # its colour washed into drains back to its own
        menu.type(f"\033[<35;8;{meter + 1}M")
        self.rest(menu, "1 reset in hand", OPENED + 12, lambda rows: self.assert_in(
            theme, "info", look(rows, "1 reset in hand"), "the meter's resets in hand"))
        menu.type("\033[<35;1;1M")
        self.rest(menu, lambda text: "1 reset in hand" not in text, OPENED + 14,
                  lambda rows: self.assert_in(theme, "muted", look(rows, model, on="2 of 5"),
                                              "the model, the pointer off"))

        def c(rows):
            self.assert_in(theme, "muted", look(rows, "config", on="agentkit"), "the header's name")
            self.assert_in(theme, "muted", look(rows, "not connected", on="Discord"),
                           "a row's value")
        menu.keys("c")
        self.rest(menu, lambda text: "› " in text and "Discord" in text, OPENED + 20, c)

        def pointed(text):    # the highlighted row
            return next((line for line in text.split("\n") if line.startswith("› ")), None)
        while "Subscriptions" not in (row := pointed(menu.screen())):
            menu.keys("Down")
            menu.wait(lambda text: pointed(text) not in (None, row), 30)

        def beside(rows):
            self.assert_in(theme, "info", look(rows, "1 reset in hand", on="› Claude"),
                           "`1 reset in hand`")
            self.assert_in(theme, "dim", look(rows, " · ", on="1 reset in hand"),
                           "the ` · ` before it")
        menu.keys("Enter")
        self.rest(menu, "1 reset in hand", OPENED + 30, beside)

        # with no room beside its meter it goes on the line under the row, itself still
        def under(rows):
            self.assert_in(theme, "info", look(rows, "1 reset", on="owner@acme.test"),
                           "`1 reset in hand` under the row")
            self.assert_in(theme, "dim", look(rows, " · ", on="owner@acme.test"),
                           "the ` · ` there")
        menu.resize(40, 50)
        self.rest(menu, lambda text: any("owner@acme.test" in line and "1 reset" in line
                                         for line in text.split("\n")), OPENED + 40, under)

        # a login ending soon turns its parts amber, never the ` · `s between them
        logins = self.home.path / ".agentkit/state/logins.json"
        self.addCleanup(logins.write_text, logins.read_text())
        self.home.write(".agentkit/state/logins.json", {"anthropic": {"default": {
            "email": "owner@acme.test", "plan": "max 20x", "ends": int(time.time()) + 86400,
            "checked_at": time.time()}}})

        def ending(rows):
            texts = [plain(line) for line in rows]
            opened = rows[first(texts, "› Claude") + 1:first(texts, "+ add a subscription")]
            dots = [shown for line in opened for char, shown in line if char == "·"]
            self.assertTrue(dots, "no ` · ` under the row")
            for shown in dots:
                self.assert_in(theme, "dim", shown, "a ` · ` beside a login ending soon")
        self.rest(menu, "login owner@acme.test", OPENED + 45, ending)

        # and a closed seat's count on `p`, in as little room
        menu.keys("Escape")
        menu.wait(lambda text: "subscriptions" not in text.split("\n")[0], 30)
        menu.keys("Escape")
        menu.wait(lambda text: "config" not in text.split("\n")[0], 30)
        menu.keys("p")
        self.rest(menu, " of 4", OPENED + 50, lambda rows: self.assert_in(
            theme, "muted", look(rows, "3 of 4"), "a closed seat's count"))

    def test_on_a_terminal_that_sets_no_background_each_is_its_role_of_black(self):
        self.assert_weights(None, BLACK)

    def test_on_a_white_background_each_is_its_role_of_white(self):
        self.assert_weights("#ffffff", WHITE)


if __name__ == "__main__":
    unittest.main()
