"""A usage meter on the ak screen glides to a new reading.

A reading for one of two logins written to `state/usage.json` while the ak screen is up: before
`motion.GLIDE` has passed, its `N% left` is between the old reading and the new, its bar the
length a screen opened on that `N` draws, the other login's cell as it was; once it has, the
line is the one a screen opened on the new reading shows.  An arrow pressed half way leaves it
between, the highlight leaving its line's last cell fading from that cell's whole width; one
`empty until …` counts up from below its reading; and at 19 columns, from `100% left` to
`8% left`, and at eight colours, the first frame after the reading is at the new one.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), its
clock held through `AK_MOTION_CLOCK` (tests/fixtures/clock.py), its harness faked
(tests/fixtures/fakeadapter.py), what the pane is written read from tmux's `pipe-pane`.  Fails
against `/bin/false`.
"""

import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

GLIDE = 0.7                     # motion.GLIDE
COLOURS = {"COLORTERM": "truecolor"}
METER = re.compile(r"([━╸─]+)  (\d+)% left")
OWN = re.compile(r"Claude I +([━╸─]+)  (\d+)% left")        # the login whose reading moves
UPDATE = re.compile(r"\x1b\[\?2026h(.*?)\x1b\[\?2026l", re.S)  # a draw or a frame, whole
ROW = re.compile(r"\x1b\[\d+;\d+H|\x1b\[[JK]|\n")             # where a row of one is written
CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MeterGlides(unittest.TestCase):
    def home(self, one, two=70):
        """A Home whose two Claude logins have `one` and `two` percent left, 0 spent."""
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, {"fable": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        clock.standing(home, "AK_MOTION_CLOCK", 999.0)
        self.read(home, one, two)
        return home

    def read(self, home, one, two=70):
        """`one` and `two` left, written whole under the cache's lock, as a probe that just
        landed writes them, so the menu's own probe holds off."""
        def login(left):
            week = {"name": "weekly", "used": 100 - left, "window_secs": 604800}
            if not left:
                week["resets_at"] = time.time() + 2 * 86400
            return {"meters": [week], "error": None, "probed_at": time.time()}
        cache = home.path / ".agentkit/state/usage.json"
        with open(cache.with_suffix(".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            home.write(".agentkit/state/usage.new", {"fetched_at": time.time(), "providers": {
                "anthropic": {"accounts": {"default": login(one), "two": login(two)}}}})
            os.replace(cache.with_name("usage.new"), cache)

    def at(self, home, seconds):
        moment = Path(home.env["AK_MOTION_CLOCK"])
        moment.with_suffix(".new").write_text(repr(seconds))
        moment.with_suffix(".new").replace(moment)

    def opened(self, home, size=(100, 40), env=COLOURS):
        """The ak screen up in a terminal, the menu's first probe landed, and its pane piped."""
        term = Terminal(home, size=size, env=env)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        cache = home.path / ".agentkit/state/usage.json"
        term.wait(lambda _: all("probe_error" in login for login in json.loads(
            cache.read_text())["providers"]["anthropic"]["accounts"].values()))
        # past the opening grow-in (`motion.GROW`), so the screen starts at rest at 1000.0
        self.at(home, 1000.0)
        term.wait(lambda screen: not re.search(r"(?<!\d)0% left", screen), bound=10)
        term.raw = home.root / f"raw{term.pane.strip('%')}"
        named = shlex.quote(str(term.raw)).replace("%", "%%").replace("#", "##")
        piped = home.tmux("pipe-pane", "-O", "-t", term.pane, f"cat >>{named}", server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        return term

    def rows(self, term):
        """Every row written to the pane since it was piped, of the updates it holds whole."""
        out = term.raw.read_bytes().decode("utf-8", "replace") if term.raw.exists() else ""
        return [CSI.sub("", row) for update in UPDATE.findall(out) for row in ROW.split(update)]

    def drawn(self, term, said):
        """Once a draw has written `said`: the screen's news begins at the clock's moment."""
        deadline = time.monotonic() + 30
        while not any(said in row for row in self.rows(term)):
            self.assertLess(time.monotonic(), deadline, term.screen())
            time.sleep(0.03)

    def line(self, term, colours=False):
        shown = term.screen(colours=True)
        line, = [line for line in shown.splitlines()      # the grid's, not the line under it
                 if all(label in CSI.sub("", line) for label in ("Claude I ", "Claude II"))]
        return line if colours else CSI.sub("", line)

    def between(self, term, old, new):
        """Claude I's `(bar, N)` once `N` is strictly between `old` and `new`."""
        lo, hi = sorted((old, new))
        shown = term.wait(lambda screen: (found := OWN.search(screen))
                          and lo < int(found[2]) < hi, bound=10)
        bar, left = OWN.search(shown).groups()
        return bar, int(left)

    def test_a_new_reading_glides_there_and_an_arrow_leaves_it_gliding(self):
        home = self.home(20)
        term = self.opened(home)
        still = self.line(term, colours=True)
        other = still[still.index("Claude II"):]
        self.assertEqual(OWN.search(self.line(term)).groups(), ("━━────────", "20"))
        self.read(home, 80)
        self.drawn(term, "80% left")
        term.wait(lambda _: self.line(term, colours=True) == still, bound=10)  # its first frame
        self.at(home, 1000 + GLIDE / 2)
        bar, shown = self.between(term, 20, 80)
        self.assertEqual(bar, OWN.search(self.line(self.opened(self.home(shown))))[1])
        now = self.line(term, colours=True)
        self.assertEqual(now[now.index("Claude II"):], other)
        self.at(home, 1000 + GLIDE + 0.05)
        term.wait(lambda _: "80% left" in self.line(term), bound=10)
        settled = self.line(term, colours=True)
        self.assertEqual(settled, self.line(self.opened(self.home(80)), colours=True))

        self.at(home, 1002)
        self.read(home, 30)
        self.drawn(term, "30% left")
        self.at(home, 1002 + GLIDE / 2)
        _, half = self.between(term, 30, 80)
        term.keys("Up")
        term.wait(lambda _: "48;" in self.line(term, colours=True), bound=10)     # lit
        self.assertEqual(OWN.search(self.line(term))[2], str(half))
        lit = self.line(term)               # Claude II, the last cell, lit over its whole width
        term.keys("Up")                     # onto Claude I: Claude II fades from that width
        term.wait(lambda _: (line := self.line(term, colours=True)).find("48;")
                  < line.find("Claude I "), bound=10)
        self.assertEqual(self.line(term), lit)
        self.at(home, 1002 + GLIDE + 0.05)
        term.wait(lambda _: "30% left" in self.line(term), bound=10)

    def test_a_meter_spent_counts_up_from_below_its_reading(self):
        home = self.home(0)
        term = self.opened(home)
        self.assertIn("Claude I   empty until", self.line(term))
        self.read(home, 80)
        self.drawn(term, "80% left")
        self.assertIn("Claude I   empty until", self.line(term))
        counted = []
        for moment in (1000.1, 1000.2):
            self.at(home, moment)
            counted.append(self.between(term, max([0, *counted]), 80)[1])
        self.assertLess(counted[0], counted[1])
        self.at(home, 1000 + GLIDE + 0.05)
        term.wait(lambda _: "80% left" in self.line(term), bound=10)

    def test_at_19_columns_and_at_eight_colours_the_first_frame_is_at_the_new_reading(self):
        home = self.home(100, 5)
        term = self.opened(home, size=(19, 40))
        self.assertIn("100%", term.screen())
        self.assertNotIn("% left", term.screen())     # no grid at 19 columns with 100% left
        self.read(home, 8, 5)
        self.drawn(term, "8% left")
        term.wait(lambda screen: "8% left" in screen, bound=10)
        self.at(home, 1000 + GLIDE / 2)
        term.keys("Up")
        term.wait(lambda _: "48;" in term.screen(colours=True), bound=10)
        written = [found[2] for row in self.rows(term) if (found := METER.search(row))]
        self.assertEqual(written[0], "8", written)
        self.assertLessEqual(set(written), {"8", "5"}, written)

        home = self.home(20)
        term = self.opened(home, env={"TERM": "xterm", "COLORTERM": ""})
        self.read(home, 80)
        self.drawn(term, "80% left")
        self.at(home, 1000 + GLIDE / 2)
        term.keys("Up")
        term.wait(lambda _: re.search(r"\x1b\[(?:\d+;)*7m", term.screen(colours=True)), bound=10)
        said = [found[2] for row in self.rows(term) if (found := OWN.search(row))]
        self.assertEqual(said[said.index("80"):], ["80"] * (len(said) - said.index("80")), said)
        self.assertLessEqual(set(said), {"20", "80"}, said)


if __name__ == "__main__":
    unittest.main(verbosity=2)
