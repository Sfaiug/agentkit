"""A red batch whose suite piece named the tests that failed again alone is narrowed by those
tests first: each halfway step runs them alone, a pass, each named as run, moving the search
deeper, and the stack right behind the deepest one they pass in is the member that turned them
red.  A confirmed failure moves the search earlier.  It fixes; the rest rebuild and land in
the same pass.  An inconclusive step gets its whole check, as without them -- a test a later
member added is not there yet -- so an empty run there alone blames no one.

Offline: real Git and checks, the suite a shell runner that runs only those asked for and
names each it runs and each that fails, sandbox records, fake processes and wakes.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander
import test_merge_train
from agentkit import gate, land, run

# t_fine then t_tax, or just those AK_ONLY lists; t_tax fails on a tree holding broken.txt.
NAMED = ('if [ -n "$AK_ONLY" ]; then tests=$(cat "$AK_ONLY"); else tests="t_fine t_tax"; fi; '
         ': "$AK_SHARD"; code=0; for t in $tests; do echo "$t" >> "${AK_RAN:-/dev/null}"; '
         'if [ "$t" = t_tax ] && [ -f broken.txt ]; '
         'then echo "FAIL $t"; echo "$t" >> "${AK_FAILED:-/dev/null}"; code=1; '
         'else echo "PASS $t"; fi; done; exit $code')
# Every test_*.sh the tree holds, or those AK_ONLY lists that it holds, naming each it runs.
FILES = ('if [ -n "$AK_ONLY" ]; then tests=$(cat "$AK_ONLY"); else tests=$(ls test_*.sh); fi; '
         ': "$AK_SHARD"; code=0; for t in $tests; do [ -f "$t" ] || continue; '
         'echo "$t" >> "${AK_RAN:-/dev/null}"; bash "$t" || '
         '{ echo "$t" >> "${AK_FAILED:-/dev/null}"; code=1; }; done; exit $code')


def on(*members):
    """The files a stack of those members holds."""
    return {f"member-{n}.txt" for n in members}


class NarrowFixture(test_lander.LanderFixture):
    stacked_files = test_merge_train.MergeTrain.stacked_files
    assert_members_deliver_in_order = test_merge_train.MergeTrain.assert_members_deliver_in_order

    def check(self, cmds, cwd, log_path, *args, **kw):
        self.trees.append(set(run.git(cwd, "ls-tree", "--name-only", "HEAD").splitlines()))
        return super().check(cmds, cwd, log_path, *args, **kw)

    def setUp(self):
        super().setUp()
        self.trees = []

    def narrow(self, suite, base, count, culprit, change):
        """Land `count` members on a target declaring `suite` and holding `base`, the
        `culprit` adding `change`: the checks that ran, as (members, tests), its red."""
        for name, text in {"AGENTS.md": f"---\ntests: {suite}\n---\n", **base}.items():
            (self.repo / name).write_text(text)
        self.commit("declare a suite that names its failed tests")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        members = [self.member(f"member-{n}", joined=n, **{
            f"member-{n}.txt": f"{n}\n", **(change if n == culprit else {})})
            for n in range(1, count + 1)]
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=1):
            land.check_line(self.turn)
        good = [member for n, member in enumerate(members, 1) if n != culprit]
        for index, member in enumerate(good):
            wait = self.wait(member)
            self.assertNotIn("fix", wait)
            self.assertEqual(wait["after"], {m.name: self.wait(m)["land"] for m in good[:index]})
            self.assertFalse(set(change) & self.stacked_files(wait["land"]))
        # red on top of members ahead, it waits for them to leave the line; first, it is fixed now
        ahead = {m.name: self.wait(m)["land"] for m in members[:culprit - 1]}
        self.assertEqual(self.wait(members[culprit - 1])["after"], ahead)
        self.assertEqual(sorted(call.args[0] for call in self.wake.call_args_list),
                         sorted(m.name for m in members if m in good or not ahead))
        self.assert_members_deliver_in_order(good)
        self.assert_cleaned()
        checked = [({f for f in files if f.startswith("member-")}, kw.get("only"))
                   for files, (_, _, kw) in zip(self.trees, self.checks)]
        return checked, self.wait(members[culprit - 1])["fix"]


class RedNarrowedByItsFailedTests(NarrowFixture, unittest.TestCase):
    def test_a_bad_fourth_of_six_is_found_by_its_failed_tests_alone(self):
        checked, fix = self.narrow(NAMED, {}, 6, 4, {"broken.txt": "broken\n"})
        self.assertEqual(checked, [
            (on(1, 2, 3, 4, 5, 6), None),       # the deepest, whole: red on t_tax
            (on(1, 2, 3), ["t_tax"]),           # halfway: they pass, deeper
            (on(1, 2, 3, 4), ["t_tax"]),        # confirmed red, behind their pass
            (on(1, 2, 3, 5, 6), None)])         # rebuilt, whole
        self.assertEqual(fix["tests"], ["t_tax"])
        self.assertIn("FAIL t_tax", Path(fix["log"]).read_text())

    def test_a_test_a_later_member_added_blames_no_stack_without_it(self):
        checked, fix = self.narrow(FILES, {"test_existing.sh": "exit 0\n"}, 4, 3,
                                   {"test_new.sh": "exit 1\n"})
        self.assertEqual(checked, [
            (on(1, 2, 3, 4), None),             # the deepest, whole: red on test_new.sh
            (on(1, 2), ["test_new.sh"]),        # not there yet: runs none, proves nothing
            (on(1, 2), None),                   # its whole check: green
            (on(1, 2, 3), ["test_new.sh"]),      # confirmed red, right behind green
            (on(1, 2, 4), None)])               # rebuilt, whole
        self.assertEqual(fix["tests"], ["test_new.sh"])

    def test_a_checkout_the_tests_alone_moved_is_put_back_and_moves_no_branch(self):
        run.git(self.repo, "branch", "kept")
        kept = run.git(self.repo, "rev-parse", "kept")
        # Run alone on a stack ahead of the bad one, the tests check out the branch `kept`.
        moving = '[ -z "$AK_ONLY" ] || [ -f broken.txt ] || git checkout -q kept; '
        checked, _ = self.narrow(moving + NAMED,
                                 {}, 6, 4, {"broken.txt": "broken\n"})
        self.assertEqual(checked, [
            (on(1, 2, 3, 4, 5, 6), None),
            (on(1, 2, 3), ["t_tax"]),           # moved its checkout: proves nothing
            (on(1, 2, 3), None),                # on the stack itself: green
            (on(1, 2, 3, 4), ["t_tax"]),
            (on(1, 2, 3, 5, 6), None)])
        self.assertEqual(run.git(self.repo, "rev-parse", "kept"), kept)


if __name__ == "__main__":
    unittest.main()
