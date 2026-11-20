"""A tick that logs a commit live pushes it to origin's `live`, and origin says whether it may.

The model turns that test new agentkit code are paid once, on a host that may push to
agentkit's repository, and every other host takes only what passed there.  So a tick that logs
`agentkit is live at <commit>` pushes that commit, unforced, to origin's branch `live`, and
says `origin's live is at <commit>` once origin took it; a refusal is said nowhere and not
tried again, and a `live` the commit is not ahead of stays.  Black-box: tests/fixtures/
akinstall.py's Home, as tests/test_key_a_version_goes_live_built.py builds it, first under the
fixture's `ssh`, which refuses git's push, then under one that serves it (`PUSH`) beside the
fetch; origin's `live` is read from its bare repository.  Each case pins every line the tick
printed but a pass's timing, which host load alone decides; this test fails against `/bin/false`.
"""

from collections import namedtuple
import re
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import BOXED, Home, rerun_boxed
from fixtures.akinstall import FETCH, PUSH, Install

# the fixture's ssh, serving git's push of origin beside its fetch
SSH = f"""#!/bin/sh
case "$*" in
  *"{' '.join(FETCH)}") exec git-upload-pack {{bare}} ;;
  *"{' '.join(PUSH)}") exec git-receive-pack {{bare}} ;;
esac
echo "ssh: not scripted in this test" >&2
exit 1
"""
TIMED = re.compile(r" took \d+(\.\d+)? s$")
DOWN = "WARN GitHub is unavailable; PR checks skipped (gh: not scripted in this test)"
Tick = namedtuple("Tick", "code err said head live")


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class AHostThatMayPushSaysWhatPassed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        cls.install = install = Install(home)
        cls.start = install.head()
        cls.tick()      # the checkout's daily git gc runs at the first tick, no case's story
        cls.unpushed = install.advance()
        cls.refused = cls.tick()
        cls.tick()      # a tick of the version live completes: only then may the next move start
        home.fake("ssh", SSH.format(bare=shlex.quote(str(install.bare))))
        cls.tip = install.advance()
        cls.pushed = cls.tick()
        install.set_ref("refs/heads/live", cls.start)
        cls.idle = cls.tick()
        cls.beside = install._git(install.bare, "commit-tree", "-p", cls.start,
                                  "-m", "beside main", f"{cls.start}^{{tree}}")
        install.set_ref("refs/heads/live", cls.beside)
        cls.next = install.advance()
        cls.kept = cls.tick()

    @classmethod
    def tick(cls):
        """One `ak watch` of the live copy: each line it printed but its timings, where the
        checkout stands then, and the commit origin's `live` names, "" for none."""
        done = cls.home.run(cls.install.ak, "watch")
        said = [line for line in [*done.out.splitlines(), *done.err.splitlines()]
                if not TIMED.search(line)]
        return Tick(done.code, done.err, said, cls.install.head(), cls.install._git(
            cls.install.bare, "for-each-ref", "--format=%(objectname)", "refs/heads/live"))

    def test_a_host_origin_refuses_goes_live_as_ever_and_origin_has_no_live(self):
        self.assertEqual(self.refused.code, 0, self.refused.err)
        self.assertEqual(self.refused.head, self.unpushed)
        self.assertEqual(self.refused.said, [f"agentkit is live at {self.unpushed[:12]}", DOWN])
        self.assertEqual(self.refused.live, "")

    def test_a_tick_that_logs_a_commit_live_leaves_origins_live_naming_it(self):
        self.assertEqual(self.pushed.code, 0, self.pushed.err)
        self.assertEqual(self.pushed.head, self.tip)
        self.assertEqual(self.pushed.said, [f"agentkit is live at {self.tip[:12]}",
                                            f"origin's live is at {self.tip[:12]}", DOWN])
        self.assertEqual(self.pushed.live, self.tip)

    def test_a_tick_that_logs_none_leaves_live_where_it_was_set_back(self):
        self.assertEqual(self.idle.code, 0, self.idle.err)
        self.assertEqual(self.idle.head, self.tip)
        self.assertEqual(self.idle.said, [DOWN])
        self.assertEqual(self.idle.live, self.start)

    def test_a_live_beside_main_stays_after_the_next_commit_is_logged_live(self):
        self.assertEqual(self.kept.code, 0, self.kept.err)
        self.assertEqual(self.kept.head, self.next)
        self.assertEqual(self.kept.said, [f"agentkit is live at {self.next[:12]}", DOWN])
        self.assertEqual(self.kept.live, self.beside)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
