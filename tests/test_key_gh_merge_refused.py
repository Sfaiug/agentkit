"""Inside a seat, `gh pr merge` is refused: merging is ak's job once a PR passes review.

A PR lands through one path (owner rules): ak merges it once it passes review with green
checks, so a seat's own `gh pr merge`, in each form gh takes it, is refused with the reason and
never reaches gh.  Every other gh call a seat makes runs gh as typed, and so does the merge of
the inbox seat, which `ak watch` asks before merging someone else's PR, and every merge of a
worker or of no seat, as ak's own merges are.  Black-box: the shims a seat's launch installs
(tests/fixtures/shims.py), run as a seat's commands with a logging gh behind them, judged by
the exit code, what was printed and the calls gh received; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.shims import Shims

REFUSED = ("ak refused `gh pr merge`: merging is ak's job once a PR passes review with green "
           "checks. Leave it to land through the line; a seat runs no `gh pr merge` of its own.\n")
MERGES = (["pr", "merge", "7"],
          ["pr", "merge", "--squash", "--delete-branch", "fix-api"],
          ["pr", "-R", "acme/fix-api", "merge", "7"],    # gh's one option before the subcommand
          ["pr", "--repo", "acme/fix-api", "merge", "7"],
          ["pr", "--repo=acme/fix-api", "merge", "7"])
OUT = "https://github.com/acme/fix-api/pull/7\n"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class GhMerge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        for name in ("acme", "inbox"):
            Seat(cls.home, name)
        cls.shims.fake("gh", out=OUT)

    def gh(self, *args, seat="acme", env=None):
        """Run the seat's gh; what it did, and the calls gh received in it."""
        before = len(self.home.calls("gh"))
        done = self.shims.run("gh", *args, seat=seat, env=env)
        return done, self.home.calls("gh")[before:]

    def passes(self, args, seat="acme", env=None):
        done, reached = self.gh(*args, seat=seat, env=env)
        self.assertEqual((done.code, done.out, done.err), (0, OUT, ""))
        self.assertEqual(reached, [args])

    def test_each_form_of_a_seats_merge_is_refused_and_never_reaches_gh(self):
        for args in MERGES:
            with self.subTest(args=args):
                done, reached = self.gh(*args)
                self.assertEqual((done.code, done.out, done.err), (1, "", REFUSED))
                self.assertEqual(reached, [])

    def test_every_other_gh_call_of_a_seat_runs_gh_as_typed(self):
        for args in (["pr", "view", "7"], ["pr", "list"], ["pr", "create", "--fill"],
                     ["pr", "checkout", "merge"], ["--version"]):
            with self.subTest(args=args):
                self.passes(args)

    def test_the_inbox_seat_may_merge(self):
        self.passes(MERGES[0], seat="inbox")

    def test_the_inbox_is_the_seat_ak_is_told_it_is(self):
        self.passes(MERGES[0], env={"AGENTKIT_INBOX_SESSION": "acme"})

    def test_a_worker_and_a_command_of_no_seat_may_merge(self):
        for seat, env in (("acme", {"AK_RUN_ROLE": "worker"}), (None, None)):
            with self.subTest(seat=seat, env=env):
                self.passes(MERGES[0], seat=seat, env=env)


if __name__ == "__main__":
    unittest.main()
