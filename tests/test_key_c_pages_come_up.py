"""The pages `c` opens come up and move as `c` does: `Models` opening is written a frame whose
header has `agentkit` and only part of `config · models` before the frame with all of it, and
Space on Weekly audit's `On` is written the half-way mark, `●` in the ink `○` had, before the new
one.  The light along the rule of one that waits is, 2.0 s on, where it was: it takes a breath.

The owner's ask of 27 Oct 2026, every screen moving as the main menu does.  Black-box: the
program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) with its colours,
its harnesses the fakes of tests/fixtures/fakeadapter.py.  Its clock injected: `AK_MOTION_CLOCK`
names a file of seconds that stands still until the test moves it, so a motion's frame is
written however late the host's load makes it; what the pane is written is read from tmux's
`pipe-pane`, never timed off a capture.  Fails against `/bin/false`.  No row on `c` opens
`Weekly audit` since 10 Nov 2026 (menu.CONFIG_ROWS): its page, Python ak's, runs in a terminal
by itself.
"""

import re
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

NAME = " · config · models"
NOTE = "takes it in or out of the config"      # under the rows of `Models` alone
HEADER = re.compile(r"agentkit([^\x1b\n]*?) +\d\d:\d\d")    # each header written, its name
SGR = re.compile(r"\x1b\[[\d;]*m")     # a header's name and clock in their own colour


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CPagesComeUp(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.claude = fakeadapter.install(self.home, claude="pass", codex="pass")["claude"]
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                   "astra": {"harness": "codex", "effort": "high"}})
        self.clock = self.home.root / "clock"
        self.at(1000)
        self.opened()
        self.term.wait("esc leave")
        self.term.keys("c", "j", "j")
        self.term.wait("› Models")

    def opened(self, page=None):
        """A terminal of its own on the clock, ak's menu or `page` (akterm.Terminal), what its
        pane is written piped to `raw`."""
        self.term = Terminal(self.home, size=(100, 30), env={"AK_MOTION_CLOCK": str(self.clock)},
                             page=page)
        self.raw = self.home.root / f"raw{self.term.pane}"
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{self.raw}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)

    def at(self, seconds):
        """ak's motion at `seconds` from now on: its clock's file swapped whole, never read half
        written."""
        self.now = seconds
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def written(self, until, since=0):
        """What the pane was written from byte `since` once it holds `until`."""
        deadline = time.monotonic() + 30
        while True:
            out = (self.raw.read_bytes() if self.raw.exists() else b"")[since:].decode(
                "utf-8", "replace")
            if re.search(until, out, re.S):
                return out
            assert time.monotonic() < deadline, f"never written {until!r}; written:\n{out!r}"
            time.sleep(0.05)

    def test_models_comes_up_its_name_writing_itself_out(self):
        self.term.keys("Enter")
        # the page's first frame writes it top down: its header, then under its rows its note
        out = SGR.sub("", self.written(NOTE))
        opened = [found[1] for found in HEADER.finditer(out, 0, out.index(NOTE))][-1]
        self.assertNotEqual(opened, NAME)
        self.assertTrue(NAME.startswith(opened), opened)
        self.at(self.now + 10)
        styles = f"(?:{SGR.pattern})*"
        self.written(f"{NOTE}.*agentkit{styles}{NAME}{styles} ")      # and then all of it

    def test_space_on_audits_on_is_written_half_way_before_the_new_mark(self):
        self.opened("config_audit")
        self.term.wait(lambda screen: re.search(r"› On +○ off", screen))
        self.at(self.now + 10)          # the page up
        shown = r"On +(\x1b\[[\d;]*m)○"        # its ink alone: the page up, no fade over it
        ink = re.findall(shown, self.written(shown))[-1]
        since = self.raw.stat().st_size
        self.term.keys("Space")
        self.written(re.escape(ink) + " ?●", since)    # half way while the clock stands, padded
        self.at(self.now + 10)
        # then in its own ink, the last ● of the last update: a whole redraw (terminal.TICK)
        # writes the drawn ● before the half over it
        self.written(rf"(?!{re.escape(ink)})\x1b\[[\d;]*m ?●[^●]*\x1b\[\?2026l[^●]*\Z", since)

    def lit(self, seconds, test):
        """Where the light on the rule under the header begins once the clock stands `seconds` on
        from 1000 and that passes `test`: None but while six cells in a row are lit, a run each."""
        self.at(1000 + seconds)
        deadline = time.monotonic() + 30
        while True:
            rule = self.term.screen(colours=True).splitlines()[1]
            runs = [len(run) for run in re.findall(r"(?:\x1b\[[\d;]*m)+(─+)", rule)]
            head = runs[0] if runs[1:-1] == [1] * 6 else None
            if test(head):
                return head
            assert time.monotonic() < deadline, f"no light passed {seconds} s on: {rule!r}"
            time.sleep(0.05)

    def test_the_light_on_the_rule_of_a_wait_is_where_it_was_2_s_on(self):
        held = self.claude.dir / "models.held"      # its catalog waits while this is there
        self.claude.script.write_text(self.claude.script.read_text().replace("exec ", (
            f'[ "$1" = models ] && while [ -e {shlex.quote(str(held))} ]; do sleep 0.05; '
            "done\nexec "), 1))
        self.term.keys("Enter")
        self.term.wait("› Claude Code")
        held.touch()
        self.addCleanup(held.unlink, missing_ok=True)
        self.term.keys("Enter")         # the wait begins now, on the clock as it stands, 1000
        self.term.wait("reading the models claude offers")
        was = self.lit(0.8, lambda head: head is not None)     # none while the clock stood
        between = self.lit(1.3, lambda head: head not in (None, was))
        self.assertEqual(self.lit(2.8, lambda head: head not in (None, between)), was)


if __name__ == "__main__":
    unittest.main()
