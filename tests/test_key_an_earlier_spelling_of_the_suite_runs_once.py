"""A member whose task names, `# once`, the suite as its base declared it is checked by the
suite once, as the target declares it now, after that `tests:` line changed while it waited; so
is a repair of the target whose task names the suite as the tip it repairs declared it, started
from the changed line; a `# once` line that was never the suite runs besides it.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py.  The target's line
changes to give every test the word `now`, which the tests ignore.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, SUITE, rules

OWN = 'echo own >>"$(git rev-parse --git-common-dir)/own.log"'


class AnEarlierSpellingOfTheSuiteRunsOnce(unittest.TestCase):
    def setUp(self):
        self.line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(self.line.close)

    def member(self, **record):
        """The line's member, its task naming the suite as the target first declared it and a
        check of its own, with `record` in its record."""
        self.line.member({"api.txt": "x\n"})
        directory = self.line.members[0]
        (directory / "task.md").write_text(
            f"# fix-1\n\n## Done when\n```bash\ntrue\n{SUITE}  # once\n{OWN}  # once\n```\n")
        path = directory / "run.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), **record}))

    def change(self):
        """The commit from which the target's line gives its tests a word."""
        return self.line.rig.commit({"AGENTS.md": rules(f"{SUITE} now")},
                                    "the suite gives its tests a word")

    def assert_lands_on_the_suite_once(self):
        done = self.line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", self.line.verdict(1))
        self.assertEqual((self.line.whole(), self.line.whole("now")), (0, 1))
        self.assertEqual((self.line.rig.path / ".git" / "own.log").read_text(), "own\n")

    def test_the_suite_the_task_kept_runs_once_as_the_target_declares_it(self):
        self.member()
        self.change()
        self.assert_lands_on_the_suite_once()

    def test_a_repair_started_as_the_line_changed_runs_the_suite_once_too(self):
        """Its base declares the changed line already; the tip the red was seen on, the words
        its task kept (11 Nov 2026: a second suite run of 43 minutes on every place)."""
        seen = self.line.base
        started = self.change()
        self.member(repair={"target": "main", "command": SUITE}, repair_tip=seen,
                    base_sha=started)
        self.assert_lands_on_the_suite_once()


if __name__ == "__main__":
    unittest.main()
