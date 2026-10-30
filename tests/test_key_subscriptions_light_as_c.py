"""`Subscriptions` on `c` comes up and lights as `c` does: the pointer moving onto `Claude II`
is written a frame with its label part of the way to its company's colour before the frame
with all of it; the page opening is written a frame whose header has `agentkit` and only part
of `config · subscriptions` before the frame with all of it; `+ add a subscription` is bright
only while it is highlighted; a company is named in its colour; and the line a row opens comes
up under it.

The owner's ask of 27 Oct 2026, coherence everywhere.  Black-box: the program `AK_BIN` names,
in a person's terminal (tests/fixtures/akterm.py) with its colours, its harness the fake of
tests/fixtures/fakeadapter.py, the pointer typed as the SGR sequence a terminal sends for it.
A frame is the first of its motion whatever the host's load, so what the pane is written is
read from tmux's `pipe-pane`, never timed off a capture.  Fails against `/bin/false`.
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

NAME = " · config · subscriptions"
ADD = "+ add a subscription"          # the page's last line
HEADER = re.compile(r"agentkit([^\x1b\n]*?) +\d\d:\d\d")    # each header written, its name
SGR = re.compile(r"\x1b\[([\d;]*)m")
POINT = "\x1b[<35;8;{row}M"           # the pointer moved, no button down, at column 8 of a row
FADING = re.compile(r"\x1b\[38;2;[\d;]+m +− remove")     # the opened line part of the way up


def labels(out, label):
    """Each write of `label` from its own cell, the third column: the colour each of its
    letters is written in, None for none."""
    found = []
    for at in (place.end() for place in re.finditer(r"\x1b\[\d+;3H", out)):
        ink, inks, letters = None, [], ""
        while len(letters) < len(label) and at < len(out):
            if style := SGR.match(out, at):
                reset = style[1] in ("", "0") or style[1].startswith("0;")
                colours = re.findall(r"38;[25];[\d;]+", style[1])
                ink, at = colours[-1] if colours else None if reset else ink, style.end()
            elif out[at] == "\x1b":
                break                 # another cell's write: not this label
            else:
                inks, letters, at = [*inks, ink], letters + out[at], at + 1
        if letters == label:
            found.append(inks)
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SubscriptionsLightAsC(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, {"fable": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})

        def used(percent):
            return {"meters": [{"name": "weekly", "used": percent, "window_secs": 604800}]}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": time.time(), "providers": {
            "anthropic": {"accounts": {"default": used(16), "two": used(71)}}}})
        # Claude II's login ending in two days: FADING's `− remove` follows its `↻ log in again`
        self.home.write(".agentkit/state/logins.json", {"anthropic": {"two": {
            "ends": time.time() + 2 * 86400, "checked_at": time.time()}}})
        self.term = Terminal(self.home, size=(100, 30), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.raw = self.home.root / "raw"
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{self.raw}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        self.term.keys("c", "Down", "Down")
        self.term.wait("› Subscriptions")
        self.since = self.raw.stat().st_size
        self.term.keys("Enter")
        self.page = self.term.wait(lambda screen: f"agentkit{NAME} " in screen
                                   and "› Claude I " in screen)

    def written(self, until, since=0):
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

    def test_the_pointed_subscription_washes_into_its_company_s_colour(self):
        self.term.type(POINT.format(row=self.row("Claude I")))
        since = self.raw.stat().st_size
        self.term.type(POINT.format(row=self.row("Claude II")))

        def lit(inks):                # all of the label in one colour: the wash's last frame
            return inks[0] is not None and len(set(inks)) == 1
        out = self.written(lambda out: any(map(lit, labels(out, "Claude II"))), since)
        frames = labels(out, "Claude II")
        last = next(number for number, inks in enumerate(frames) if lit(inks))
        self.assertTrue(frames[:last], frames)          # part of the way first
        self.assertTrue(all(set(inks) != set(frames[last]) for inks in frames[:last]), frames)

    def test_the_page_comes_up_its_name_writing_itself_out(self):
        # the page's first frame writes it top down: its header, then under its rows `add`
        out = self.written(lambda out: ADD in out, self.since)
        opened = [found[1] for found in HEADER.finditer(out, 0, out.index(ADD))][-1]
        self.assertNotEqual(opened, NAME)
        self.assertTrue(NAME.startswith(opened), opened)
        self.written(lambda out: re.search(f"{re.escape(ADD)}.*agentkit{NAME} ", out, re.S),
                     self.since)        # and then all of it

    def test_add_a_subscription_is_bright_only_while_highlighted(self):
        def add(screen):              # its line as the terminal holds it, attributes and all
            return next(line for line in screen.split("\n") if ADD in line)
        self.assertNotIn("\x1b[1m", add(self.term.screen(colours=True)))
        self.term.keys("Down", "Down")
        self.term.wait(f"› {ADD}")
        self.assertIn("\x1b[1m", add(self.term.screen(colours=True)))

    def test_a_company_is_named_in_its_colour_as_c_names_a_harness(self):
        def named(_):                 # its line as the terminal holds it, attributes and all
            return next(line for line in self.term.screen(colours=True).split("\n")
                        if "Anthropic" in line)
        self.term.wait(lambda shown: "38;2;217;119;87" in named(shown))     # Claude's #D97757
        self.assertNotIn("\x1b[1m", named(None))

    def test_the_line_a_row_opens_comes_up_under_it(self):
        for _ in range(2):            # a move onto its row, then one back from off every row
            since = self.raw.stat().st_size
            self.term.type(POINT.format(row=self.row("Claude II")))
            self.written(FADING.search, since)
            self.term.type(POINT.format(row=1))     # the header
            self.term.wait(lambda screen: "− remove" not in screen)


if __name__ == "__main__":
    unittest.main()
