"""A past session removed from `past sessions` fades out where it stood before it goes: `x` on
`theta` over `beta` and `Remove` picked, part way through `motion.LEAVES` `theta`'s row and the
card under it stand as they were, each in an ink and background between its own and the screen's
background, `beta`'s row as it was; past it no line names `theta` and `beta` has its row.  What
still moves -- the card coming up, its highlight -- leaves from where it stood; a key typed
meanwhile is read after; a resize the card answered ends nothing, one meanwhile the fade at once.
At 8 colours nothing fades.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) on the
injected motion clock (tests/fixtures/clock.py), each update it writes read by `pipe-pane`.
"""

import os
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import clock
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import look, looks, plain
from fixtures.akterm import SERVER, Terminal

TZ = f"AKT{time.gmtime().tm_hour - 12:+d}"      # past noon, so both seats closed today
os.environ["TZ"] = TZ
time.tzset()
FADE, LEAVES = 0.15, 0.2        # motion.FADE, motion.LEAVES
OPENED, PICKED = 1000.0, 1010.0     # the page up, the card coming up; `Remove` picked at rest
KEYS = "  ↑↓←→ move   ⏎ reopen   x remove   esc back"
UPDATE = re.compile(r"\x1b\[\?2026h(.*?)\x1b\[\?2026l", re.S)
CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def rgb(shown, ground=38):
    """A look's colour of `ground`, 38 its text's or 48 its background's, as (R, G, B)."""
    return next((tuple(map(int, part.split(";")[2:])) for part in shown
                 if part.startswith(f"{ground};2;")), None)


def between(colour, start, end):
    """Whether `colour` is neither `start` nor `end`, each channel between theirs."""
    return colour not in (None, start, end) and all(
        min(a, b) <= c <= max(a, b) for c, a, b in zip(colour, start, end))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ARemovedPastSessionFadesOut(unittest.TestCase):
    def removing(self, env, how="rest"):
        """`Remove` picked on `theta`'s card in a terminal with `env`, `how`: by Enter at `rest`,
        `resized` after two resizes it was drawn anew for, or as the highlight still `moves` onto
        it; or by a click as the card still `rises`.  The screen's looks as the pick found them."""
        self.home = Home()
        self.addCleanup(self.home.close)
        checkout = self.home.path / "code/acme"
        checkout.mkdir(parents=True)
        assert self.home.run("git", "init", "-q", str(checkout)).code == 0
        for name, closed in (("theta", time.time() - 600), ("beta", time.time() - 1200)):
            self.home.write(f".agentkit/state/session-{name}.json", {
                "orchestrator": "fable", "workers": ["fable"], "cwd": str(checkout),
                "repo": str(checkout), "created": int(closed) - 3600,
                "conversation": f"conv-{name}", "id_source": "launcher", "resumable": True,
                "session_title": name})
            self.home.write(f".agentkit/state/seat-{name}.json",
                            {"stopped_at": closed, "closed_by_owner": True})
        clock.standing(self.home, "AK_MOTION_CLOCK", 0.0)
        self.term = Terminal(self.home, size=(100, 30), env={"TZ": TZ, **env})
        self.term.wait("p past")
        self.term.keys("p")
        self.term.wait(KEYS)
        self.at(OPENED)
        self.term.keys("x")
        self.term.wait("› ✓ Keep")
        if how == "rises":              # part way up
            self.at(OPENED + FADE / 2)
            before = self.shows(lambda rows: between(rgb(look(rows, "Remove theta")), *(
                rgb(look(rows, "beta"), ground) for ground in (38, 48))))
            row = self.row(before, "× Remove")
            at = f"{plain(before[row]).index('×') + 1};{row + 1}"
            pick = f"\x1b[<0;{at}M\x1b[<0;{at}m"
        else:
            self.term.keys("Down")
            self.term.wait("› × Remove")
            if how == "moves":          # from Keep, at the clock's first frame of it
                before = self.shows(lambda rows: rgb(look(rows, "✓ Keep"), 48)
                                    != rgb(look(rows, "beta"), 48))
            else:
                self.at(PICKED)
                for width in (105, 110) if how == "resized" else ():    # the last, nothing moving
                    self.term.resize(width, 30)
                    self.term.wait("─" * width)
                before = self.shows(self.rest)
            pick = "\r"
        self.raw = self.home.root / "raw"
        self.raw.touch()
        self.home.tmux("pipe-pane", "-t", self.term.pane, f"cat >{self.raw}", server=SERVER)
        self.term.type(pick)
        return before

    def rest(self, rows):
        """Whether the card is up and its highlight on `Remove` alone, at rest."""
        return all(look(rows, text) == look(rows, "beta")
                   for text in ("theta", "Remove theta", "✓ Keep"))

    def at(self, seconds):
        """ak's motion at `seconds` from now on, its clock's file swapped whole."""
        moment = Path(self.home.env["AK_MOTION_CLOCK"])
        moment.with_suffix(".new").write_text(repr(seconds))
        moment.with_suffix(".new").replace(moment)

    def shows(self, test):
        """The screen's looks once `test` of them holds, `look` failing on none: tmux may be
        read part way through a frame."""
        deadline = time.monotonic() + 30
        while True:
            rows = looks(self.term.screen(colours=True))
            try:
                if test(rows):
                    return rows
            except AssertionError:
                pass
            self.assertLess(time.monotonic(), deadline, f"never so:\n{self.term.screen()}")
            time.sleep(0.05)

    def updates(self):
        """Each whole update written since `Remove` was picked, as the text it shows."""
        return [CSI.sub("", update) for update in UPDATE.findall(
            self.raw.read_bytes().decode("utf-8", "replace"))]

    def begun(self, _screen=None):
        """Whether the fade has written its first frame: the card's question, as it stood."""
        return any("Remove theta" in update for update in self.updates())

    def row(self, rows, text):
        return next(n for n, line in enumerate(rows) if text in plain(line))

    def leaving(self, rows, before, text, ground=38):
        """Whether `text`'s line stands as it did `before`, its `ground` part way from there to
        the screen's background."""
        n, screen = self.row(before, text), rgb(look(before, "beta"), 48)
        return plain(rows[n]) == plain(before[n]) and between(
            rgb(look([rows[n]], text), ground), rgb(look([before[n]], text), ground), screen)

    def test_the_row_and_its_card_fade_out_and_then_beta_takes_its_row(self):
        before = self.removing({"COLORTERM": "truecolor"})
        beta = self.row(before, "beta")
        self.term.wait(self.begun)
        self.at(PICKED + LEAVES / 2)
        self.shows(lambda rows: self.leaving(rows, before, "theta")
                   and self.leaving(rows, before, "Remove theta")
                   and self.leaving(rows, before, "× Remove", 48) and rows[beta] == before[beta])
        self.at(PICKED + LEAVES + 0.05)
        after = self.term.wait(lambda screen: "theta" not in screen and KEYS in screen)
        self.assertIn("beta", after.split("\n")[self.row(before, "theta")])

    def test_what_still_moves_leaves_from_where_it_stood(self):
        for how in ("rises", "moves"):
            with self.subTest(how):
                before = self.removing({"COLORTERM": "truecolor"}, how)
                self.term.wait(self.begun)
                shown = looks(self.term.screen(colours=True))
                for text in ("Remove theta", "✓ Keep", "× Remove"):
                    self.assertEqual(look(shown, text), look(before, text), text)

    def test_a_key_typed_meanwhile_is_read_after_and_a_resize_ends_it_at_once(self):
        before = self.removing({"COLORTERM": "truecolor"}, "resized")
        theta = self.row(before, "theta")
        self.term.wait(self.begun)
        self.at(PICKED + LEAVES / 2)
        mid = self.shows(lambda rows: self.leaving(rows, before, "theta"))
        self.term.keys("Escape")
        self.at(PICKED + LEAVES * 3 / 4)
        self.shows(lambda rows: self.leaving(rows, before, "theta") and rows[theta] != mid[theta])
        self.term.resize(90, 30)        # the clock never passes LEAVES
        self.term.wait(lambda screen: "esc leave" in screen and "past sessions" not in screen)
        self.assertFalse((self.home.path / ".agentkit/state/session-theta.json").exists())

    def test_at_eight_colours_the_first_screen_after_the_pick_has_no_theta(self):
        self.removing({"TERM": "xterm", "COLORTERM": ""})
        self.term.wait(lambda screen: "theta" not in screen and KEYS in screen)
        self.assertNotIn("theta", self.updates()[0])
        self.assertIn("beta", self.updates()[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
