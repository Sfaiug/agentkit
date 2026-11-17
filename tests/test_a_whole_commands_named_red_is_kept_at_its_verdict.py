"""A command run whole that names the tests it failed keeps them in history with its verdict.

The `tests:` suite run unsharded, or a task's `# once` command, runs no test alone: what its
last go named failed (`AK_FAILED`) is what the verdict blaming the member keeps, one landing row
a test on the commit its check ran on (`land.red_part`'s `failed`).  Offline: local Git, the
fixture's shell suites, fake launches and wakes.
"""

from contextlib import closing
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_landing_red_on_the_tip_pauses as fixture
from agentkit import history, land

NAMED = ('code=0; sh test_widget.sh || { '
         'echo test_widget.sh >>"${AK_FAILED:-/dev/null}"; code=1; }; exit $code')


class AWholeCommandsNamedRedIsKeptAtItsVerdict(unittest.TestCase):
    setUp = fixture.RedOnTheTip.setUp
    prepare = fixture.RedOnTheTip.prepare
    member = fixture.RedOnTheTip.member
    declare = fixture.RedOnTheTip.declare
    commit = fixture.RedOnTheTip.commit
    advance = fixture.RedOnTheTip.advance
    check = fixture.RedOnTheTip.check
    wait = fixture.RedOnTheTip.wait

    def blamed(self, own):
        (self.repo / "test_widget.sh").write_text("test ! -f broken.txt\n")
        self.declare("true" if own else NAMED)
        member = self.member(**{"broken.txt": "member breakage\n"})
        if own:
            (member / "task.md").write_text(
                "# acme\n\n## Done when\n```bash\n" + NAMED + "  # once\n```\n")
        history.start_run(member.name, repo=self.repo)
        self.advance()
        land.check_line(self.turn)
        self.assertEqual(self.wait(member)["fix"]["command"], NAMED)
        with closing(history._connect(readonly=True)) as db:
            checks = db.execute("SELECT tree FROM checks WHERE run_id=? AND kind='landing' "
                                "AND command=?", (member.name, NAMED)).fetchall()
            rows = db.execute("SELECT tree, test, flaky FROM test_reds WHERE run_id=? "
                              "AND kind='landing'", (member.name,)).fetchall()
        self.assertEqual(rows, [(checks[-1][0], "test_widget.sh", 0)])

    def test_the_suite_run_whole(self):
        self.blamed(own=False)

    def test_a_task_command_run_whole(self):
        self.blamed(own=True)


if __name__ == "__main__":
    unittest.main()
