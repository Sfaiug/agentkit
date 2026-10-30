"""The fresh-install gate's checks that fail on the release before too are handed back once.

On 27 Oct the fresh-install gate failed `c`, `d` and `d2` on every run, old release as new, and
`ak update` kept each upgrade past them, as agentkit's own checks, saying so only in its result
line.  Now such an upgrade leaves one line naming those checks, which the tick hands back once:
the same checks again hand back nothing new until the fresh gate passes with no check failed, a
different set is handed back, and a line not yet told stands as written whatever later upgrades
find.  Black-box: `ak update` runs the program `AK_BIN` names through tests/fixtures/akbin.py,
with a fake `claude` keeping its installed release in a file and the gates stood in for by
tests/fixtures/akgates.py; each tick runs the live install tests/fixtures/akinstall.py copies to
HOME/agentkit, which types the line into the seat that merged into agentkit; this test fails
against `/bin/false`.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akgates import Gates
from fixtures.akinstall import Install

OLD, NEW, NEWER = "2.1.0", "2.2.0", "2.3.0"
# `claude install latest` installs what the channel file names, and with `moves` there the
# channel is on a newer release by the next install.
CLAUDE = """#!/bin/sh
case "$1 $2" in
  "--version "*) cat {root}/installed ;;
  "install latest") echo "$(cat {root}/channel) (Claude Code)" >{root}/installed
                    if [ -f {root}/moves ]; then echo {newer} >{root}/channel; fi ;;
  "install "*) echo "$2 (Claude Code)" >{root}/installed ;;
  *) echo "claude: not scripted in this test" >&2; exit 1 ;;
esac
"""


@unittest.skipUnless(sys.platform.startswith("linux"), "the fresh-install gate runs only on Linux")
@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FreshStandingFaults(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        self.install = Install(self.home)
        self.home.fake("claude", CLAUDE.format(root=shlex.quote(str(self.home.root)), newer=NEWER))
        self.gates = Gates(self.home)
        self.seat = self.install.seat()

    def update(self, new, old, code=0):
        """An upgrade whose fresh gate fails `new` on the new release and `old` on the one before;
        `old` None skips it, as a host that cannot run it does."""
        root = self.home.root
        (root / "installed").write_text(f"{OLD} (Claude Code)\n")
        (root / "channel").write_text(f"{NEW}\n")
        self.gates.reset()
        if old is None:
            self.gates.exit("e2e-fresh", 2)
        else:
            self.gates.exit("e2e-fresh", int(bool(new)), new, run=1)
            self.gates.exit("e2e-fresh", int(bool(old)), old, run=2)
        done = self.home.ak("update", timeout=120)
        self.assertEqual(done.code, code, done.out + done.err)
        self.assertIn("e2e-fresh", self.gates.ran(), done.out)  # no seat's turn held it back

    def tick(self):
        """One tick of the live install: the lines it typed into the seat."""
        before = len(self.seat.lines())
        done = self.home.run(self.install.ak, "watch")
        self.assertEqual(done.code, 0, done.out + done.err)
        return self.seat.lines()[before:]

    def log(self, line):
        return self.home.path / line.split("Log: ~/", 1)[1].split(". Fix", 1)[0]

    def test_kept_past_standing_checks_hands_them_back_once(self):
        self.update(["c", "d"], ["c", "d", "d2"])
        [line] = self.tick()
        self.assertRegex(line, r"^The fresh-install gate failed checks that fail on the release "
                               r"before too: FAIL  c / FAIL  d\. Log: ~/\S+\. "
                               r"Fix the standing faults\.$")
        self.assertIn("FAIL  c", self.log(line).read_text())
        self.update(["c", "d"], ["c", "d"])
        self.assertEqual(self.tick(), [])
        self.update(["q"], ["q"])
        [line] = self.tick()
        self.assertIn("too: FAIL  q. Log:", line)
        self.update(["c", "d"], ["c", "d"])     # told before q, and no clean pass since
        self.assertEqual(self.tick(), [])

    def test_handed_back_when_the_release_tested_does_not_install_again(self):
        (self.home.root / "moves").touch()
        self.update(["c"], ["c"], code=1)
        [line] = self.tick()
        self.assertIn("too: FAIL  c. Log:", line)

    def test_a_line_not_yet_told_stands_as_written(self):
        self.update(["c"], ["c"])
        first = set(self.home.path.rglob("*"))      # what that upgrade left, its log among it
        self.seat.show("claude-working-pane.txt")
        self.assertEqual(self.tick(), [])
        self.seat.show("claude-prompt-pane.txt")
        listed = self.home.ak("orch", "list")   # which reads the turn ended
        self.assertEqual(listed.code, 0, listed.err)
        self.update(["q"], ["q"])
        self.update([], [])
        self.update(["c"], ["c"])
        [line] = self.tick()
        self.assertIn("too: FAIL  c. Log:", line)
        self.assertIn(self.log(line), first)
        self.update(["q"], ["q"])   # a different set, at the first upgrade after it was told
        [line] = self.tick()
        self.assertIn("too: FAIL  q. Log:", line)

    def test_after_a_clean_pass_the_same_checks_are_handed_back_again(self):
        self.update(["c"], ["c"])
        self.assertEqual(len(self.tick()), 1)
        self.update([], None)       # a skipped gate is no clean pass
        self.update(["c"], ["c"])
        self.assertEqual(self.tick(), [])
        self.update([], [])
        self.update(["c"], ["c"])
        [line] = self.tick()
        self.assertIn("too: FAIL  c. Log:", line)


if __name__ == "__main__":
    unittest.main()
