"""A lander's pass goes on after the checkout of a member it landed is removed, as a delivery
removes it: the pass works from the project's checkout, which no landing takes away.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, in the case of tests/test_key_an_unnamed_red_narrows_by_whole_checks.py:
of six members the third breaks a file a piece loads, a red naming no test, narrowed by whole
checks, so the members under it land while the pass still has the stacks behind it to rebuild.
The first member's record names a checkout of its own, a worktree of the repository on its
branch, and the suite removes it as a check starts once that record holds `land`.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akline import Line
from test_key_an_unnamed_red_narrows_by_whole_checks import MEMBERS, TESTS


class APassOutlivesItsFirstMembersCheckout(unittest.TestCase):
    def test_the_culprit_alone_is_sent_back_after_the_first_member_s_checkout_is_gone(self):
        home = Home()
        record = home.path / ".agentkit" / "runs" / "fix-1" / "run.json"
        # In the repository's Git storage, as a boxed check may write nowhere else outside its own.
        leave = (f"grep -q '\"land\":' {shlex.quote(str(record))} 2>/dev/null && git worktree "
                 'remove --force "$(git rev-parse --git-common-dir)/fix-1" 2>/dev/null\n')
        line = Line({**TESTS, "suite.sh": leave + TESTS["suite.sh"]}, home=home)
        self.addCleanup(line.close)
        for files in MEMBERS:
            line.member(files)
        checkout = line.rig.path / ".git" / "fix-1"
        line.rig.git("worktree", "add", "-q", str(checkout), "ak/fix-1")
        record.write_text(json.dumps({**json.loads(record.read_text()), "worktree": str(checkout)}))
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertFalse(checkout.exists())
        for n in range(1, 7):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 3 else ["land"], (n, done.out + done.err))


if __name__ == "__main__":
    unittest.main()
