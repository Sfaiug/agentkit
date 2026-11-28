"""A login's meter on `Subscriptions` glides to a new reading, as on `c` and the ak screen.

Two logins, the first holding a reset and highlighted, a new reading written to
`state/usage.json` under the open page.  The second's: before `motion.GLIDE` has passed, its
`N% left` is between the old reading and the new, its bar the length a page opened on that `N`
draws, the first's line as it was; once it has, its line is the one a page opened on the new
reading shows, and a key pressed half way through the next shows that at once.  The first's
glides the same, its line highlighted and saying its reset in hand in every frame.  Both
written at once 51 columns wide, where the reset fits beside a line saying `20% left` but not
`100% left`, either way: the page stays up and ends on the lines a page opened on the new
readings shows, each frame of the way up saying the reset beside its meter.

Black-box as tests/test_key_a_meter_glides_on_config.py is: the program `AK_BIN` names, in a
person's terminal (tests/fixtures/akterm.py), its clock held through `AK_MOTION_CLOCK`, what the
pane is written read from tmux's `pipe-pane`.  Fails against `/bin/false`.
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
FIRST = re.compile(r"Claude I +([━╸─]+)  (\d+)% left")        # the login holding a reset
SECOND = re.compile(r"Claude II +([━╸─]+)  (\d+)% left")
UPDATE = re.compile(r"\x1b\[\?2026h(.*?)\x1b\[\?2026l", re.S)  # a draw or a frame, whole
ROW = re.compile(r"\x1b\[\d+;\d+H|\x1b\[[JK]|\n")             # where a row of one is written
CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PAGE = "agentkit · config · subscriptions "
LABELS = ("Claude I", "Claude II")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MeterGlidesOnSubscriptions(unittest.TestCase):
    def home(self, one, two):
        """A Home whose two Claude logins have `one` and `two` percent left."""
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, {"fable": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        clock.standing(home, "AK_MOTION_CLOCK", 1000.0)
        self.read(home, one, two)
        return home

    def read(self, home, one, two):
        """`one` and `two` left, the first holding a reset, written whole under the cache's
        lock, as a probe that just landed writes them, so the menu's own probe holds off."""
        def login(left, **held):
            return {"meters": [{"name": "weekly", "used": 100 - left, "window_secs": 604800}],
                    "error": None, "probed_at": time.time(), **held}
        cache = home.path / ".agentkit/state/usage.json"
        with open(cache.with_suffix(".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            home.write(".agentkit/state/usage.new", {"fetched_at": time.time(), "providers": {
                "anthropic": {"accounts": {"default": login(one, resets=1),
                                           "two": login(two)}}}})
            os.replace(cache.with_name("usage.new"), cache)

    def at(self, home, seconds):
        moment = Path(home.env["AK_MOTION_CLOCK"])
        moment.with_suffix(".new").write_text(repr(seconds))
        moment.with_suffix(".new").replace(moment)

    def opened(self, home, size=(100, 40)):
        """`Subscriptions` up on the first login in a terminal, the menu's first probe landed,
        come up whole, its pane piped."""
        term = Terminal(home, size=size, env={"COLORTERM": "truecolor"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        cache = home.path / ".agentkit/state/usage.json"
        term.wait(lambda _: all("probe_error" in login for login in json.loads(
            cache.read_text())["providers"]["anthropic"]["accounts"].values()))
        term.keys("c")
        term.wait("› Fable")
        term.keys("Down", "Down")
        term.wait("› Subscriptions")
        term.keys("Enter")
        term.wait("› Claude I ")
        self.at(home, 1002.0)
        term.wait(lambda screen: PAGE in screen.splitlines()[0], bound=10)
        term.raw = home.root / f"raw{term.pane.strip('%')}"
        named = shlex.quote(str(term.raw)).replace("%", "%%").replace("#", "##")
        piped = home.tmux("pipe-pane", "-O", "-t", term.pane, f"cat >>{named}", server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        return term

    def rows(self, term, since, raw=False):
        """Every row written to the pane from byte `since` it was piped, of whole updates."""
        out = (term.raw.read_bytes()[since:] if term.raw.exists() else b"").decode(
            "utf-8", "replace")
        return [row if raw else CSI.sub("", row)
                for update in UPDATE.findall(out) for row in ROW.split(update)]

    def written(self, home, term, one, two, said):
        """`one` and `two` read, once a row written since says `said`: the byte they came at."""
        since = term.raw.stat().st_size if term.raw.exists() else 0
        self.read(home, one, two)
        deadline = time.monotonic() + 30
        while not any(said in row for row in self.rows(term, since)):
            self.assertLess(time.monotonic(), deadline, term.screen())
            time.sleep(0.03)
        return since

    def line(self, term, label, colours=False):
        found, = [line for line in term.screen(colours=True).splitlines()
                  if re.search(rf"{label} +[━╸─]+  \d+% left", CSI.sub("", line))]
        return found if colours else CSI.sub("", found)

    def between(self, term, meter, old, new):
        """`(bar, N)` of `meter` once its `N` is strictly between `old` and `new`."""
        shown = term.wait(lambda screen: (found := meter.search(screen))
                          and min(old, new) < int(found[2]) < max(old, new), bound=10)
        bar, left = meter.search(shown).groups()
        return bar, int(left)

    def glides(self, home, term, n, old, new, readings):
        """Login `n`, from 0, glides from `old` to `new` as `readings` are written at 1003, the
        other's line as it was: the byte they came at."""
        meter, label, other = (FIRST, *LABELS) if n == 0 else (SECOND, *LABELS[::-1])
        still, kept = (self.line(term, name, colours=True) for name in (label, other))
        self.at(home, 1003)
        since = self.written(home, term, *readings, f"{new}% left")
        term.wait(lambda _: self.line(term, label, colours=True) == still, bound=10)
        self.at(home, 1003 + GLIDE / 2)
        bar, shown = self.between(term, meter, old, new)
        self.assertEqual(self.line(term, other, colours=True), kept)
        fresh = self.opened(self.home(*readings[:n], shown, *readings[n + 1:]))
        self.assertEqual(bar, meter.search(self.line(fresh, label))[1])
        self.at(home, 1003 + GLIDE + 0.05)
        term.wait(lambda _: f"{new}% left" in self.line(term, label), bound=10)
        self.assertEqual(self.line(term, label, colours=True),
                         self.line(self.opened(self.home(*readings)), label, colours=True))
        return since

    def test_the_other_login_glides_and_a_key_shows_the_next_reading_at_once(self):
        home = self.home(20, 70)
        term = self.opened(home)
        self.glides(home, term, 1, 70, 30, (20, 30))
        self.at(home, 1005)
        self.written(home, term, 20, 90, "90% left")
        self.at(home, 1005 + GLIDE / 2)
        self.between(term, SECOND, 30, 90)
        term.keys("Down")                           # half way: at once at the new reading
        term.wait(lambda screen: "› Claude II" in screen and SECOND.search(screen)[2] == "90",
                  bound=10)

    def test_the_highlighted_login_glides_lit_saying_its_reset_in_hand(self):
        home = self.home(20, 70)
        term = self.opened(home)
        since = self.glides(home, term, 0, 20, 80, (80, 70))
        frames = [row for row in self.rows(term, since, raw=True)
                  if FIRST.search(CSI.sub("", row))]
        self.assertTrue({int(FIRST.search(CSI.sub("", row))[2]) for row in frames} - {20, 80})
        for row in frames:
            plain = CSI.sub("", row)
            self.assertTrue(plain.startswith("› Claude I "), plain)
            self.assertTrue(plain.endswith("% left · 1 reset in hand"), plain)
            self.assertIn("\x1b[1m", row)

    def both(self, home, term, moment, old, new):
        """Both logins' `old` readings `new`, written at once at `moment`: the rows written
        since, once both have glided there, none past the edge, where the terminal would wrap
        it over the row under it, and the page up."""
        self.at(home, moment)
        since = self.written(home, term, *new, f"{new[0]}% left")
        self.at(home, moment + GLIDE / 2)
        for meter, was, now in zip((FIRST, SECOND), old, new):
            self.between(term, meter, was, now)
        self.at(home, moment + GLIDE + 0.05)
        term.wait(lambda _: all(f"{left}% left" in self.line(term, name)
                                for name, left in zip(LABELS, new)), bound=10)
        rows = self.rows(term, since)
        self.assertLessEqual(max(len(row) for row in rows), 51)
        self.assertIn(PAGE, term.screen().splitlines()[0])
        return rows

    def test_both_at_once_on_a_narrow_screen_end_on_a_page_opened_there(self):
        home = self.home(100, 100)
        term = self.opened(home, (51, 40))
        opened = [self.line(term, name, colours=True) for name in LABELS]
        self.both(home, term, 1003, (100, 100), (20, 30))   # its reset in hand fits beside 20%
        fresh = self.opened(self.home(20, 30), (51, 40))
        self.assertEqual([self.line(term, name, colours=True) for name in LABELS],
                         [self.line(fresh, name, colours=True) for name in LABELS])
        rows = self.both(home, term, 1005, (20, 30), (100, 100))   # ... not beside 100%
        self.assertEqual([self.line(term, name, colours=True) for name in LABELS], opened)
        # but beside each frame between, which has room for it
        frames = [row for row in rows if (found := FIRST.search(row)) and 20 < int(found[2]) < 100]
        self.assertTrue(frames)
        for row in frames:
            self.assertTrue(row.endswith("% left · 1 reset in hand"), row)

if __name__ == "__main__":
    unittest.main(verbosity=2)
