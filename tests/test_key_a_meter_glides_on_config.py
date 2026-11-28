"""A usage meter on the `c` screen glides to a new reading, as on the ak screen.

A reading for one of two logins written to `state/usage.json` under the open `c` screen: before
`motion.GLIDE` has passed, its `N% left` is between the old reading and the new, its bar the
length a screen opened on that `N` draws, the other login's cell as it was; once it has, the
meters' line is the one a screen opened on the new reading shows.  The other's reading written
while the first glides glides too, a later frame showing both between their old readings and
their new; a key pressed half way shows the new reading at once; one `empty until …` counts up
from under its reading, and one that becomes empty shows `empty until …` in the first draw after.

Black-box as tests/test_key_a_usage_meter_glides.py is: the program `AK_BIN` names, in a person's
terminal (tests/fixtures/akterm.py), its clock held through `AK_MOTION_CLOCK`, what the pane is
written read from tmux's `pipe-pane`.  Fails against `/bin/false`.
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
OWN = re.compile(r"Claude I +([━╸─]+)  (\d+)% left")         # the login whose reading moves
OTHER = re.compile(r"Claude II +([━╸─]+)  (\d+)% left")
UPDATE = re.compile(r"\x1b\[\?2026h(.*?)\x1b\[\?2026l", re.S)  # a draw or a frame, whole
ROW = re.compile(r"\x1b\[\d+;\d+H|\x1b\[[JK]|\n")             # where a row of one is written
CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MeterGlidesOnConfig(unittest.TestCase):
    def home(self, one, two=70):
        """A Home whose two Claude logins have `one` and `two` percent left."""
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, {"fable": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        clock.standing(home, "AK_MOTION_CLOCK", 1000.0)
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

    def opened(self, home):
        """`c` up in a terminal, come up whole, the menu's first probe landed, its pane piped."""
        term = Terminal(home, size=(100, 40), env={"COLORTERM": "truecolor"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        cache = home.path / ".agentkit/state/usage.json"
        term.wait(lambda _: all("probe_error" in login for login in json.loads(
            cache.read_text())["providers"]["anthropic"]["accounts"].values()))
        term.keys("c")
        term.wait("› Fable")
        self.at(home, 1001.0)
        term.wait(lambda screen: "agentkit · config " in screen.splitlines()[0], bound=10)
        term.raw = home.root / f"raw{term.pane.strip('%')}"
        named = shlex.quote(str(term.raw)).replace("%", "%%").replace("#", "##")
        piped = home.tmux("pipe-pane", "-O", "-t", term.pane, f"cat >>{named}", server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        return term

    def rows(self, term, since=0):
        """Every row written to the pane from byte `since` it was piped, of whole updates."""
        out = (term.raw.read_bytes()[since:] if term.raw.exists() else b"").decode(
            "utf-8", "replace")
        return [CSI.sub("", row) for update in UPDATE.findall(out) for row in ROW.split(update)]

    def written(self, home, term, one, two=70):
        """`one` and `two` read: the rows written from the first draw showing them on."""
        since = term.raw.stat().st_size if term.raw.exists() else 0
        self.read(home, one, two)
        said = (f"{one}% left" if one else "empty until", f"{two}% left")
        deadline = time.monotonic() + 30
        while True:
            rows = self.rows(term, since)
            first = next((n for n, row in enumerate(rows) if all(part in row for part in said)),
                         None)
            if first is not None:
                return rows[first:]
            self.assertLess(time.monotonic(), deadline, term.screen())
            time.sleep(0.03)

    def line(self, term, colours=False):
        line, = [line for line in term.screen(colours=True).splitlines()
                 if all(label in CSI.sub("", line) for label in ("Claude I ", "Claude II"))]
        return line if colours else CSI.sub("", line)

    def between(self, term, *meters):
        """`(bar, N)` of each `(meter, old, new)` once every `N` is strictly between the two."""
        def shown(screen):
            found = [meter.search(screen) for meter, _, _ in meters]
            return all(one and min(old, new) < int(one[2]) < max(old, new)
                       for one, (_, old, new) in zip(found, meters)) and found
        return [(one[1], int(one[2])) for one in shown(term.wait(shown, bound=10))]

    def test_a_new_reading_glides_there_the_other_s_too_and_a_key_ends_it(self):
        home = self.home(20)
        term = self.opened(home)
        still = self.line(term, colours=True)
        self.assertEqual(OWN.search(self.line(term)).groups(), ("━━────────", "20"))
        self.written(home, term, 80)
        term.wait(lambda _: self.line(term, colours=True) == still, bound=10)  # its first frame
        self.at(home, 1001 + GLIDE / 2)
        (bar, shown), = self.between(term, (OWN, 20, 80))
        self.assertEqual(bar, OWN.search(self.line(self.opened(self.home(shown))))[1])
        now = self.line(term, colours=True)
        self.assertEqual(now[now.index("Claude II"):], still[still.index("Claude II"):])
        self.at(home, 1001 + GLIDE + 0.05)
        term.wait(lambda _: "80% left" in self.line(term), bound=10)
        self.assertEqual(self.line(term, colours=True),
                         self.line(self.opened(self.home(80)), colours=True))

        self.at(home, 1003)
        self.written(home, term, 30)
        self.at(home, 1003.2)
        self.between(term, (OWN, 30, 80))
        self.written(home, term, 30, 40)            # the other's lands while the first glides
        self.at(home, 1003.2 + GLIDE / 2)
        self.between(term, (OWN, 30, 80), (OTHER, 40, 70))
        term.keys("Down")                           # half way: at once at the new readings
        term.wait(lambda screen: "› Models" in screen and OWN.search(screen)[2] == "30"
                  and OTHER.search(screen)[2] == "40", bound=10)

    def test_one_empty_counts_up_from_under_its_reading_and_one_emptied_is_at_once(self):
        home = self.home(0)
        term = self.opened(home)
        self.assertIn("Claude I   empty until", self.line(term))
        self.written(home, term, 80)
        self.assertIn("Claude I   empty until", self.line(term))
        counted = []
        for moment in (1001.1, 1001.2):
            self.at(home, moment)
            counted.append(self.between(term, (OWN, max([0, *counted]), 80))[0][1])
        self.assertLess(counted[0], counted[1])
        self.at(home, 1001 + GLIDE + 0.05)
        term.wait(lambda _: "80% left" in self.line(term), bound=10)
        self.assertFalse([row for row in self.written(home, term, 0) if OWN.search(row)])
        self.assertIn("Claude I   empty until", self.line(term))


if __name__ == "__main__":
    unittest.main(verbosity=2)
