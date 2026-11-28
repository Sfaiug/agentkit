"""A past session removed from `past sessions` fades out where it stood before it goes: `x` on
`theta` over `beta` and `Remove` picked, part way through `motion.LEAVES` `theta`'s row and the
question under it stand as they were in inks between their own and the background, `beta`'s row
as it was; past it no line names `theta` and `beta` has its row.  At 8 colours nothing fades.

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
LEAVES = 0.2                    # motion.LEAVES
PICKED = 1000.0                 # the moment `Remove` is picked, every motion before it at rest
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
    def removing(self, env):
        """`Remove` picked on `theta`'s card at PICKED, in a terminal with `env`: the screen's
        looks as the pick found them."""
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
        for key, shown in (("p", KEYS), ("x", "› ✓ Keep"), ("Down", "› × Remove")):
            self.term.keys(key)
            self.term.wait(shown)
        self.at(PICKED)
        before = self.shows(lambda rows: look(rows, "theta") == look(rows, "Remove theta")
                            == look(rows, "beta"))
        self.raw = self.home.root / "raw"
        self.raw.touch()
        self.home.tmux("pipe-pane", "-t", self.term.pane, f"cat >{self.raw}", server=SERVER)
        self.term.keys("Enter")
        return before

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

    def row(self, rows, text):
        return next(n for n, line in enumerate(rows) if text in plain(line))

    def test_the_row_and_its_card_fade_out_and_then_beta_takes_its_row(self):
        before = self.removing({"COLORTERM": "truecolor"})
        theta, question = self.row(before, "theta"), self.row(before, "Remove theta")
        beta = self.row(before, "beta")
        ink, ground = rgb(look(before, "beta")), rgb(look(before, "beta"), 48)    # all three's
        self.term.wait(lambda _: self.updates())        # the fade begun at PICKED
        self.at(PICKED + LEAVES / 2)
        self.shows(lambda rows: [plain(rows[n]) for n in (theta, question)]
                   == [plain(before[n]) for n in (theta, question)]
                   and between(rgb(look([rows[theta]], "theta")), ink, ground)
                   and between(rgb(look([rows[question]], "Remove theta")), ink, ground)
                   and rows[beta] == before[beta])
        self.at(PICKED + LEAVES + 0.05)
        after = self.term.wait(lambda screen: "theta" not in screen and KEYS in screen)
        self.assertIn("beta", after.split("\n")[theta])

    def test_at_eight_colours_the_first_screen_after_the_pick_has_no_theta(self):
        self.removing({"TERM": "xterm", "COLORTERM": ""})
        self.term.wait(lambda screen: "theta" not in screen and KEYS in screen)
        self.assertNotIn("theta", self.updates()[0])
        self.assertIn("beta", self.updates()[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
