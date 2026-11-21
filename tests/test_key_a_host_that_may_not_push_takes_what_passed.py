"""A host GitHub did not say may push checks origin's `live`, with no model turn, and takes it.

The model turns that test new agentkit code are paid once, on a host that may push to agentkit's
repository, whose tick pushes each commit it logs live to origin's `live`.  So a host GitHub never
told its login may push, or last told it may not, checks the commit origin's `live` names, where a
host it told may push checks origin's main, and runs its tests/live.sh with
AK_LIVE_NO_MODEL_CALLS=1; each moves to the commit its own check passed at.  GitHub's last answer
stands through a tick it does not answer.  A main with no tests/live.sh has no check to pass:
each of these hosts moves to it, though origin's `live` names an older commit.
Black-box: tests/fixtures/akinstall.py's Home, as
tests/test_key_a_host_that_may_push_says_what_passed.py builds it, once with a `gh` that answers
`false` to that question and once `true`, then exits 1 to it in both, and once with one that
exits 1 to it throughout; origin's `live` is set one commit behind its main twice, and each time
the test ticks until the install moves; then a commit takes tests/live.sh off origin's main, its
`live` left as it was, and the test ticks until the install moves again.  The
tests/live.sh on origin notes in HOME/checked the commit it ran at and its AK_LIVE_NO_MODEL_CALLS.
This test fails against `/bin/false`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import BOXED, Home, rerun_boxed
from fixtures.akinstall import Install

LIVE = """#!/bin/sh
echo "$(git rev-parse HEAD) ${AK_LIVE_NO_MODEL_CALLS:-unset}" >>"$HOME/checked"
"""
# `{said}`: GitHub's answer to whether this login may push to the checkout's repository, with a
# diagnostic on stderr that is no part of it; gh's exit 1 where it is ""
GH = """#!/bin/sh
if [ -n "{said}" ] && [ "$*" = "api repos/{{owner}}/{{repo}} --jq .permissions.push" ]; then
  echo {said}
  echo "request completed" >&2
  exit 0
fi
echo "gh: not scripted in this test" >&2
exit 1
"""


def moved(home, install):
    """Where the install stands once a tick moved it: `ak watch` until one does, one fails, or
    three minutes passed."""
    before, until = install.head(), time.monotonic() + 180
    while install.head() == before and time.monotonic() < until:
        if home.run(install.ak, "watch").code:
            break
    return install.head()


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class AHostThatMayNotPushTakesWhatPassed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refused = cls.story("false")
        cls.allowed = cls.story("true")
        cls.unanswered = cls.story("")

    @classmethod
    def story(cls, said):
        """A Home whose GitHub answers `said`, then nothing: for each of two moves, origin's
        `live` and main, and where the install stands after it; for one more, once origin's main
        has no tests/live.sh, that main and where the install stands after it; then what
        HOME/checked holds."""
        home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        install = Install(home)
        (install.seed / "tests").mkdir()
        (install.seed / "tests" / "live.sh").write_text(LIVE)
        moves = []
        for answer in (said, ""):
            home.fake("gh", GH.format(said=answer))
            live, main = install.advance(), install.advance()
            install.set_ref("refs/heads/live", live)
            moves.append((live, main, moved(home, install)))
        (install.seed / "tests" / "live.sh").unlink()
        unchecked = install.advance(), moved(home, install)
        checked = home.path / "checked"
        return moves, unchecked, checked.read_text().splitlines() if checked.exists() else []

    def test_a_host_that_may_not_push_checks_live_without_model_calls_and_moves_to_it(self):
        for said, (moves, _, checked) in (("false", self.refused), ("never", self.unanswered)):
            with self.subTest(said=said):
                self.assertEqual([head for _, _, head in moves], [live for live, _, _ in moves])
                self.assertEqual(checked, [f"{live} 1" for live, _, _ in moves])

    def test_a_host_that_may_push_checks_main_with_model_calls_and_moves_to_it(self):
        moves, _, checked = self.allowed
        self.assertEqual([head for _, _, head in moves], [main for _, main, _ in moves])
        self.assertEqual(checked, [f"{main} unset" for _, main, _ in moves])

    def test_each_host_moves_to_a_main_without_live_sh(self):
        for said, (_, (main, head), _) in (("false", self.refused), ("true", self.allowed),
                                           ("never", self.unanswered)):
            with self.subTest(said=said):
                self.assertEqual(head, main)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
