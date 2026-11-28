"""Usage meters on the ak screen grow in from empty as it opens.

Two logins in `state/usage.json`, one at 80% left and one `empty until …`, in a home with no
seat: with the motion clock held before `motion.GROW` has passed, the first login shows an `N`
under 80 and a bar shorter than at 80 while the second stands as on a settled screen; past
`motion.GROW`, the grid is a settled screen's, and returning from `c` does not start it again;
a reading landing mid-grow glides from the reading before; and at eight colours the first
screen says `80% left`.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), its
clock held through `AK_MOTION_CLOCK` (tests/fixtures/clock.py), its harness faked
(tests/fixtures/fakeadapter.py).  Fails against `/bin/false`.
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

GROW = 0.45                     # motion.GROW
GLIDE = 0.7                     # motion.GLIDE
COLOURS = {"COLORTERM": "truecolor"}
OWN = re.compile(r"Claude I +([━╸─]+)  (\d+)% left")
UPDATE = re.compile(r"\x1b\[\?2026h(.*?)\x1b\[\?2026l", re.S)
ROW = re.compile(r"\x1b\[\d+;\d+H|\x1b\[[JK]|\n")
CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def filled(bar):
    """Filled length of `bar`, in half cells."""
    return 2 * bar.count("━") + bar.count("╸")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MetersGrowIn(unittest.TestCase):
    def home(self, one=80, two=0):
        """A Home with no seats and two Claude logins: `one` and `two` percent left, 0 spent."""
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, {"fable": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        clock.standing(home, "AK_MOTION_CLOCK", 1000.0)
        self.read(home, one, two)
        return home

    def read(self, home, one, two=0):
        """Write `one` and `two` left under the cache's lock, fresh so the menu's probe holds off."""
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
        """The ak screen up in a terminal, its first probe landed, its pane piped."""
        term = Terminal(home, size=size, env=env)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        cache = home.path / ".agentkit/state/usage.json"
        term.wait(lambda _: all("probe_error" in login for login in json.loads(
            cache.read_text())["providers"]["anthropic"]["accounts"].values()))
        term.raw = home.root / f"raw{term.pane.strip('%')}"
        named = shlex.quote(str(term.raw)).replace("%", "%%").replace("#", "##")
        piped = home.tmux("pipe-pane", "-O", "-t", term.pane, f"cat >>{named}", server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        return term

    def rows(self, term):
        out = term.raw.read_bytes().decode("utf-8", "replace") if term.raw.exists() else ""
        return [CSI.sub("", row) for update in UPDATE.findall(out) for row in ROW.split(update)]

    def drawn(self, term, said):
        deadline = time.monotonic() + 30
        while not any(said in row for row in self.rows(term)):
            self.assertLess(time.monotonic(), deadline, term.screen())
            time.sleep(0.03)

    def line(self, term, colours=False):
        shown = term.screen(colours=True)
        line, = [line for line in shown.splitlines()
                 if all(label in CSI.sub("", line) for label in ("Claude I ", "Claude II"))]
        return line if colours else CSI.sub("", line)

    def test_meters_grow_in_from_empty_and_settle(self):
        home = self.home(80, 0)
        term = self.opened(home)
        # held at opening (before GROW): empty bar and 0% left, Claude II already `empty until`
        bar0, left0 = OWN.search(self.line(term)).groups()
        self.assertLess(int(left0), 80)
        self.assertIn("Claude II  empty until", self.line(term))
        # held part way through GROW: strictly under 80 and shorter than at 80
        self.at(home, 1000.0 + GROW / 2)
        shown = term.wait(lambda screen: (found := OWN.search(screen))
                          and 0 < int(found[2]) < 80, bound=10)
        bar, left = OWN.search(shown).groups()
        mid = self.line(term, colours=True)
        # past GROW: settled grid matches a fresh draw after returning from `c` (which does not
        # grow in again)
        self.at(home, 1000.0 + GROW + 0.05)
        term.wait(lambda _: "80% left" in self.line(term), bound=10)
        settled = self.line(term, colours=True)
        full_bar, full_left = OWN.search(self.line(term)).groups()
        self.assertEqual((full_bar, full_left), ("━━━━━━━━──", "80"))
        self.assertLess(filled(bar0), filled(full_bar))
        self.assertLess(filled(bar), filled(full_bar))
        self.assertEqual(mid[mid.index("Claude II"):], settled[settled.index("Claude II"):])

        term.keys("c")
        term.wait("esc back")
        term.keys("Escape")
        term.wait("esc leave")
        self.assertEqual(self.line(term, colours=True), settled)

    def test_a_reading_landing_mid_grow_glides_from_the_reading_before(self):
        home = self.home(80, 0)
        term = self.opened(home)
        self.at(home, 1000.0 + GROW / 2)
        term.wait(lambda screen: (found := OWN.search(screen)) and 0 < int(found[2]) < 80,
                  bound=10)
        self.read(home, 20, 0)
        self.drawn(term, "20% left")
        # gliding from 80 (the reading before) to 20: its first frame is at 80
        term.wait(lambda _: OWN.search(self.line(term))[2] == "80", bound=10)
        self.at(home, 1000.0 + GROW / 2 + GLIDE / 2)
        term.wait(lambda screen: (found := OWN.search(screen)) and 20 < int(found[2]) < 80,
                  bound=10)
        self.at(home, 1000.0 + GROW / 2 + GLIDE + 0.05)
        term.wait(lambda _: "20% left" in self.line(term), bound=10)

    def test_at_eight_colours_the_first_screen_says_80_left(self):
        home = self.home(80, 0)
        term = self.opened(home, env={"TERM": "xterm", "COLORTERM": ""})
        self.assertEqual(OWN.search(self.line(term)).groups(), ("━━━━━━━━──", "80"))
        self.assertIn("Claude II  empty until", self.line(term))


if __name__ == "__main__":
    unittest.main(verbosity=2)
