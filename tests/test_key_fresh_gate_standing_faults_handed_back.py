"""The fresh-install gate's checks that fail on the release before too are handed back once.

On 27 Oct the fresh-install gate failed `c`, `d` and `d2` on every run, old release as new, and
`ak update` kept each upgrade past them, as agentkit's own checks, saying so only in its result
line.  Now such an upgrade leaves one line naming those checks, which the tick hands back once:
the same checks again hand back nothing new until the fresh gate passes with no check failed, a
different set is handed back, and a line not yet told stands as written whatever later upgrades
find.  `ak update` runs black-box through tests/fixtures/akbin.py, with a fake `claude` keeping
its installed release in a file and the gates stood in for by tests/fixtures/akgates.py; the
tick's delivery runs in-process on that Home's state, to a fake seat.
"""

from contextlib import ExitStack
import shlex
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akgates import Gates
from agentkit import config, update, watch

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
class FreshStandingFaults(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        self.home.fake("claude", CLAUDE.format(root=shlex.quote(str(self.home.root)), newer=NEWER))
        self.gates = Gates(self.home)
        self.ready, self.seen = True, []
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.home.path / ".agentkit"))
        for name, place in config.PLACES.items():
            stack.enter_context(patch.object(config, name, config.HOME / place))
        stack.enter_context(patch.object(update, "agentkit_dir", return_value=config.REPO))
        stack.enter_context(patch.object(update, "harnesses", return_value=()))
        stack.enter_context(patch.object(update, "_git", return_value=(
            0, "https://github.com/acme/agentkit.git")))
        stack.enter_context(patch.object(watch, "after_merge_fallback",
                                         return_value={"name": "atoll"}))
        stack.enter_context(patch.object(watch, "type_at_prompt", side_effect=self.type_line))

    def type_line(self, seat, line, log, typed=None, receipt=lambda mark: None, **_kw):
        self.seen.append((line, typed))
        receipt({"seat": seat["name"], "line": line})
        return self.ready

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

    def tick(self):
        """One tick's delivery: the lines it typed."""
        before = len(self.seen)
        update.keep_current(lambda line: None, now=1_000_000)
        return [line for line, _ in self.seen[before:]]

    def record(self):
        return (config.STATE / "fresh-gate-faults" / "handed").read_bytes()

    def test_kept_past_standing_checks_hands_them_back_once(self):
        self.update(["c", "d"], ["c", "d", "d2"])
        [line] = self.tick()
        self.assertRegex(line, r"^The fresh-install gate failed checks that fail on the release "
                               r"before too: FAIL  c / FAIL  d\. Log: ~/\S+\. "
                               r"Fix the standing faults\.$")
        log = self.home.path / line.split("Log: ~/", 1)[1].split(". Fix", 1)[0]
        self.assertIn("FAIL  c", log.read_text())
        self.assertEqual(self.tick(), [])
        self.update(["c", "d"], ["c", "d"])
        self.assertEqual(self.tick(), [])
        self.update(["q"], ["q"])
        [line] = self.tick()
        self.assertIn("too: FAIL  q. Log:", line)

    def test_handed_back_when_the_release_tested_does_not_install_again(self):
        (self.home.root / "moves").touch()
        self.update(["c"], ["c"], code=1)
        [line] = self.tick()
        self.assertIn("too: FAIL  c. Log:", line)

    def test_a_line_not_yet_told_stands_as_written(self):
        self.ready = False
        self.update(["c"], ["c"])
        [line] = self.tick()
        held = self.record()
        self.update(["q"], ["q"])
        self.update([], [])
        self.update(["c"], ["c"])
        self.assertEqual(self.record(), held)
        self.ready = True
        self.assertEqual(self.tick(), [line])
        self.assertEqual(self.seen[-1][1], {"seat": "atoll", "line": line})
        self.assertEqual(self.tick(), [])
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
