"""On a light background a subscription's colour washes in and out of its meter through mixes of
the meter's own amber, its company's colour and the foreground, and through no other tone.

A pale company colour washing over an amber meter passes through light greys near its end; each
is drawn as the mix it is, never as the mirror tone a company's own light grey takes on a light
background, which would flash brown.  Black-box: the program `AK_BIN` names, in a person's
terminal (tests/fixtures/akterm.py) whose tmux answers OSC 11 with the white its panes are set
to (`window-style`), its harness the fake of tests/fixtures/fakeadapter.py, the pointer typed as
the SGR sequence a terminal sends for it.  Every frame is read from tmux's `pipe-pane`, never
timed off a capture.  Fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

COMPANY = (208, 248, 248)       # #D0F8F8: pale, but a hue, so drawn as it is on white
AMBER = (142, 94, 0)            # a meter whose login ends: the white theme's warning
TEXT = (24, 28, 34)             # ... and its text, the foreground the wash's edge lights toward
POINT = "\x1b[<35;8;{row}M"     # the pointer moved, no button down, at column 8 of a row
SGR = re.compile(r"\x1b\[([\d;]*)m")
FULL = "━╸"                     # a meter's full cells (terminal.share_parts)
TRIPS = 4                       # washes in and out: each frame mixes one cell part of the way


def meters(out, row):
    """Each write of a meter's cells from its own first cell on `row`: the colour each full cell
    is written in, None for none."""
    found = []
    for at in (place.end() for place in re.finditer(rf"\x1b\[{row};\d+H", out)):
        ink, inks = None, []
        while at < len(out):
            if style := SGR.match(out, at):
                rgb = re.findall(r"(?:^|;)38;2;(\d+);(\d+);(\d+)", style[1])
                reset = style[1] in ("", "0") or style[1].startswith("0;")
                ink = tuple(map(int, rgb[-1])) if rgb else None if reset else ink
                at = style.end()
            elif out[at] in FULL:
                inks, at = [*inks, ink], at + 1
            else:
                break
        if inks:
            found.append(inks)
    return found


def off_the_mix(rgb):
    """How far a tone is from the nearest a * AMBER + b * COMPANY, the rest TEXT (a, b >= 0):
    least squares for a and b, then the largest channel's miss."""
    amber, company, rgb = ([c - t for c, t in zip(ink, TEXT)] for ink in (AMBER, COMPANY, rgb))
    aa, cc = (sum(c * c for c in ink) for ink in (amber, company))
    ac = sum(p * q for p, q in zip(amber, company))
    ax, cx = (sum(p * v for p, v in zip(ink, rgb)) for ink in (amber, company))
    a, b = (ax * cc - cx * ac) / (aa * cc - ac * ac), (cx * aa - ax * ac) / (aa * cc - ac * ac)
    if a < 0:
        a, b = 0, max(0, cx / cc)
    elif b < 0:
        a, b = max(0, ax / aa), 0
    return max(abs(v - (a * p + b * q)) for v, p, q in zip(rgb, amber, company))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WashOnALightBackground(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, {"fable": "claude"}, providers={"anthropic": {
            "mode": "subscription", "accounts": ["default", "two"], "colour": "#D0F8F8"}})

        def used(percent):
            return {"meters": [{"name": "weekly", "used": percent, "window_secs": 604800}]}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": time.time(), "providers": {
            "anthropic": {"accounts": {"default": used(16), "two": used(16)}}}})
        # Claude II's login ends in two days: its meter rests amber
        self.home.write(".agentkit/state/logins.json", {"anthropic": {"two": {
            "ends": time.time() + 2 * 86400, "checked_at": time.time()}}})
        # tmux keeps the background a test sets only while its server is up
        Terminal(self.home, "--help").exit_code()
        done = self.home.tmux("set-option", "-g", "window-style", "bg=#ffffff", server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        # The menu reads the background once as it starts, from an answer within a
        # second; on a loaded host tmux answers later, which reads dark: start it again.
        for attempt in range(5):
            self.raw = self.home.root / f"raw{attempt}"
            if self.opened() == AMBER:
                return
            self.home.tmux("kill-session", "-t", self.term.pane, server=SERVER)
        self.fail("the menu never read the terminal's background as light")

    def opened(self):
        """The menu on its Subscriptions page, every byte written to it from there on in
        `self.raw`; the colour Claude II's meter rests in."""
        self.term = Terminal(self.home, size=(100, 30), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{self.raw}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        self.term.keys("c", "Down", "Down")
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "agentkit · config · subscriptions " in screen
                       and "› Claude I " in screen and self.rest())
        return self.rest()

    def rest(self):
        """The colour Claude II's meter is drawn in on the screen, None for none."""
        line = next((line for line in self.term.screen(colours=True).split("\n")
                     if "Claude II" in line), "")
        found = re.search(rf"38;2;(\d+);(\d+);(\d+)m[{FULL}]", line)
        return found and tuple(map(int, found.groups()))

    def written(self, until, since):
        """What the pane was written from byte `since` once `until` holds of it."""
        deadline = time.monotonic() + 30
        while True:
            out = (self.raw.read_bytes() if self.raw.exists() else b"")[since:].decode(
                "utf-8", "replace")
            if until(out):
                return out
            assert time.monotonic() < deadline, f"never written as asked; written:\n{out!r}"
            time.sleep(0.05)

    def row(self, label):
        return next(number for number, line in enumerate(self.term.screen().split("\n"), 1)
                    if f" {label} " in line)

    def test_the_wash_runs_through_mixes_of_its_colours_alone(self):
        inks = []
        for _ in range(TRIPS):
            for label, end in (("Claude II", COMPANY), ("Claude I", AMBER)):   # in, then out
                since = self.raw.stat().st_size
                self.term.type(POINT.format(row=self.row(label)))
                self.term.wait(f"› {label} ")
                row = self.row("Claude II")      # the line under the highlighted row moves it
                out = self.written(lambda out: any(set(cells) == {end}
                                                   for cells in meters(out, row)), since)
                inks += [ink for cells in meters(out, row) for ink in cells]
        between = set(inks) - {AMBER, COMPANY}
        self.assertGreater(len(between), TRIPS, inks)       # part of the way, frame after frame
        self.assertEqual([ink for ink in set(inks) if ink is None or off_the_mix(ink) > 2], [],
                         sorted(between, key=str))


if __name__ == "__main__":
    unittest.main()
