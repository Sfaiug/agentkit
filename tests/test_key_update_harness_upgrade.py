"""A real `ak update` upgrades a harness, gates it, and puts the old release back on a red gate.

This is how every seat's harness moves to a new release: ak runs the harness's `[update]
upgrade` command, then the acceptance gates (live, the fresh install), and keeps the new
release only when they pass.  On a red gate it reinstalls the release it started from with
`[update] revert` and says so; a reinstall that does not take is named with the command to run
by hand, since a broken revert leaves every seat on a broken harness.  A second red gate in a row
is kept for the tick to hand back, and a green one clears it.  While a seat is working, no
harness moves.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with a fake `claude` that keeps its installed release in a file and the
gates stood in for by tests/fixtures/akgates.py.
"""

import json
import re
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akgates import Gates
from fixtures.akseat import Seat

OLD, NEW = "2.1.0", "2.2.0"
# What `claude install` does: `latest` puts the channel's release in, a version that one.  A
# flag file makes either refuse, as an installer that fails does.
CLAUDE = """#!/bin/sh
case "$1 $2" in
  "--version "*) cat {installed} ;;
  "install latest") [ -f {flags}/latest-fails ] && exit 1
                    echo "{new} (Claude Code)" >{installed} ;;
  "install "*) [ -f {flags}/reinstall-fails ] && exit 1; echo "$2 (Claude Code)" >{installed} ;;
  *) echo "claude: not scripted in this test" >&2; exit 1 ;;
esac
"""
# The fresh-install gate runs only on Linux; elsewhere the report says it was skipped.
GATES = ["live"] + (["e2e-fresh"] if sys.platform.startswith("linux") else [])


def claude(home):
    """A fake claude on OLD; the path of the file holding what it has installed."""
    installed = home.root / "claude-installed"
    installed.write_text(f"{OLD} (Claude Code)\n")
    home.fake("claude", CLAUDE.format(installed=shlex.quote(str(installed)),
                                      flags=shlex.quote(str(home.root)), new=NEW))
    return installed


class HarnessUpgrade(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        self.installed = claude(self.home)
        self.gates = Gates(self.home)

    def update(self):
        done = self.home.ak("update", timeout=120)
        return done.code, done.out + done.err

    def release(self):
        return self.installed.read_text().split()[0]

    def handed(self):
        """What the tick would hand back about claude's gate, or None."""
        path = self.home.path / ".agentkit/state/harness-gates/claude/handed"
        return json.loads(path.read_text()) if path.exists() else None

    def test_a_green_upgrade_runs_every_gate_and_keeps_the_new_release(self):
        code, said = self.update()
        self.assertEqual(code, 0, said)
        self.assertEqual(self.release(), NEW)
        self.assertEqual(self.gates.calls(), [(gate, "1") for gate in GATES])
        self.assertRegex(said, rf"(?m)^update: claude: upgraded\b.*{re.escape(NEW)}")

    def test_each_red_gate_puts_the_old_release_back_and_says_so(self):
        for at, gate in enumerate(GATES):
            with self.subTest(gate):
                self.installed.write_text(f"{OLD} (Claude Code)\n")
                self.gates.reset()
                self.gates.exit(gate, 1)
                code, said = self.update()
                self.assertEqual(code, 1, said)
                self.assertEqual(self.release(), OLD)
                # the gates after a red one never run
                self.assertEqual(self.gates.ran(), GATES[:at + 1])
                self.assertRegex(said, rf"(?m)^update: claude: reverted\b.*{re.escape(OLD)}")

    def test_a_reinstall_that_does_not_take_names_the_command_to_run_by_hand(self):
        (self.home.root / "reinstall-fails").touch()
        self.gates.exit("live", 1)
        code, said = self.update()
        self.assertEqual(code, 1, said)
        self.assertEqual(self.release(), NEW)
        self.assertRegex(said, r"(?m)^update: claude: cannot revert\b.*"
                               rf"`claude install {re.escape(OLD)}` by hand")

    def test_an_upgrade_command_that_fails_runs_no_gate(self):
        (self.home.root / "latest-fails").touch()
        code, said = self.update()
        self.assertEqual(code, 1, said)
        self.assertEqual(self.release(), OLD)
        self.assertEqual(self.gates.ran(), [])
        self.assertRegex(said, r"\bclaude\b.*could not be upgraded")
        self.assertIsNone(self.handed())

    def test_a_second_red_gate_in_a_row_is_kept_to_hand_back_until_one_passes(self):
        self.gates.exit("live", 1)
        self.assertEqual(self.update()[0], 1)
        self.assertNotIn("line", self.handed() or {})     # one red can be the host's
        self.assertEqual(self.update()[0], 1)
        line = self.handed()["line"]
        self.assertIn("claude", line)
        self.assertIn("live", line)
        self.gates.reset()
        self.assertEqual(self.update()[0], 0)
        self.assertIsNone(self.handed())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhileASeatWorks(unittest.TestCase):
    def test_no_harness_moves_until_the_seat_is_done(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            installed = claude(home)
            gates = Gates(home)
            seat = Seat(home, "acme", screen="claude-working-pane.txt")
            # a look at the seats, as the menu and the tick take, before the update reads them
            self.assertEqual(home.ak("orch", "list").code, 0)
            done = home.ak("update", timeout=120)
            self.assertEqual(done.code, 0, done.err)
            self.assertIn("1 sessions are working (acme)", done.out + done.err)
            self.assertEqual((installed.read_text().split()[0], gates.ran()), (OLD, []))
            seat.show("claude-prompt-pane.txt")
            self.assertEqual(home.ak("orch", "list").code, 0)
            done = home.ak("update", timeout=120)
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual((installed.read_text().split()[0], gates.ran()), (NEW, GATES))


if __name__ == "__main__":
    unittest.main()
