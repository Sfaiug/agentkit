"""A red harness gate runs again on the old release; checks failing there too are agentkit's.

From 21 to 24 Oct the fresh-install gate failed two menu checks on every harness, old release as
new, and every harness upgrade was undone for it.  Now `ak update` answers a red gate by putting
the old release back and running that gate again: when every check the new release failed also
fails there, the new release goes back in, the gates after it run, and the result line names
those checks as agentkit's, never the harness's red.  A check that passes on the old release, or
a red that names no check, stays the harness's red: the old release stays.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, with a fake `claude`
that keeps its installed release in a file and the gates stood in for by
tests/fixtures/akgates.py.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akgates import Gates

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
LATER = ["e2e-fresh"] if sys.platform.startswith("linux") else []


class StandingFault(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        root = self.home.root
        (root / "installed").write_text(f"{OLD} (Claude Code)\n")
        (root / "channel").write_text(f"{NEW}\n")
        self.home.fake("claude", CLAUDE.format(root=shlex.quote(str(root)), newer=NEWER))
        self.gates = Gates(self.home)

    def update(self):
        done = self.home.ak("update", timeout=120)
        return done.code, done.out + done.err

    def release(self):
        return (self.home.root / "installed").read_text().split()[0]

    def handed(self):
        path = self.home.path / ".agentkit/state/harness-gates/claude/handed"
        return json.loads(path.read_text()) if path.exists() else None

    def live(self, new, old):
        """live fails `new` on the new release and `old` on the one before."""
        self.gates.reset()
        self.gates.exit("live", 1, new, run=1)
        self.gates.exit("live", 1 if old else 0, old, run=2)

    def test_checks_failing_on_the_old_release_too_keep_the_new_one(self):
        for _ in range(2):    # a second time is no second red either
            (self.home.root / "installed").write_text(f"{OLD} (Claude Code)\n")
            self.live(["d", "d2"], ["d", "d2", "q"])
            code, said = self.update()
            self.assertEqual(code, 0, said)
            self.assertEqual(self.release(), NEW)
            self.assertEqual(self.gates.ran(), ["live", "live", *LATER])
            self.assertRegex(said, r"(?m)^update: .*live failed only agentkit's own checks "
                                   r"\(d, d2\)")
            self.assertIsNone(self.handed())

    def test_a_channel_that_moved_since_the_gate_is_a_red(self):
        (self.home.root / "moves").touch()
        self.live(["d"], ["d"])
        code, said = self.update()
        self.assertEqual(code, 1, said)
        self.assertEqual(self.release(), OLD)
        self.assertEqual(self.gates.ran(), ["live", "live"])

    def test_a_check_passing_on_the_old_release_puts_it_back_and_is_named(self):
        for _ in range(2):
            self.live(["d", "codex-turn"], ["d"])
            code, said = self.update()
            self.assertEqual(code, 1, said)
            self.assertEqual(self.release(), OLD)
            self.assertEqual(self.gates.ran(), ["live", "live"])
        self.assertIn("twice in a row (live): codex-turn. Log:", self.handed()["line"])

    def test_a_red_naming_no_check_puts_the_old_release_back(self):
        self.gates.exit("live", 1)
        code, said = self.update()
        self.assertEqual(code, 1, said)
        self.assertEqual(self.release(), OLD)
        self.assertEqual(self.gates.ran(), ["live"])


if __name__ == "__main__":
    unittest.main()
