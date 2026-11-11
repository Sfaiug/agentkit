"""A member whose task names, `# once`, the suite as its base declared it is checked by the
suite once, as the target declares it now, after that `tests:` line changed while it waited; a
`# once` line that was never the suite runs besides it.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py.  The target's line
changes to give every test the word `now`, which the tests ignore.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, SUITE, rules

OWN = 'echo own >>"$(git rev-parse --git-common-dir)/own.log"'


class AnEarlierSpellingOfTheSuiteRunsOnce(unittest.TestCase):
    def test_the_suite_the_task_kept_runs_once_as_the_target_declares_it(self):
        line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        line.member({"api.txt": "x\n"})
        (line.members[0] / "task.md").write_text(
            f"# fix-1\n\n## Done when\n```bash\ntrue\n{SUITE}  # once\n{OWN}  # once\n```\n")
        line.rig.commit({"AGENTS.md": rules(f"{SUITE} now")}, "the suite gives its tests a word")
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1))
        self.assertEqual((line.whole(), line.whole("now")), (0, 1))
        self.assertEqual((line.rig.path / ".git" / "own.log").read_text(), "own\n")


if __name__ == "__main__":
    unittest.main()
