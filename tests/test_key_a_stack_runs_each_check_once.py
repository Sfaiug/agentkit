"""A whole check of stacked changes runs each command its members owe once on the tested tree.
A change that rewrites the `tests:` line makes that line every later stack's own check too,
besides the target's suite; a member behind it with a `# once` check of its own brought the
rewritten line along a second time.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py.  Its suite is
sharded, so one whole check fits and covers both members.  The first rewrites the `tests:` line
to give every test the word `now`, which the tests ignore; the second has a `# once` check of
its own.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, SUITE, rules

OWN = 'echo own >>"$(git rev-parse --git-common-dir)/own.log"'


class AStackRunsEachCheckOnce(unittest.TestCase):
    def test_a_rewritten_suite_line_runs_once_for_the_stack_behind_it(self):
        line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        line.member({"AGENTS.md": rules(f"{SUITE} now")})
        line.member({"api.txt": "x\n"})
        (line.members[1] / "task.md").write_text(
            f"# fix-2\n\n## Done when\n```bash\ntrue\n{OWN}  # once\n```\n")
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in (1, 2):
            self.assertIn("land", line.verdict(n))
        self.assertEqual((line.whole(), line.whole("now")), (1, 1))
        self.assertEqual((line.rig.path / ".git" / "own.log").read_text(), "own\n")


if __name__ == "__main__":
    unittest.main()
